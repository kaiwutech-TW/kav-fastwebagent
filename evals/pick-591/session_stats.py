"""Per-turn wall time, tool calls, tokens and final text of a Claude Code session transcript.
usage: session_stats.py <marker-text-in-first-prompt>   (picks the newest transcript containing it, never this session's)"""
import glob, json, os, sys
from datetime import datetime

marker = sys.argv[1]
mine = "375bb7d5"
files = sorted(glob.glob(os.path.expanduser("~/.claude/projects/-Users-kaiwu-orca-projects-Kav-test/*.jsonl")), key=os.path.getmtime)
path = next(f for f in reversed(files) if mine not in f and marker in open(f).read())
print("jsonl:", os.path.basename(path))
fmt = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
turns = []
for line in open(path):
    try:
        d = json.loads(line)
    except ValueError:
        continue
    ts, m, t = d.get("timestamp"), d.get("message") or {}, d.get("type")
    if not ts or t not in ("user", "assistant"):
        continue
    content = m.get("content")
    if t == "user" and isinstance(content, str) and not d.get("isMeta"):
        turns.append({"prompt": content[:60], "start": ts, "end": ts, "calls": 0, "usage": {}, "tools": [], "text": []})
        continue
    if t == "user" and isinstance(content, list) and all(isinstance(c, dict) and c.get("type") == "text" for c in content) and not d.get("isMeta"):
        turns.append({"prompt": content[0]["text"][:60], "start": ts, "end": ts, "calls": 0, "usage": {}, "tools": [], "text": []})
        continue
    if not turns:
        continue
    cur = turns[-1]
    cur["end"] = ts
    if t == "assistant":
        for k, v in (m.get("usage") or {}).items():
            if isinstance(v, (int, float)):
                cur["usage"][k] = cur["usage"].get(k, 0) + v
        for c in content or []:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                cur["calls"] += 1
                cur["tools"].append(c.get("name", "")[:40])
            if isinstance(c, dict) and c.get("type") == "text":
                cur["text"].append(c["text"])
for i, tr in enumerate(turns, 1):
    u = tr["usage"]
    inp = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
    print(f"\n== turn {i}: {tr['prompt']!r}")
    print(f"wall {round((fmt(tr['end']) - fmt(tr['start'])).total_seconds(), 1)} s | tool calls {tr['calls']} | input(all) {inp} | output {u.get('output_tokens', 0)}")
    print("tools:", tr["tools"][:40])
    print("final:", ("\n".join(tr["text"]))[-700:])
