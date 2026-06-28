#!/usr/bin/env python3
"""
nova_proof_of_hours.py — Proof of Work from Claude Code JSONL sessions
Gap-based sessionization · Content-free · Path-free · Discord-aware
Fleet standard: gap>30min = new session, dedup cross-project, safe to publish
"""
import os, sys, json, glob, argparse
from datetime import datetime, timezone, timedelta
from collections import defaultdict

TZ7 = timezone(timedelta(hours=7))
PROJECTS_DIR = os.path.expanduser("~/.claude/projects")

REAL_TYPES = {"human", "assistant"}

# Patterns that signal automation, not human input
AUTO_PREFIXES = (
    "<channel source=", "<task-notification>", "<local-command",
    "tool_result", "This session is being continued",
    "[Request interrupted", "API Error",
)

def norm_ts(ts):
    if not ts: return None
    if isinstance(ts, (int, float)):
        return float(ts) / 1000.0 if ts > 1e12 else float(ts)
    if isinstance(ts, str):
        if ts.isdigit():
            v = int(ts)
            return float(v) / 1000.0 if v > 1e12 else float(v)
        try: return datetime.fromisoformat(ts.replace("Z","+00:00")).timestamp()
        except: return None
    return None

def is_tool_result(obj):
    content = obj.get("message",{}).get("content", obj.get("content",""))
    if isinstance(content, list):
        return any(isinstance(c,dict) and c.get("type")=="tool_result" for c in content)
    return False

def is_automation(text):
    if not text: return True
    low = text[:150].lower()
    return any(m.lower() in low for m in AUTO_PREFIXES)

def proc_file(fpath):
    """Yield (epoch, role) tuples from a JSONL file."""
    results = []
    try:
        with open(fpath, "r", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line: continue
                try: obj = json.loads(line)
                except: continue
                mtype = obj.get("type","")
                who = None
                if mtype == "human": who = "human"
                elif mtype == "assistant": who = "ai"
                else:
                    role = obj.get("message",{}).get("role","")
                    if role == "user": who = "human"
                    elif role == "assistant": who = "ai"
                if not who: continue
                if who == "human" and is_tool_result(obj): continue
                epoch = norm_ts(obj.get("timestamp"))
                if epoch is None: continue
                if who == "human":
                    text = ""
                    content = obj.get("message",{}).get("content", obj.get("content",""))
                    if isinstance(content, list):
                        text = " ".join(c.get("text","") for c in content if isinstance(c,dict))
                    elif isinstance(content, str): text = content
                    if is_automation(text): continue
                results.append((epoch, who))
    except OSError: pass
    return results

def sessionize(events, gap_min=30):
    """Group events into sessions. gap>gap_min = new session."""
    if not events: return []
    events.sort()
    sessions = []
    cur = [events[0]]
    for e in events[1:]:
        if (e[0] - cur[-1][0]) > gap_min * 60:
            sessions.append(cur)
            cur = [e]
        else:
            cur.append(e)
    if cur: sessions.append(cur)
    return sessions

def main():
    ap = argparse.ArgumentParser(description="Nova Proof of Hours")
    ap.add_argument("--date", help="Target date YYYY-MM-DD GMT+7 (default: today)")
    ap.add_argument("--days", type=int, default=1, help="Last N days (default: 1)")
    ap.add_argument("--gap", type=int, default=30, help="Session gap in minutes (default: 30)")
    ap.add_argument("--json", action="store_true", help="Machine-readable output")
    args = ap.parse_args()

    if args.date:
        target_dates = [args.date]
    else:
        target_dates = [(datetime.now(TZ7) - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(args.days)]

    jsonl_files = glob.glob(os.path.join(PROJECTS_DIR, "**", "*.jsonl"), recursive=True)
    
    # Collect all events
    date_events = defaultdict(list)
    for f in jsonl_files:
        for epoch, who in proc_file(f):
            dt = datetime.fromtimestamp(epoch, tz=TZ7)
            dstr = dt.strftime("%Y-%m-%d")
            if dstr in target_dates:
                date_events[dstr].append((epoch, who))

    if args.json:
        out = []
        for d in sorted(target_dates):
            events = date_events.get(d, [])
            sessions = sessionize(events, args.gap)
            active_min = sum((s[-1][0] - s[0][0]) / 60 for s in sessions)
            human_count = sum(1 for _, w in events if w == "human")
            ai_count = sum(1 for _, w in events if w == "ai")
            out.append({"date": d, "active_hours": round(active_min/60, 2),
                         "sessions": len(sessions), "human": human_count, "ai": ai_count,
                         "total": human_count + ai_count, "gap_min": args.gap})
        print(json.dumps(out if args.days > 1 else out[0]))
    else:
        total_h = 0
        total_s = 0
        total_t = 0
        for d in sorted(target_dates):
            events = date_events.get(d, [])
            sessions = sessionize(events, args.gap)
            active_min = sum((s[-1][0] - s[0][0]) / 60 for s in sessions)
            human_count = sum(1 for _, w in events if w == "human")
            ai_count = sum(1 for _, w in events if w == "ai")
            total_h += active_min / 60
            total_s += len(sessions)
            total_t += human_count + ai_count
            print(f"{d}: {active_min/60:.2f}h active ({len(sessions)} sessions, {human_count+ai_count} turns) [gap>{args.gap}m]")
        
        if args.days > 1:
            print(f"\nTOTAL ({args.days}d): {total_h:.2f}h active, {total_s} sessions, {total_t} turns")

if __name__ == "__main__":
    main()
