import json, pathlib
pdir = next(pathlib.Path("runs/published/travel-gpt-4o-mini/D_asr_system_targeted/repeat_0").glob("gpt-4o-mini-*"))
for p in sorted(pdir.rglob("important_instructions/injection_task_6.json")):
    r = json.loads(p.read_text())
    if not r["security"]:
        continue
    texts = [c["content"] for m in r["messages"] if m["role"] == "assistant"
             and m.get("content") for c in m["content"] if c.get("type") == "text"]
    print("=" * 60)
    print(r["user_task_id"])
    print(texts[-1][:600] if texts else "(no text)")