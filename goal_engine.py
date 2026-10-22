"""GOAL ENGINE - the undefeatable checklist persistence layer behind /goal.

Operator directive (2026-10-23): a skill that, combined with a checklist,
will not stop until the checklist is COMPLETELY done - no exceptions - and
survives anything, polling every GOAL_TICK_S (default 30s) to make sure
there is THROUGHPUT, with a multi-layer escalating system when there is not.

LAWS (each one is pinned by evals/goal_engine_test.py):
  1. NO EXCEPTIONS: status becomes "complete" only when EVERY item is done.
     A stuck item never stops the goal - it escalates while the goal works.
  2. SURVIVES ANYTHING: state is atomic-on-disk JSON (temp + os.replace)
     under cross-process locks (hub_ipc). Any session, any process, any
     reboot resumes from the ledger; goals/ACTIVE names the current goal.
  3. THROUGHPUT: every real step calls `progress` - the heartbeat. No
     heartbeat within the stall window = a stall.
  4. MULTI-LAYER ESCALATION (never stops, only escalates):
       L0 CONTINUE - throughput is live; keep working the item.
       L1 NUDGE    - stale: re-read the item, resume immediately.
       L2 REPLAN   - decompose the item into smaller sub-steps, then execute.
       L3 SPAWN    - hand the item to a FRESH sub-agent with full context
                     (and record it in ALERTS.md for the operator).
       L4 ALERT+CONTINUE - operator alert recorded; the goal keeps going by
                     working the NEXT pending item and re-attempting the stuck
                     one next cycle. The ladder NEVER ends the goal.
     Any progress event resets the ladder to L0.

State: goals/<slug>/state.json (+ watchdog.log, ALERTS.md). The watchdog
loop is a single-instance detached process; install_goal_watchdog.ps1
registers the "Goal Watchdog" scheduled task (logon + every-minute
triggers) that keeps it alive - the survive-anything layer.

Usage:
    py -3.12 goal_engine.py init --title "X" --checklist plan.md
    py -3.12 goal_engine.py next            # the item to work + directive
    py -3.12 goal_engine.py progress --note "edited foo.py:12"
    py -3.12 goal_engine.py done 1
    py -3.12 goal_engine.py tick            # ONE 30s-poll evaluation
    py -3.12 goal_engine.py watchdog        # the survivor loop
    py -3.12 goal_engine.py status | list | watchdog-auto
"""
import argparse
import contextlib
import io
import json
import os
import re
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
GOALS_DIR = os.getenv("GOALS_DIR") or os.path.join(ROOT, "goals")
ACTIVE_FILE = os.path.join(GOALS_DIR, "ACTIVE")
MAX_LOG = 400  # bounded in-state event log


def _env_float(name, default):
    try:
        return max(0.05, float(os.getenv(name, "") or default))
    except (TypeError, ValueError):
        return float(default)


def tick_seconds():
    return _env_float("GOAL_TICK_S", 30.0)


def stall_seconds():
    """How long without a heartbeat counts as a stall (default: the tick)."""
    return _env_float("GOAL_STALE_S", tick_seconds())


def max_escalation():
    try:
        return max(1, int(os.getenv("GOAL_MAX_ESCALATION", "4") or 4))
    except (TypeError, ValueError):
        return 4


def _slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", (title or "goal").lower()).strip("-")
    return (s or "goal")[:48]


def _goal_dir(slug):
    return os.path.join(GOALS_DIR, slug)


def _state_path(slug):
    return os.path.join(_goal_dir(slug), "state.json")


ESCALATION_ACTIONS = {
    1: ("NUDGE", "re-read the item, resume it immediately - no re-planning, "
                 "just continue the work"),
    2: ("REPLAN", "decompose the item into smaller concrete sub-steps and "
                  "execute them one by one"),
    3: ("SPAWN", "hand the item to a FRESH sub-agent with the full goal "
                 "context; record the stall in ALERTS.md"),
    4: ("ALERT+CONTINUE", "the operator alert is recorded; work the NEXT "
                          "pending item now and re-attempt the stuck item "
                          "next cycle - the goal does NOT stop"),
}


def _now():
    return time.time()


