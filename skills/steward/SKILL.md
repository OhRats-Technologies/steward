---
name: steward
description: Run a long goal through a mid-tier orchestrator and cheap workers while a frontier model only gates the user channel. Use when the user asks to run a goal with the steward pattern or wants frontier-quality steering of a long multi-agent job at low cost.
license: MIT
compatibility: Requires Python 3.10+ and OpenCode 2.x with subagents; the included agent adapter is OpenCode-specific.
metadata:
  author: OhRats Technologies
  version: "0.2.0"
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
The script is the state machine. It refuses an illegal step and says what to do instead, so read
its error and follow it; do not edit the JSON files by hand.

    open -> delegated -> done            done needs evidence, or the item's own check passing;
                                         only `assign` delegates, and only open work
    open | delegated -> blocked-on-user  (escalate)  -> back to work on your steer
    open | delegated | blocked -> cancelled
    done -> open | delegated             (a steer reopens it and clears the old evidence)

`read` prints unacked lines and does not consume them. Act, then `ack <id>` (`ack O1`). The gate stays
closed on unacked inbox lines. The orchestrator acks `INBOX.jsonl`; you ack `OUTBOX.jsonl`. Never
ack the other tier's mailbox.

State is JSON lines and plain files on purpose: you can read them, they survive a reboot, and the
two writers are serialized by a file lock (POSIX; on Windows, run under WSL). `init` writes a
`.gitignore` inside the brainspace.

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
3. One `space.py task "<request>" --check "<command>"` per top-level request. The check is a shell
   command, run from the project root, that exits 0 only when the request is met. With a check,
   nobody can mark the item done by saying so. Leave `--check` out only when no command can tell.
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
| Task | `task "<request>" [--check "<command>"]` |
| Change to running or finished work | `steer <id> "<the new instruction>"` |
| Answer to an escalation | `steer <id> "<the answer>"` |
| Cancellation | `cancel <id> "<why>"` |
| Standing preference | `note "<the rule>"` (it lands in `GOAL.md` and in every later brief). Only for a rule that binds all work; an instruction or answer about one item is a `steer`, never also a `note` |
| Question or status check | `status`, then answer from what it prints. Send nothing. If the answer is not there, say so and route a lookup `task` |

Each verb changes the ledger and writes the directive in one step. `steer` puts a blocked or
finished item back to work by itself; you never set states by hand.

A constraint stated beside a task is its own act. Reply to the user in the same turn: what you
routed, what is running, what comes next.

After a `task`, `steer`, `cancel` or `note`, wake the orchestrator with its session handle
(`space.py session` prints it):
`subagent({ agent: "steward-orchestrator", description: "Continue", sessionID: "<SESSION>",
prompt: "Continue." })`. A follow-up to a running child joins its run; to an idle one it starts a
turn. Without it, a directive sits unread in a finished or waiting session.

**A report from the orchestrator.** Read the outbox, handle it, ack it.

- `escalate`: if `GOAL.md` already answers the question, do not ask the user: `steer <id>
  "<decision>"` (it records the decision in `GOAL.md`), wake the orchestrator, `ack O<n>`. If the answer is the
  user's, ask one specific question, leave the item blocked, and do not wake the orchestrator for
  that item; other work keeps moving. When the answer arrives, `steer` and wake.
- `finished`: run `space.py gate`. Exit 0 plus the goal's own done command is the only reason to
  tell the user it is done. Exit 3 means a user decision is still pending; handle it. Exit 2 means
  work remains. If the gate is 0 but the done command fails, add a task for the gap, wake the
  orchestrator, and do not report done. Ack the finished line after you act.
- `milestone`: read it; if it names a rule that should change, edit the skill file; ack it; end.
- A report that says only `waiting: A, B` is a check-in (below).
- A report that says `waiting on user` with no outbox line: `status` shows the `blocked-on-user`
  item; treat its request as the escalation.

An idle orchestrator with open work is a bug: resume it with `Continue.` Never launch a second
orchestrator: `session` refuses to record one while another is on file. Pass `--replace` only
when the old session is gone.

## A check-in

Run `status`. It prints the phase, every item with its evidence, each worker's last status line,
and `STALE` beside a worker that has been silent too long. Look for: evidence that does not show a
command and its output, a stale worker, work drifting from `GOAL.md`, the same failure twice.
Correct with a `steer` or a `note`.

A failure seen twice is an implicit state machine: some sequence the prompts describe but nothing
enforces. Name its states, then make the bad step impossible in `space.py` (a refused transition,
a gate line) before you add a sentence to a prompt.

## Budget

Per wake: `status`, `gate`, `read outbox` and at most three status files. Do not read code, logs
or worker output. If you need more than that to decide, send a lookup task. Your cost should be a
few thousand tokens per wake.

## Rules

- No tier certifies its own work. Workers are checked by the orchestrator, the orchestrator by the
  gate and by you.
- Never relay a number you did not see in a file.
- Pushing, publishing, deleting and spending are the user's decisions. Record each one in
  `GOAL.md` when given.
- One orchestrator, one item, one owner, one brief. Resume the session; do not duplicate it.
- `read` then `ack`. An unacked directive keeps the gate closed; an acked one is your
  responsibility.
- When `space.py` refuses a command, do what its message says. Do not work around it.
