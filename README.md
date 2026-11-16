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

The steward drives everything through one script, one command per user act:

```sh
S="python3 .opencode/skills/steward/scripts/space.py --dir .steward"
$S init
$S task "add a --json flag to the CLI" --check "pytest -q tests/test_cli.py"   # prints L1
$S steer L1 "name the flag --format json instead"
$S note "never touch vendor/"
$S status        # phase, every item, each worker's last line, stale workers
$S cancel L1 "not needed any more"
$S gate          # 0 finished | 2 keep going | 3 waiting on the user
```

The full protocol is in `skills/steward/SKILL.md`; the orchestrator's is
`skills/steward/orchestrator-prompt.md`.

## The state machines are in the script, not the prompts

The first version described its protocol in prose and let the script accept anything. Every rule
a model had to remember was a place a weak model failed. Each of those implicit state machines is
now explicit in `space.py`, which refuses an illegal step and says what to do instead.

| State machine | States | Enforced by |
|---|---|---|
| Item | `open → delegated → done`, `blocked-on-user`, `cancelled` | A transition table. `done` needs evidence; a reopened item loses its old evidence |
| Proof | claimed → checked | An item can carry `--check`. `done` runs it and closes the item only on exit 0, so a worker's word cannot close it |
| Escalation | asked → answered | `escalate` blocks the item and reports in one step. The question cannot be acked while open; the `steer` that answers it unblocks the item, acks the question and records the decision in `GOAL.md` |
| Directive | sent → read → acked | `read` does not consume; the gate stays closed until `ack` |
| Brief | none → written → session recorded | `assign` writes all six parts and every standing rule. One worker owns one item; only open work can be assigned. Work that deletes or overwrites needs `--confirmed '<the words naming what goes>'`, otherwise the refusal says to escalate |
| Decomposition | open → split → done | `add '<part>' --part-of L1 [--after L2]` splits an item. A split item cannot be assigned; a part cannot start before what it waits for is done; the whole closes only after every part; cancelling it cancels its open parts |
| Worker instruction | told → read | `tell A` writes to the worker's `notes/ORCHESTRATOR.md`, which every brief says to read before each step, and prints the call that resumes it |
| Request | new work vs existing item | `task` refuses a request that names an existing item: a question goes to `status`, a change to `steer`; `--new` for separate work |
| Run | working → waiting on the user → finished | `gate` exit codes 2, 3, 0. `finished` cannot be sent while the gate is open |
| Orchestrator | none → recorded | `session` refuses to record a second one without `--replace` |

`gate` prints the next step for every unfinished item, and `status` gives the steward one screen
to answer from. Both exist so a model reads its next action instead of deriving it.

## Does it make a weak model stronger?

`evals/` holds an executable test: 27 scenarios, each a brainspace plus one event (a user message,
a worker report, an inbox line). The model sees only the skill text and the state, replies with
`space.py` commands, sees their output for up to three rounds, and the resulting files are checked
by rule. No model grades anything.

Three trials per scenario, 2026-11-16:

| Skill version | DeepSeek V4.1 Flash `#low` | Claude Haiku 5.5 (before the last fixes) |
|---|---|---|
| 0.1 (prose protocol, permissive script) | 64/81 (79 %) | 56/81 (69 %) |
| 0.2 (verbs, enforced lifecycle) | 81/81 (100 %) | 75/81 (93 %) |

Read this as a development result, not a held-out one. Each failure the models showed was fixed
in the script or the prompt and then measured again on the same 27 scenarios, so 81/81 shows the
known failures are gone, not that no failure remains. A finite eval cannot show that. Details,
every fix and the reproduction commands are in `evals/README.md`.

Decomposition (whole or parts, parallel or ordered) was measured with a train and a held-out set:
held-out went from 4/12 to 27/30 over two runs, with the skill changed only from train failures.
The questions the orchestrator now asks itself are in `orchestrator-prompt.md`, "Before you
assign".

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
python3 -m unittest discover -s skills/steward/tests -v   # the state machine, 73 tests
python3 evals/run.py --selfcheck                          # the scenarios are solvable and non-trivial
python3 evals/run.py --model claude-haiku-5-5 --repeats 3 # needs the `claude` CLI; about $0.30
python3 evals/run.py --model 'opencode-go/deepseek-v4.1-flash#low' --versions v02 --repeats 1  # smoke, ~2 min
```

The finish path and the escalation → approval → resume path of version 0.1 were smoke-tested end
to end on OpenCode 2.3.0 with a toy goal on 2026-11-16. Version 0.2 has not been run end to end on
OpenCode; its commands are tested by the unit tests and the eval only.

## Compliance

- **Agent Skills:** `skills/steward/SKILL.md`; `name: steward` matches its directory; frontmatter
  follows the required fields. `uvx --from skills-ref agentskills validate skills/steward` prints
  `Valid skill` (checked 2026-11-16).
- **Agent Plugins 1.0.0:** root `plugin.json` with the canonical `$schema`, and skills under the
  fixed `skills/` location. No MCP servers, so no `mcp.json`. The manifest validates against the
  published 1.0.0 schema.
- **OpenCode 2.x:** skill in `.opencode/skills`, agents in `.opencode/agents`; the skill and agents
  are copied from this repository, not loaded from it.

## Limits

- The eval covers state commands only. Launching subagents, writing good briefs and judging
  worker output are not measured, and no full run with a weak orchestrator has been measured.
- A check is only as good as the command the steward wrote. `test -f out.md` passes on an empty
  file. Items without a check still close on evidence text that nobody verifies.
- An orchestrator that ends its turn early is only caught when the steward next wakes. Nothing
  re-prompts it automatically.
- The steward answers from files it did not write. Stale status files give stale answers;
  `status` flags a silent worker but cannot tell a slow one from a dead one.
- Cost is not measured. The design intent is a few thousand steward tokens per wake.

## License

MIT. See `LICENSE`.