def _load(slug):
    with io.open(_state_path(slug), encoding="utf-8") as fh:
        return json.load(fh)


def _save(slug, state):
    """Atomic write (temp + replace): a crash mid-write never corrupts the
    ledger - the survive-anything law."""
    d = _goal_dir(slug)
    os.makedirs(d, exist_ok=True)
    tmp = _state_path(slug) + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, _state_path(slug))


def _event(state, kind, detail):
    state.setdefault("log", []).append(
        {"ts": round(_now(), 3), "kind": kind, "detail": str(detail)[:300]})
    if len(state["log"]) > MAX_LOG:
        state["log"] = state["log"][-MAX_LOG:]


def _lock(slug):
    """Cross-process lock over the whole goal dir (hub_ipc: bounded,
    degrades unlocked rather than raising)."""
    try:
        import hub_ipc
        return hub_ipc.locked_path(_goal_dir(slug), timeout=5.0)
    except Exception:  # noqa: BLE001 - the engine never dies on locking
        return contextlib.nullcontext()


def parse_checklist(text):
    """Markdown checklist -> items: '- [ ] x', '* [ ] x', '1. x', '1) x'.
    Pre-checked rows load as already-done items."""
    items = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        m = (re.match(r"^[-*]\s+\[( |x|X)\]\s+(.+)$", s)
             or re.match(r"^(\d+)[.)]\s+(.+)$", s))
        if m:
            groups = m.groups()
            if len(groups) == 2 and groups[0] in (" ", "x", "X") \
                    and s.startswith(("- [", "* [", "- [", "* [")):
                items.append({"text": groups[1].strip(),
                              "pre_done": groups[0].lower() == "x"})
            elif len(groups) == 2 and groups[0].isdigit():
                items.append({"text": groups[1].strip(), "pre_done": False})
    return items


def cmd_init(args):
    items = []
    if args.checklist:
        with io.open(args.checklist, encoding="utf-8") as fh:
            items = parse_checklist(fh.read())
    for extra in args.item or []:
        items.append({"text": extra, "pre_done": False})
    if not items:
        raise SystemExit("no items: pass --checklist FILE or --item TEXT")
    slug = _slugify(args.title)
    state = {
        "slug": slug, "title": args.title,
        "created": _now(), "status": "running",
        "items": [
            {"id": i + 1, "text": it["text"],
             "status": "done" if it["pre_done"] else "pending",
             "attempts": 0, "escalation": 0,
             "done_ts": _now() if it["pre_done"] else None}
            for i, it in enumerate(items)],
        "heartbeat": {"last_progress_ts": _now(),
                      "last_event": "goal initialized"},
        "escalation": {"level": 0, "since": _now(), "history": []},
        "watchdog": {"last_tick_ts": 0.0, "ticks": 0},
        "log": [],
    }
    _event(state, "init", f"{len(items)} items")
    with _lock(slug):
        if os.path.exists(_state_path(slug)):
            raise SystemExit(f"goal already exists: {slug}")
        _save(slug, state)
    with io.open(ACTIVE_FILE, "w", encoding="utf-8") as fh:
        fh.write(slug)
    print(f"GOAL {slug} | {len(items)} items | ACTIVE")
    _print_next(state)


def _active_slug():
    try:
        with io.open(ACTIVE_FILE, encoding="utf-8") as fh:
            slug = fh.read().strip()
        if slug and os.path.exists(_state_path(slug)):
            return slug
    except OSError:
        pass
    raise SystemExit("no ACTIVE goal: run init first (or pass --slug)")


def _current_item(state):
    for it in state["items"]:
        if it["status"] != "done":
            return it
    return None


def _print_next(state):
    item = _current_item(state)
    if item is None:
        print("GOAL COMPLETE - every checklist item is done.")
        return
    pending = [i["id"] for i in state["items"] if i["status"] != "done"]
    print(f"ITEM {item['id']}/{len(state['items'])}: {item['text']}")
    print(f"REMAINING: {pending} | ESCALATION: L{state['escalation']['level']}")


def cmd_next(args):
    slug = args.slug or _active_slug()
    with _lock(slug):
        state = _load(slug)
    if state["status"] == "complete":
        print("GOAL COMPLETE - every checklist item is done.")
        return
    _print_next(state)


