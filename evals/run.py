#!/usr/bin/env python3
"""Executable eval: can a small model drive the brainspace correctly from the skill text alone?

Each scenario builds a brainspace, shows the model its state and one event (a user message for the
steward, a report or an inbox line for the orchestrator), runs the `space.py` commands the model
replies with, and checks the resulting files by rule. No model grades anything.

Conditions are whole skill versions: the prompt text and the script the commands run against.
  v01  the first release: prose protocol, permissive script (evals/v01/)
  v02  the current skill: verbs and an enforced lifecycle (skills/steward/)

  python3 evals/run.py --selfcheck                      # scenarios are solvable and non-trivial
  python3 evals/run.py --model claude-haiku-5-5 --repeats 3

Model calls go through `claude -p` with no tools and no settings.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import shlex
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUNDS = 3  # the model sees its commands' output and may continue
SKILL = HERE.parent / "skills" / "steward"
VERSIONS = {
    "v01": {"script": HERE / "v01" / "space.py", "steward": HERE / "v01" / "SKILL.md",
            "orchestrator": HERE / "v01" / "orchestrator-prompt.md"},
    "v02": {"script": SKILL / "scripts" / "space.py", "steward": SKILL / "SKILL.md",
            "orchestrator": SKILL / "orchestrator-prompt.md"},
}  # fmt: skip
INTERFACE = """

