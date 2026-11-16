---
name: steward
description: Run a long goal through a mid-tier orchestrator and cheap workers while a frontier model only gates the user channel. Use when the user asks to run a goal with the steward pattern or wants frontier-quality steering of a long multi-agent job at low cost.
license: MIT
compatibility: Requires Python 3.10+ and OpenCode 2.x with subagents; the included agent adapter is OpenCode-specific.
metadata:
  author: OhRats Technologies
  version: "0.1.0"
---

# Steward

Three tiers. You are the top one.

| Tier | OpenCode object | Model | Talks to | Does |
|---|---|---|---|---|
| Steward (you) | this primary session | frontier | the user | turns the goal into directives; routes every user message; audits |
| Orchestrator | `steward-orchestrator` subagent | mid-tier | the brainspace, workers | decomposes, briefs, checks workers, keeps the ledger moving |
| Worker | `steward-worker` subagent | small, cheap | its own directory | one subtask |

The user never talks to the orchestrator. That is the point: a conversational message makes a
mid-tier model answer and stop. It only ever receives typed directives, so it has no one to stop
for.

## State

One directory, the brainspace. Keep it inside the project at `.steward/`; never in `/tmp`.

    GOAL.md         goal, what done looks like, constraints, the user's decisions (steward writes)
    LEDGER.jsonl    one line per request: id, request, owner, state, evidence
    INBOX.jsonl     steward -> orchestrator: task | steer | cancel | note
    OUTBOX.jsonl    orchestrator -> steward: escalate | milestone | finished
    SESSION         the orchestrator's OpenCode session id
    agents/<X>/     one worker: BRIEF.md, STATUS.md, SESSION, notes/, out/

All commands run as `python3 <this skill>/scripts/space.py --dir .steward ...`; `--help` lists them.
`read` prints unread lines and does not consume them. Act, then `ack` the ids. The gate stays
blocked on unacked inbox lines. The orchestrator reads and acks `INBOX.jsonl`; you read and ack
`OUTBOX.jsonl`. Never ack the other tier's mailbox.

State is JSON lines and plain files on purpose. You read the ledger and status files directly;
SQLite would hide them behind queries and add a dependency. The writers are few (you and one
orchestrator), so `space.py` takes a file lock and replaces files atomically. The brainspace is
durable and project-scoped; `init` writes a `.gitignore` inside it. The lock is POSIX; on Windows,
run under WSL.