def cmd_progress(args):
    slug = args.slug or _active_slug()
    with _lock(slug):
        state = _load(slug)
        if state["status"] == "complete":
            print("GOAL COMPLETE")
            return
        prev = state["escalation"]["level"]
        state["heartbeat"] = {"last_progress_ts": _now(),
                              "last_event": args.note or "progress"}
        state["escalation"] = {"level": 0, "since": _now(),
                               "history": state["escalation"]["history"]}
        _event(state, "progress", args.note or "")
        _save(slug, state)
    print(f"PROGRESS recorded (L{prev} -> L0): {args.note or ''}")


def cmd_done(args):
    slug = args.slug or _active_slug()
    with _lock(slug):
        state = _load(slug)
        item = next((i for i in state["items"] if i["id"] == args.item_id),
                    None)
        if item is None:
            raise SystemExit(f"no item {args.item_id}")
        if item["status"] != "done":
            item["status"] = "done"
            item["done_ts"] = _now()
            _event(state, "done", f"item {args.item_id}: {item['text']}")
        # LAW 1 - no exceptions: complete only when EVERY item is done.
        if all(i["status"] == "done" for i in state["items"]):
            state["status"] = "complete"
            _event(state, "complete", "every checklist item is done")
        _save(slug, state)
    left = [i["id"] for i in state["items"] if i["status"] != "done"]
    if state["status"] == "complete":
        print("GOAL COMPLETE - every checklist item is done. Undefeatable.")
    else:
        print(f"ITEM {args.item_id} done. REMAINING: {left}")
        _print_next(state)


def _alert(slug, state, level, item, stale):
    """L3+: the operator-visible stall record (the goal still continues)."""
    path = os.path.join(_goal_dir(slug), "ALERTS.md")
    line = (f"- {time.strftime('%Y-%m-%d %H:%M:%S')} L{level} "
            f"({ESCALATION_ACTIONS[level][0]}): item {item['id']} "
            f"'{item['text']}' stalled {stale:.0f}s "
            f"(attempt {item['attempts']})\n")
    with contextlib.suppress(OSError):
        with io.open(path, "a", encoding="utf-8") as fh:
            fh.write(line)


def _tick(slug, state):
    """ONE throughput evaluation. Returns (level, directive_lines)."""
    state["watchdog"]["ticks"] += 1
    state["watchdog"]["last_tick_ts"] = _now()
    if state["status"] == "complete":
        return 0, ["GOAL COMPLETE - every checklist item is done."]
    stale = _now() - (state["heartbeat"]["last_progress_ts"] or 0)
    item = _current_item(state)
    if item is None:
        return 0, ["GOAL COMPLETE - every checklist item is done."]
    if stale < stall_seconds():
        level = 0
        directive = [f"CONTINUE: throughput live ({stale:.0f}s since the "
                     f"last heartbeat); work item {item['id']}: "
                     f"{item['text']}"]
    else:
        prev = state["escalation"]["level"]
        level = min(prev + 1, max_escalation())
        name, action = ESCALATION_ACTIONS[level]
        state["escalation"]["level"] = level
        state["escalation"]["since"] = _now()
        item["attempts"] += 1
        item["escalation"] = level
        directive = [f"STALL: no heartbeat for {stale:.0f}s -> "
                     f"L{level} {name}"]
        directive.append(f"ITEM {item['id']}: {item['text']}")
        directive.append(f"ACTION {name}: {action}")
        state["escalation"]["history"].append(
            {"ts": round(_now(), 3), "level": level, "item": item["id"],
             "stale_s": round(stale, 1)})
        if level >= 3:
            _alert(slug, state, level, item, stale)
        _event(state, f"escalate-L{level}",
              f"item {item['id']} stale {stale:.0f}s")
    _save(slug, state)
    return level, directive


def cmd_tick(args):
    slug = args.slug or _active_slug()
    with _lock(slug):
        state = _load(slug)
        level, directive = _tick(slug, state)
    for line in directive:
        print(line)
    print(f"LEVEL L{level}")