---
You are being run in a harness. You cannot launch subagents or run a shell here. Reply with the
`space.py` commands you would run now for the event below, one per line, inside one ```sh block,
written as `space.py <command> ...` (the harness adds `--dir`). They are executed in order and
nothing else you write is executed. `$ID` in a command is replaced by the id printed by your most
recent `add` or `task`. You will then see each command's output and may reply with more commands.
When nothing more is needed, reply with an empty block.
"""


def space(script: Path, root: Path, argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(script), "--dir", str(root), *argv],
                          capture_output=True, text=True, cwd=cwd, timeout=60)  # fmt: skip


def rows(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def commands(reply: str) -> list[list[str]]:
    """`space.py ...` lines from the reply's fenced blocks (or the whole reply if none)."""
    blocks = re.findall(r"```[a-z]*\n(.*?)```", reply, flags=re.S)
    out = []
    for line in "\n".join(blocks or [reply]).splitlines():
        if "space.py" not in line or line.lstrip().startswith("#"):
            continue
        try:
            argv = shlex.split(line.split("space.py", 1)[1], comments=True)
        except ValueError:
            continue
        if argv[:1] == ["--dir"]:
            argv = argv[2:]
        if argv and argv[0] != "init":
            out.append(argv)
    return out


def execute(script: Path, root: Path, cmds: list[list[str]], last: str = "") -> list[dict]:
    log = []
    for argv in cmds:
        argv = [a.replace("$ID", last) for a in argv]
        proc = space(script, root, argv, root.parent)
        if argv[0] in {"add", "task"} and proc.returncode == 0:
            last = proc.stdout.strip()
        log.append({"argv": argv, "code": proc.returncode, "out": proc.stdout.strip()[:600],
                    "err": proc.stderr.strip()[:300], "last": last})  # fmt: skip
    return log


def check(root: Path, before: dict, expect: dict) -> list[str]:
    """Every unmet expectation, as text. Empty means the scenario passed."""
    miss = []
    ledger = {r["id"]: r for r in rows(root / "LEDGER.jsonl")}
    for item, want in expect.get("items", {}).items():
        got = ledger.get(item)
        if got is None:
            miss.append(f"{item} missing")
            continue
        states = want.get("state")
        if states and got["state"] not in ([states] if isinstance(states, str) else states):
            miss.append(f"{item} state {got['state']} not {states}")
        if "owner" in want and got.get("owner", "") != want["owner"]:
            miss.append(f"{item} owner {got.get('owner')!r} not {want['owner']!r}")
        if "evidence" in want and bool(str(got.get("evidence") or "").strip()) != want["evidence"]:
            miss.append(f"{item} evidence present={not want['evidence']}")
    if "item_count" in expect and len(ledger) != expect["item_count"]:
        miss.append(f"{len(ledger)} items, not {expect['item_count']}")
    for box in ("inbox", "outbox"):
        msgs = rows(root / f"{box.upper()}.jsonl")
        new = msgs[before[box] :]
        if f"{box}_new" in expect and len(new) != expect[f"{box}_new"]:
            miss.append(f"{len(new)} new {box} lines, not {expect[f'{box}_new']}")
        pool = list(new)
        for want in expect.get(box, []):
            hit = next((m for m in pool if m.get("kind") == want["kind"]
                        and ("item" not in want or m.get("item", "") == want["item"])), None)  # fmt: skip
            if hit is None:
                miss.append(f"no new {box} {want}")
            else:
                pool.remove(hit)
        state = {m["id"]: bool(m.get("read")) for m in msgs}
        for mid in expect.get("acked", []):
            if mid[0].lower() == box[0] and not state.get(mid):
                miss.append(f"{mid} not acked")
        for mid in expect.get("unacked", []):
            if mid[0].lower() == box[0] and state.get(mid):
                miss.append(f"{mid} acked")
    if "gate" in expect:
        code = space(VERSIONS["v02"]["script"], root, ["gate"], root.parent).returncode
        if code != expect["gate"]:
            miss.append(f"gate {code}, not {expect['gate']}")
    return miss


def build(scn: dict, tmp: Path) -> tuple[Path, dict, str]:
    """Create the scenario's brainspace with the current script; return it, counts and a state dump."""
    root = tmp / ".steward"
    new = VERSIONS["v02"]["script"]
    space(new, root, ["init", scn.get("goal", "Ship the project.")], tmp)
    for line in scn.get("setup", []):
        proc = space(new, root, shlex.split(line), tmp)
        if proc.returncode not in (0, 2, 3):
            raise RuntimeError(f"{scn['id']} setup failed: {line}: {proc.stderr}")
    for rel, text in scn.get("files", {}).items():
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    before = {b: len(rows(root / f"{b.upper()}.jsonl")) for b in ("inbox", "outbox")}
    dump = f"$ cat GOAL.md\n{(root / 'GOAL.md').read_text().strip()}\n" + "\n".join(
        f"$ space.py {' '.join(a)}\n{space(new, root, a, tmp).stdout.strip() or '(nothing)'}"
        for a in (["list"], ["read", "inbox"], ["read", "outbox"])
    )
    return root, before, dump


def call(model: str, system: str, user: str) -> tuple[str, float]:
    cmd = ["claude", "-p", "--model", model, "--system-prompt", system, "--tools", "",
           "--setting-sources", "", "--strict-mcp-config", "--output-format", "json"]  # fmt: skip
    with tempfile.TemporaryDirectory() as cwd:
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True, cwd=cwd, timeout=300)
    out = json.loads(proc.stdout)
    return out.get("result", ""), out.get("total_cost_usd", 0.0)


def trial(scn: dict, version: str, model: str) -> dict:
    v = VERSIONS[version]
    with tempfile.TemporaryDirectory() as tmp:
        root, before, dump = build(scn, Path(tmp))
        system = v[scn["role"]].read_text() + INTERFACE
        user = f"Brainspace state:\n{dump}\n\nEvent ({scn['role']}):\n{scn['event']}"
        log, replies, cost, last = [], [], 0.0, ""
        for _ in range(ROUNDS):
            try:
                reply, spent = call(model, system, user)
            except Exception as err:  # noqa: BLE001 - a failed call is a failed trial, not a crash
                return {"id": scn["id"], "version": version, "role": scn["role"], "pass": False,
                        "miss": [f"call: {err}"], "cost": cost}  # fmt: skip
            replies.append(reply)
            cost += spent
            step = execute(v["script"], root, commands(reply), last)
            if not step:
                break
            log += step
            last = step[-1]["last"]
            shown = "\n".join(f"$ space.py {shlex.join(c['argv'])}\n{c['out'] or c['err'] or '(nothing)'}\n(exit {c['code']})"
                              for c in step)  # fmt: skip
            user += f"\n\nYou ran:\n{shown}\n\nMore commands, or an empty block if you are finished."
        reply = "\n---\n".join(replies)
        miss = check(root, before, scn["expect"])
    return {"id": scn["id"], "version": version, "role": scn["role"], "pass": not miss, "miss": miss,
            "refused": sum(1 for c in log if c["code"] == 1), "log": log, "reply": reply, "cost": cost}  # fmt: skip


def selfcheck(scenarios: list[dict]) -> int:
    bad = 0
    for scn in scenarios:
        for version, key in (("v02", "solution"), ("v01", "solution_v01"), (None, None)):
            with tempfile.TemporaryDirectory() as tmp:
                root, before, _ = build(scn, Path(tmp))
                if version:
                    execute(VERSIONS[version]["script"], root, [shlex.split(c) for c in scn[key]])
                miss = check(root, before, scn["expect"])
            if version and miss:
                bad += 1
                print(f"{scn['id']}: {key} does not pass: {miss}")
            if not version and not miss:
                bad += 1
                print(f"{scn['id']}: passes with no commands; it tests nothing")
    print(f"{len(scenarios)} scenarios, {bad} problems")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scenarios", default=str(HERE / "scenarios.jsonl"))
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--model", default="claude-haiku-5-5")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--versions", nargs="+", default=["v01", "v02"], choices=list(VERSIONS))
    ap.add_argument("--out", default=str(HERE / "results"))
    args = ap.parse_args()
    scenarios = rows(Path(args.scenarios))
    if args.selfcheck:
        return selfcheck(scenarios)

    jobs = [(s, v) for s in scenarios for v in args.versions for _ in range(args.repeats)]
    with cf.ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda j: trial(j[0], j[1], args.model), jobs))
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    (out / f"{args.model}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in results))

    tally: dict = defaultdict(lambda: [0, 0])
    for r in results:
        for key in ((r["version"], "all"), (r["version"], r.get("role", "?")), (r["version"], r["id"])):
            tally[key][0] += r["pass"]
            tally[key][1] += 1
    for v in args.versions:
        parts = ", ".join(f"{k} {tally[v, k][0]}/{tally[v, k][1]}" for k in ("all", "steward", "orchestrator"))
        print(f"{v}: {parts}")
    for s in scenarios:
        print(f"  {s['id']:<28}" + "  ".join(f"{v} {tally[v, s['id']][0]}/{tally[v, s['id']][1]}" for v in args.versions))
    print(f"cost ${sum(r['cost'] for r in results):.2f} for {len(results)} calls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
