#!/usr/bin/env python3
"""Brainspace state: the ledger, the two mailboxes and the stop gate.

All state is JSON lines under one directory. Mutations take a file lock and
replace files atomically, so the steward and the orchestrator can share one
brainspace from different processes.

  space.py --dir DIR init [GOAL]                                 # create, keep an existing GOAL.md
  space.py --dir DIR add "request in the user's words" [--owner A]
  space.py --dir DIR set L3 [--state delegated] [--owner B] [--evidence "pytest: 212 passed"]
  space.py --dir DIR list [--open]
  space.py --dir DIR send inbox|outbox KIND "text" [--item L3]
  space.py --dir DIR read inbox|outbox                           # print unread, does not consume
  space.py --dir DIR ack inbox|outbox ID [ID...]                 # consume after handling
  space.py --dir DIR agent B "brief text"                        # creates agents/B/ with BRIEF.md
  space.py --dir DIR session [SESSION_ID] [--agent A]            # store/print a subagent session id
  space.py --dir DIR gate                                        # 0 finished, 2 continue, 3 waiting on user
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows: no lock; use WSL when the steward and orchestrator share a brainspace.
    fcntl = None

STATES = ["open", "delegated", "done", "blocked-on-user", "cancelled"]
FINAL = {"done", "cancelled"}
MAY_END = FINAL | {"blocked-on-user"}
INBOX_KINDS = ["task", "steer", "cancel", "note"]
OUTBOX_KINDS = ["escalate", "milestone", "finished"]
LETTER = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def save(path: Path, rows: list[dict]) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with tmp.open("w") as fh:
        fh.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


@contextmanager
def locked(root: Path):
    """Serialize read-modify-write across the steward and orchestrator processes."""
    if fcntl is None:
        yield
        return
    with (root / ".lock").open("a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def next_id(rows: list[dict]) -> str:
    highest = 0
    for r in rows:
        if not r["id"].startswith("L"):
            continue
        rest = r["id"][1:]
        if rest.isdigit():
            highest = max(highest, int(rest))
    return f"L{highest + 1}"


def gate(root: Path) -> int:
    """0: finished. 2: work or unread directives remain. 3: waiting on the user."""
    rows = load(root / "LEDGER.jsonl")
    active = [r for r in rows if r["state"] not in MAY_END]
    waiting = [r for r in rows if r["state"] == "blocked-on-user"]
    unread = [m for m in load(root / "INBOX.jsonl") if not m.get("read")]
    unproven = [
        r for r in rows
        if r["state"] == "done" and not str(r.get("evidence") or "").strip()
    ]

    for r in active:
        print(f"NOT DONE {r['id']} [{r['state']}] owner={r['owner'] or '-'}: {r['request']}")
    for m in unread:
        print(f"UNREAD {m['id']} [{m.get('kind', '?')}]: {m['text']} (ack inbox {m['id']} after handling)")
    for r in unproven:
        print(f"NO EVIDENCE {r['id']}: marked done without a check you ran")

    if active or unread or unproven:
        print("Do not end the turn. Handle the lines above, then check the gate again.")
        return 2
    if waiting:
        for r in waiting:
            print(f"WAITING {r['id']} owner={r['owner'] or '-'}: {r['request']}")
        print("Waiting on a user decision. End the turn without `finished`; the steward will resume you.")
        return 3
    print("All items are done or cancelled. The turn may end.")
    return 0


def cmd_init(root: Path, goal: str | None) -> int:
    root.mkdir(parents=True, exist_ok=True)
    (root / "agents").mkdir(exist_ok=True)
    goal_path = root / "GOAL.md"
    if goal and (not goal_path.exists() or not goal_path.read_text().strip()):
        goal_path.write_text(goal.strip() + "\n")
    elif not goal_path.exists():
        goal_path.touch()
    for name in ("LEDGER.jsonl", "INBOX.jsonl", "OUTBOX.jsonl"):
        (root / name).touch()
    ignore = root / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n")
    print(root.resolve())
    return 0


def cmd_list(root: Path, open_only: bool) -> int:
    for r in load(root / "LEDGER.jsonl"):
        if not open_only or r["state"] not in FINAL:
            print(f"{r['id']} [{r['state']}] owner={r['owner'] or '-'}: {r['request']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dir", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").add_argument("goal", nargs="?", default=None)
    p = sub.add_parser("add")
    p.add_argument("request")
    p.add_argument("--owner", default="")
    p = sub.add_parser("set")
    p.add_argument("id")
    p.add_argument("--state", choices=STATES)
    p.add_argument("--owner")
    p.add_argument("--evidence")
    sub.add_parser("list").add_argument("--open", action="store_true")
    p = sub.add_parser("send")
    p.add_argument("box", choices=["inbox", "outbox"])
    p.add_argument("kind")
    p.add_argument("text")
    p.add_argument("--item", default="")
    p = sub.add_parser("read")
    p.add_argument("box", choices=["inbox", "outbox"])
    p = sub.add_parser("ack")
    p.add_argument("box", choices=["inbox", "outbox"])
    p.add_argument("ids", nargs="+")
    p = sub.add_parser("agent")
    p.add_argument("letter")
    p.add_argument("brief")
    p = sub.add_parser("session")
    p.add_argument("id", nargs="?", default=None)
    p.add_argument("--agent", default=None)
    sub.add_parser("gate")
    args = ap.parse_args()

    root = Path(args.dir)
    if args.cmd == "init":
        return cmd_init(root, args.goal)
    if not root.is_dir() or not (root / "LEDGER.jsonl").exists():
        print(f"no brainspace at {root}; run init first", file=sys.stderr)
        return 1
    if args.cmd == "gate":
        return gate(root)
    if args.cmd == "list":
        return cmd_list(root, args.open)

    with locked(root):
        ledger = root / "LEDGER.jsonl"
        if args.cmd == "add":
            if not args.request.strip():
                print("add needs a request", file=sys.stderr)
                return 1
            rows = load(ledger)
            row = {"id": next_id(rows), "request": args.request, "owner": args.owner,
                   "state": "open", "evidence": "", "updated": now()}  # fmt: skip
            save(ledger, [*rows, row])
            print(row["id"])
        elif args.cmd == "set":
            rows = load(ledger)
            hit = [r for r in rows if r["id"] == args.id]
            if not hit:
                print(f"no ledger item {args.id}", file=sys.stderr)
                return 1
            state = args.state if args.state is not None else hit[0]["state"]
            owner = args.owner if args.owner is not None else hit[0]["owner"]
            if state == "delegated" and not owner:
                print("delegated needs an owner", file=sys.stderr)
                return 1
            for key, val in (("state", args.state), ("owner", args.owner),
                             ("evidence", args.evidence)):  # fmt: skip
                if val is not None:
                    hit[0][key] = val
            hit[0]["updated"] = now()
            save(ledger, rows)
        elif args.cmd == "send":
            kinds = INBOX_KINDS if args.box == "inbox" else OUTBOX_KINDS
            if args.kind not in kinds:
                print(f"{args.box} kinds: {kinds}", file=sys.stderr)
                return 1
            if not args.text.strip():
                print("send needs text", file=sys.stderr)
                return 1
            if args.item and args.item not in {r["id"] for r in load(ledger)}:
                print(f"no ledger item {args.item}", file=sys.stderr)
                return 1
            path = root / f"{args.box.upper()}.jsonl"
            rows = load(path)
            row = {"id": f"{args.box[0].upper()}{len(rows) + 1}", "kind": args.kind,
                   "text": args.text, "item": args.item, "read": False, "at": now()}  # fmt: skip
            rows.append(row)
            save(path, rows)
            print(row["id"])
        elif args.cmd == "read":
            path = root / f"{args.box.upper()}.jsonl"
            for m in load(path):
                if not m.get("read"):
                    print(f"{m['id']} [{m.get('kind', '?')}] item={m.get('item') or '-'}: {m['text']}")
        elif args.cmd == "ack":
            path = root / f"{args.box.upper()}.jsonl"
            rows = load(path)
            wanted = set(args.ids)
            missing = wanted - {m["id"] for m in rows}
            if missing:
                print(f"no message {', '.join(sorted(missing))} in {args.box}", file=sys.stderr)
                return 1
            acked = 0
            for m in rows:
                if m["id"] in wanted and not m.get("read"):
                    m["read"] = True
                    acked += 1
            save(path, rows)
            print(f"acked {acked}")
        elif args.cmd == "agent":
            if not LETTER.fullmatch(args.letter):
                print("agent letter must be a single word, e.g. A", file=sys.stderr)
                return 1
            if not args.brief.strip():
                print("agent needs a brief", file=sys.stderr)
                return 1
            home = root / "agents" / args.letter
            (home / "notes").mkdir(parents=True, exist_ok=True)
            (home / "out").mkdir(exist_ok=True)
            (home / "BRIEF.md").write_text(args.brief.strip() + "\n")
            (home / "STATUS.md").touch()
            print(home)
        elif args.cmd == "session":
            if args.agent is not None and not LETTER.fullmatch(args.agent):
                print("agent letter must be a single word, e.g. A", file=sys.stderr)
                return 1
            home = root if not args.agent else root / "agents" / args.agent
            if not home.is_dir():
                print(f"no worker directory {home}", file=sys.stderr)
                return 1
            path = home / "SESSION"
            if args.id:
                path.write_text(args.id.strip() + "\n")
                print(args.id.strip())
            elif path.exists() and path.read_text().strip():
                print(path.read_text().strip())
            else:
                print("no session recorded", file=sys.stderr)
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
