# Steward

A three-tier agent pattern: a frontier **steward** guards the user channel and looks in rarely, a
mid-tier **orchestrator** decomposes and checks, and cheap **workers** do one subtask each. The
user never talks to the orchestrator.

The point is the shield. A mid-tier model that receives a conversational message answers it and
stops. The orchestrator here receives only typed directives through a file, and a deterministic
gate decides when it may stop.

```
user <-> STEWARD (frontier, wakes on user messages and orchestrator reports)
            |  GOAL.md, INBOX: task | steer | cancel | note
            v
        ORCHESTRATOR (mid-tier subagent, runs until the gate passes)
            |  briefs                      ^ OUTBOX: escalate | milestone | finished
            v                              |
        WORKERS (cheap subagents) -- each in agents/<X>/: BRIEF, STATUS, notes/, out/
```

This repository packages the pattern three ways:

- as an **Agent Skill** (`skills/steward/SKILL.md`) for any compatible client;
- as an **Agent Plugin** (`plugin.json` plus `skills/`) for Agent Plugins 1.0.0 clients;
- with an **OpenCode 2.x adapter** (`skills/steward/adapters/opencode/agents/`) that maps the
  orchestrator and workers to real subagents.

## Install (OpenCode 2.x)

From this repository:

```sh
mkdir -p .opencode/skills/steward .opencode/agents
cp -r skills/steward/. .opencode/skills/steward/
cp skills/steward/adapters/opencode/agents/*.md .opencode/agents/
```

Then uncomment and set `model:` in both copied agent files
(`.opencode/agents/steward-orchestrator.md` and `.opencode/agents/steward-worker.md`). Without a
model they inherit the steward's model, and the cost split disappears.

Add the nesting depth to `opencode.json(c)`. OpenCode defaults to one level, which lets the
steward launch the orchestrator but stops the orchestrator from launching workers:

```jsonc
{
  "experimental": {
    "subagent_depth": 2
  }
}
```

OpenCode discovers `.opencode/skills` and `.opencode/agents` automatically. The launching session
needs the `subagent` tool and permission to launch `steward-orchestrator`.

Global install: copy the skill to `~/.config/opencode/skills/steward` and the two agent files to
`~/.config/opencode/agents/`.

## Use

In a session on a frontier model, ask for a goal and mention the steward skill. The steward:

1. creates `.steward/GOAL.md` and the ledger;
2. launches `steward-orchestrator` as a background subagent and stores its session id;
3. ends its turn. When the orchestrator goes idle — waiting, escalating or finished — the steward
   is woken with a report.

Manual start:

```sh
python3 .opencode/skills/steward/scripts/space.py --dir .steward init
```

Then write `GOAL.md` and add one ledger line per request. The full protocol is in
`skills/steward/SKILL.md`; the orchestrator prompt is `skills/steward/orchestrator-prompt.md`.

The gate is the stop condition:

```sh
python3 .opencode/skills/steward/scripts/space.py --dir .steward gate
# 0 finished | 2 keep going | 3 waiting on the user
```

## State: JSON lines, not SQLite

The brainspace is a directory, by default `.steward/` in the project. Never `/tmp`.

- **Durable.** `/tmp` is cleared on reboot and is not project-scoped. A long job must survive both.
- **Readable.** The steward answers from `LEDGER.jsonl` and `agents/*/STATUS.md` directly. SQLite
  would hide that behind queries and add a dependency to every worker.
- **Safe enough.** Only the steward and one orchestrator write, and `space.py` serializes every
  ledger and mailbox mutation with a file lock, then replaces the file atomically after fsync. A
  crash cannot leave a half line. The lock is POSIX; on Windows, run under WSL.
- **Migrate later if needed.** If more concurrent writers appear, SQLite becomes the right call.
  At two writers it is extra machinery with no measured benefit.

`init` writes `.steward/.gitignore`, so the state never lands in the project's history.

## Test

```sh
python3 -m unittest discover -s skills/steward/tests -v
```

The suite covers init preservation, ledger transitions, gate exit codes, unread/ack semantics,
message validation, worker directories, session handles and concurrent adds.

The finish path and the escalation → approval → resume path were also smoke-tested end to end on
OpenCode 2.3.0 with a toy goal on 2026-11-16. The multi-model cost split was not measured.

## Compliance

- **Agent Skills:** `skills/steward/SKILL.md`; `name: steward` matches its directory; frontmatter
  follows the required fields. `skills-ref validate skills/steward` passes.
- **Agent Plugins 1.0.0:** root `plugin.json` with the canonical `$schema`, and skills under the
  fixed `skills/` location. No MCP servers, so no `mcp.json`. The manifest validates against the
  published 1.0.0 schema.
- **OpenCode 2.x:** skill in `.opencode/skills`, agents in `.opencode/agents`; the skill and agents
  are copied from this repository, not loaded from it.

## Limits

- The state machine is unit-tested; the hierarchy's quality still depends on the models and on how
  often the steward must wake to catch drift.
- The steward answers from files it did not write. Stale status files give stale answers.
- The gate checks that evidence exists, not that it is good; the check-in is the only quality guard.
- Cost is not measured. The design intent is a few thousand steward tokens per wake.

## License

MIT. See `LICENSE`.
