"""GOAL ENGINE pins (/goal skill, operator directive 2026-10-23).

The undefeatable-checklist laws, each pinned:
  1. NO EXCEPTIONS: status is "complete" only when EVERY item is done.
  2. SURVIVES ANYTHING: the on-disk ledger resumes a "dead" process.
  3. THROUGHPUT: progress resets the ladder; no heartbeat = a stall.
  4. MULTI-LAYER ESCALATION: L1 NUDGE -> L2 REPLAN -> L3 SPAWN (ALERTS.md)
     -> L4 ALERT+CONTINUE, capped, never ending the goal.
Plus the survivor watchdog loop: single-instance, ticks, escalates, and
EXITS only when the goal completes.
"""
import argparse
import json
import os
import time

import pytest

import goal_engine as ge


@pytest.fixture()
def goals_dir(tmp_path, monkeypatch):
    d = tmp_path / "goals"
    d.mkdir()
    monkeypatch.setattr(ge, "GOALS_DIR", str(d))
    monkeypatch.setattr(ge, "ACTIVE_FILE", str(d / "ACTIVE"))
    monkeypatch.setenv("GOALS_DIR", str(d))
    return d


def _init(goals_dir, title="demo goal",
          items=("first item", "second item", "third item")):
    ge.cmd_init(argparse.Namespace(title=title, checklist=None,
                                   item=list(items)))


def _ns(**kw):
    return argparse.Namespace(**kw)


def _state(goals_dir, slug="demo-goal"):
    with open(os.path.join(str(goals_dir), slug, "state.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def _save(goals_dir, state, slug="demo-goal"):
    with open(os.path.join(str(goals_dir), slug, "state.json"), "w",
              encoding="utf-8") as fh:
        json.dump(state, fh)


# ---------------------------------------------------------------------------
# law 0: parsing
# ---------------------------------------------------------------------------

def test_checklist_parsing():
    items = ge.parse_checklist(
        "# plan\n"
        "- [ ] write the engine\n"
        "- [x] already done row\n"
        "1. numbered item\n"
        "2) paren item\n"
        "plain prose is ignored\n")
    assert [i["text"] for i in items] == [
        "write the engine", "already done row", "numbered item",
        "paren item"]
    assert items[1]["pre_done"] is True
    assert items[0]["pre_done"] is False


# ---------------------------------------------------------------------------
# law 1: NO EXCEPTIONS - complete only when EVERY item is done
# ---------------------------------------------------------------------------

def test_complete_only_when_every_item_is_done(goals_dir):
    _init(goals_dir, items=("a", "b", "c"))
    ge.cmd_done(_ns(slug=None, item_id=1))
    ge.cmd_done(_ns(slug=None, item_id=2))
    assert _state(goals_dir)["status"] == "running"   # item 3 still pending
    ge.cmd_done(_ns(slug=None, item_id=3))
    assert _state(goals_dir)["status"] == "complete"


# ---------------------------------------------------------------------------
# law 2: SURVIVES ANYTHING - the ledger is the resume path
# ---------------------------------------------------------------------------

def test_the_ledger_resumes_a_dead_process(goals_dir):
    _init(goals_dir)
    ge.cmd_done(_ns(slug=None, item_id=1))
    # "process death": a brand-new reader only sees the files on disk.
    slug = (goals_dir / "ACTIVE").read_text().strip()
    st = ge._load(slug)
    assert st["status"] == "running"
    item = ge._current_item(st)
    assert item["id"] == 2          # resumes at the FIRST not-done item


# ---------------------------------------------------------------------------
# law 3 + 4: throughput + the escalation ladder
# ---------------------------------------------------------------------------

def _backdate(goals_dir, seconds):
    st = _state(goals_dir)
    st["heartbeat"]["last_progress_ts"] = time.time() - seconds
    _save(goals_dir, st)


def test_tick_with_throughput_stays_l0(goals_dir):
    _init(goals_dir)
    level, directive = ge._tick("demo-goal", _state(goals_dir))
    assert level == 0
    assert "CONTINUE" in directive[0]


def test_escalation_ladder_climbs_and_caps(goals_dir, monkeypatch):
    monkeypatch.setenv("GOAL_STALE_S", "0.05")
    _init(goals_dir)
    _backdate(goals_dir, 60)
    seen = []
    for _ in range(6):
        level, directive = ge._tick("demo-goal", _state(goals_dir))
        seen.append((level, directive[0]))
    # L1 NUDGE -> L2 REPLAN -> L3 SPAWN -> L4 ALERT+CONTINUE -> cap L4
    assert [s[0] for s in seen] == [1, 2, 3, 4, 4, 4]
    assert "NUDGE" in seen[0][1]
    assert "REPLAN" in seen[1][1]
    assert "SPAWN" in seen[2][1]
    assert "ALERT+CONTINUE" in seen[3][1]
    # L3+ writes the operator alert
    alerts = goals_dir / "demo-goal" / "ALERTS.md"
    assert alerts.exists() and "SPAWN" in alerts.read_text(encoding="utf-8")


def test_progress_resets_the_ladder(goals_dir, monkeypatch):
    monkeypatch.setenv("GOAL_STALE_S", "0.05")
    _init(goals_dir)
    _backdate(goals_dir, 60)
    ge._tick("demo-goal", _state(goals_dir))          # L1
    ge._tick("demo-goal", _state(goals_dir))          # L2
    ge.cmd_progress(_ns(slug=None, note="edited the file"))
    st = _state(goals_dir)
    assert st["escalation"]["level"] == 0             # reset to L0
    assert st["heartbeat"]["last_event"] == "edited the file"
    level, _ = ge._tick("demo-goal", _state(goals_dir))
    assert level == 0                                  # throughput is live


# ---------------------------------------------------------------------------
# the survivor loop (subprocess: single-instance, escalates, exits complete)
# ---------------------------------------------------------------------------

def test_watchdog_survivor_loop(goals_dir):
    import subprocess
    import sys
    _init(goals_dir, items=("only item",))
    _backdate(goals_dir, 60)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    engine = os.path.join(root, "goal_engine.py")
    env = {**os.environ, "GOALS_DIR": str(goals_dir),
           "GOAL_TICK_S": "0.2", "GOAL_STALE_S": "0.2"}
    wd = subprocess.Popen([sys.executable, engine, "watchdog"],
                          env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True)
    try:
        # a second launch must no-op (single-instance survivor)
        second = subprocess.run([sys.executable, engine, "watchdog"],
                                env=env, capture_output=True, text=True,
                                timeout=30)
        assert "already running" in second.stdout
        # let it tick + escalate past L3 (ALERTS.md appears)
        deadline = time.time() + 15
        while time.time() < deadline:
            if (goals_dir / "demo-goal" / "ALERTS.md").exists():
                break
            time.sleep(0.2)
        assert (goals_dir / "demo-goal" / "ALERTS.md").exists()
        log = (goals_dir / "demo-goal" / "watchdog.log").read_text(
            encoding="utf-8")
        assert "watchdog start" in log and "STALL" in log
        # completing the goal makes the survivor EXIT on its next loop
        ge.cmd_done(_ns(slug=None, item_id=1))
        try:
            wd.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            wd.kill()
            wd.communicate()
            raise AssertionError("watchdog did not exit on completion")
    finally:
        if wd.poll() is None:
            wd.kill()

