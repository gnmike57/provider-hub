import json

d = json.load(open(r"handoff_matrix.json", encoding="utf-8"))
for e in d:
    runs = e.get("runs") or {}
    if not runs:
        print("=" * 20, e["primary"], "ERROR:", e.get("error"))
        continue
    for t in ("A", "B"):
        r = runs.get(t)
        if not r:
            continue
        print("=" * 24, e["primary"], t, r["reply_class"], f"{r['seconds']}s")
        print(r["reply"][:600].replace("\n", " / "))