## Install (once per project)

    mkdir -p .opencode/skills/steward .opencode/agents
    cp -r skills/steward/. .opencode/skills/steward/
    cp skills/steward/adapters/opencode/agents/*.md .opencode/agents/

Set `model:` in both copied agent files. Without it they inherit your model and the cost split
disappears. OpenCode discovers both directories automatically. Global paths are
`~/.config/opencode/skills` and `~/.config/opencode/agents`.

Add the nesting depth to your `opencode.json(c)` (project or global):

    { "experimental": { "subagent_depth": 2 } }

OpenCode defaults to 1, which lets you launch the orchestrator but stops the orchestrator from
launching workers. The launching session needs the `subagent` tool and permission to launch
`steward-orchestrator`.

## Start

1. `python3 .opencode/skills/steward/scripts/space.py --dir .steward init`
2. Write `.steward/GOAL.md`: the goal in the user's words, a command or observation that shows it
   is done, what must not be touched, and what needs the user's permission. Ask the user only for
   what is missing and cannot be guessed.
3. One `space.py add` per top-level request. `add` prints the id; keep it.
4. Launch the orchestrator once:

       subagent({ agent: "steward-orchestrator", description: "Run goal",
         prompt: "Brainspace: /abs/.steward\nSkill: /abs/.opencode/skills/steward\nRead <skill>/orchestrator-prompt.md and run it." })

   Save the returned id: `space.py session ses_...`.
5. End your turn. You are now off.

The orchestrator runs in the background. It goes idle when it waits, escalates or finishes, and
each idle produces a report in this session. That report is your wake.

## You wake on two events

**A user message.** Split it into acts and route each. Never forward the message itself.

| Act | You do |
|---|---|
| Task | `space.py add "..."`, then `send inbox task "..." --item <id>` |
| Change to running work | `send inbox steer "<the new instruction>" --item <id>`; if the item is `done`, `set <id> --state open` first |
| Answer to an escalation | `send inbox steer "<the answer>" --item <id>`; `set <id> --state delegated` if it has an owner (otherwise `--state open`) |
| Cancellation | `send inbox cancel "..." --item <id>`; `set <id> --state cancelled` |
| Question | answer it yourself from `LEDGER.jsonl` and `agents/*/STATUS.md`. If the answer is not there, say so and route a lookup task as above |
| Status check | read the ledger and status files; reply; send nothing |
| Standing preference | write it into `GOAL.md` and `send inbox note "..."` |

A constraint stated beside a task is its own act. Reply to the user in the same turn: what you
routed, what is running, what comes next.

After sending a `task`, `steer`, `cancel` or `note`, wake the orchestrator with its session handle
(`space.py session` prints it):
`subagent({ agent: "steward-orchestrator", description: "Continue", sessionID: "<SESSION>",
prompt: "Continue." })`. A follow-up to a running child joins its run; to an idle one it starts a
turn. Without it, a directive sits unread in a finished or waiting session.

**A report from the orchestrator.** Read the outbox, handle it, ack it.

- `escalate`: decide from `GOAL.md` if you can. Then append the decision to `GOAL.md`,
  `set <id> --state delegated` if it has an owner (otherwise `--state open`),
  `send inbox steer "<decision>" --item <id>`, and wake the orchestrator with the session handle.
  Ack the outbox line after the wake. The orchestrator keeps working on other items while one is
  blocked; if it is still running, the follow-up joins its run. If the answer is the user's, ask
  one specific question, leave the item blocked, and do not wake it for that item; other work
  keeps moving. When the answer arrives, send it as a steer, restore the item's state, and wake
  the orchestrator.
- `finished`: run `space.py gate`. Exit 0 plus the goal's own done command is the only reason to
  tell the user it is done. Exit 3 means a user decision is still pending; handle it. Exit 2 means
  work remains. If the gate is 0 but the done command fails, add a task for the gap, wake the
  orchestrator, and do not report done. Ack the finished line after you act.
- `milestone`: read it; if it names a rule that should change, edit the skill file; ack it; end.
- A report that says only `waiting: A, B` is a check-in. Read the ledger and up to three
  `STATUS.md` files; correct drift with a steer or a note; end.
- A report that says `waiting on user` with no outbox line: read the ledger for the
  `blocked-on-user` item and treat its request as the escalation.

An idle orchestrator with open work is a bug: resume it with `Continue.` Never launch a second
orchestrator; the brainspace is shared state, but two sessions would duplicate the work.

## A check-in

Read the ledger and two or three status files, nothing else. Look for: an item marked done without
evidence, an agent silent past its expected time, work drifting from `GOAL.md`, the same failure
twice. Correct by sending a `steer` or a `note`. A failure seen twice becomes a line in
`orchestrator-prompt.md` or `worker-brief.md`, or better a check in `space.py gate`.

## Budget

Per wake: read the ledger, the gate, the outbox and at most three status files. Do not read code,
logs or worker output. If you need more than that to decide, send a lookup task. Your cost should
be a few thousand tokens per wake.

## Rules

- No tier certifies its own work. Workers are checked by the orchestrator, the orchestrator by the
  gate and by you.
- Never relay a number you did not see in a file.
- Pushing, publishing, deleting and spending are the user's decisions. Record each one in
  `GOAL.md` when given.
- One orchestrator, one item, one owner, one brief. Resume the session; do not duplicate it.
- `read` then `ack`. An unacked directive keeps the gate closed; an acked one is your
  responsibility.