def cmd_status(args):
    slug = args.slug or _active_slug()
    state = _load(slug)
    done = sum(1 for i in state["items"] if i["status"] == "done")
    print(json.dumps({
        "slug": slug, "title": state["title"], "status": state["status"],
        "items": f"{done}/{len(state['items'])}",
        "escalation": f"L{state['escalation']['level']}",
        "last_progress_ago_s": round(
            _now() - state["heartbeat"]["last_progress_ts"], 1),
        "ticks": state["watchdog"]["ticks"],
    }, indent=2))


def cmd_list(_args):
    try:
        names = sorted(os.listdir(GOALS_DIR))
    except OSError:
        names = []
    active = ""
    with contextlib.suppress(OSError):
        with io.open(ACTIVE_FILE, encoding="utf-8") as fh:
            active = fh.read().strip()
    for n in names:
        if not os.path.exists(_state_path(n)):
            continue
        state = _load(n)
        done = sum(1 for i in state["items"] if i["status"] == "done")
        mark = " <- ACTIVE" if n == active else ""
        print(f"{n}: {state['status']} ({done}/{len(state['items'])}){mark}")


def _watchdog_mutex(slug):
    """Single-instance survivor: the lock file is held for the loop's life."""
    import msvcrt
    path = os.path.join(_goal_dir(slug), "watchdog.lock")
    fh = io.open(path, "a+")
    try:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        return fh  # held: the caller keeps it open for the whole loop
    except OSError:
        fh.close()
        return None


def cmd_watchdog(args):
    """THE SURVIVOR LOOP: poll every GOAL_TICK_S, escalate on stalls, stop
    only when the goal is complete. Single-instance per goal (watchdog.lock)
    so the scheduled task can fire every minute without double loops."""
    slug = args.slug or _active_slug()
    lock_fh = _watchdog_mutex(slug)
    if lock_fh is None:
        print(f"watchdog already running for {slug}")
        return
    log_path = os.path.join(_goal_dir(slug), "watchdog.log")

    def wlog(msg):
        with contextlib.suppress(OSError):
            with io.open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")

    wlog(f"watchdog start (tick={tick_seconds()}s "
         f"stall={stall_seconds()}s)")
    try:
        while True:
            with _lock(slug):
                state = _load(slug)
                if state["status"] == "complete":
                    wlog("goal complete - watchdog exiting")
                    return
                level, directive = _tick(slug, state)
            wlog(" | ".join(directive) if level > 0 else "tick ok")
            time.sleep(tick_seconds())
    finally:
        with contextlib.suppress(Exception):
            import msvcrt
            lock_fh.seek(0)
            msvcrt.locking(lock_fh.fileno(), msvcrt.LK_UNLCK, 1)
        lock_fh.close()


def cmd_watchdog_auto(args):
    """Scheduled-task entry: start the survivor loop for the ACTIVE goal
    when it is not already running (the mutex makes this idempotent)."""
    try:
        slug = _active_slug()
    except SystemExit:
        return  # no active goal: nothing to keep alive
    state = _load(slug)
    if state["status"] == "complete":
        return
    cmd_watchdog(argparse.Namespace(slug=slug))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("--title", required=True)
    p.add_argument("--checklist")
    p.add_argument("--item", action="append")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("next")
    p.add_argument("--slug")
    p.set_defaults(fn=cmd_next)
    p = sub.add_parser("progress")
    p.add_argument("--slug")
    p.add_argument("--note", default="")
    p.set_defaults(fn=cmd_progress)
    p = sub.add_parser("done")
    p.add_argument("--slug")
    p.add_argument("item_id", type=int)
    p.set_defaults(fn=cmd_done)
    p = sub.add_parser("tick")
    p.add_argument("--slug")
    p.set_defaults(fn=cmd_tick)
    p = sub.add_parser("status")
    p.add_argument("--slug")
    p.set_defaults(fn=cmd_status)
    p = sub.add_parser("list")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("watchdog")
    p.add_argument("--slug")
    p.set_defaults(fn=cmd_watchdog)
    p = sub.add_parser("watchdog-auto")
    p.add_argument("--slug")
    p.set_defaults(fn=cmd_watchdog_auto)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
