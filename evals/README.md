# Eval

Can a small model drive the brainspace correctly from the skill text alone?

`scenarios.jsonl` holds 27 scenarios (15 steward, 12 orchestrator). Each builds a brainspace, shows
the model `GOAL.md`, the ledger and the unacked mail, and gives it one event. The model replies
with `space.py` commands; the runner executes them, shows the output (a line the shell could not
parse is shown as a shell error), and allows up to five rounds in all.
Then `check()` in `run.py` compares the ledger and mailboxes with the scenario's `expect` by rule.

Two whole skill versions are compared, prompt and script together:

- `v01`: the first release, kept in `v01/`. Prose protocol; the script accepts any state change.
- `v02`: the current skill in `../skills/steward/`.

```sh
python3 evals/run.py --selfcheck
python3 evals/run.py --model claude-haiku-5-5 --repeats 3                     # via `claude -p`
python3 evals/run.py --model 'opencode-go/deepseek-v4.1-flash#low' --repeats 3 # via `opencode run`
python3 evals/run.py --model spark-local/spark-dspark --versions v02 --repeats 1 --workers 2
```

A `provider/model[#variant]` id runs through `opencode run` with a no-tool agent; anything else
runs through `claude -p` with no tools and no settings. A call that times out or returns nothing
is retried once.

`--selfcheck` runs each scenario's reference solution under both versions and confirms that doing
nothing fails. Raw replies and command logs are in `results/`.

## Results

| Model | Date | v01 | v02 |
|---|---|---|---|
| DeepSeek V4.1 Flash, `#low` (OpenCode Go), 5 rounds | 2026-11-16 | 64/81 | 81/81 |
| DeepSeek V4.1 Flash, default reasoning, 3 rounds, before the fixes below | 2026-11-16 | 61/81 | 76/81 |
| Claude Haiku 5.5, 3 rounds, before the fixes below | 2026-11-16 | 56/81 | 75/81 |

Each cell is 27 scenarios × 3 trials. The rows are not one experiment: the skill, two scenarios and
the round limit changed between them (below).

What DeepSeek exposed, and what changed:

- **A status question became a ledger item** (v02 0/3). Asked "how far along is the parser? and
  drop the changelog task", it cancelled correctly but also filed `task "report progress on L1"`.
  `SKILL.md` allowed a lookup task. Now `task` refuses a request that names an existing item and
  says to answer from `status` or `steer` it (`--new` for separate work), and `status` prints
  "no status line yet" for a worker that has not written one.
- **The orchestrator could not reach a running worker.** The prompt said to send a steer or a
  failure to the worker's session, but no command did; the model spent its rounds on `--help`.
  `tell A "..."` now writes the instruction to `agents/A/notes/ORCHESTRATOR.md`, which every brief
  says to read before each step, and prints the resume call. The orchestrator prompt lists the
  exact commands, and `space.py help` works.
- **A destructive instruction with two readings was assigned.** `assign` now refuses work that
  deletes or overwrites unless `--confirmed` quotes the words that name what goes; the refusal
  says to escalate otherwise.
- **Whether to ack an escalation the user has not answered** was ambiguous. Now `ack` refuses it
  and the answering `steer` acks it.

Two failures were the eval's fault, and both scenarios were fixed:

- `st-finished-report` recorded evidence (`grep -q receive`) that does not prove the typo is gone.
  DeepSeek refused to report done and reopened the item, which was right. The item now carries the
  goal's own check.
- An `escalate` line with an apostrophe inside single quotes failed to parse and was dropped
  silently, so the model never saw the error. The harness now shows it as a shell error.

## Decomposition: train and held-out (DeepSeek V4.1 Flash `#low`)

`decompose-train.jsonl` and `decompose-heldout.jsonl` each hold five orchestrator scenarios with
the same shapes in different domains: three independent parts, a strict sequence, one small task
that must not be split, a mix, and a fan-in. The check reads the ledger: which parts exist, which
were started, and what each waits for. Both sets were written before any guidance; the skill was
changed only from train failures, and held-out results were never used to change it.

| Step | Train | Held-out |
|---|---|---|
| Mechanism only (`add --part-of`, `--after`) | 5/15 | 4/15 (4/12 on the four unchanged scenarios) |
| After three rounds of changes from train failures | 14/15, then 15/15 | 15/15, then 12/15 on a second run |

What the train failures taught, and the change each produced:

1. The model assigned multi-part requests whole. `gate` said "assign it" for every open item. It
   now asks: can one worker finish all of it with one done command? Otherwise split it. The
   orchestrator prompt gained four questions: one result or several? Which are real work? Does a
   part need another's output, or only the same facts? Which wait for nothing, so start now?
2. The first "three independent parts" scenarios were three one-line edits, which one worker
   should do together. The model was right and both scenarios (train and held-out) were changed
   to three parts that are each real work. This was decided from the train result, before the
   held-out one was read.
3. A part the user ordered with "then" was started early, and the model could not fix it: there
   was no way to add an order later. Now `set L5 --after L4` exists, `help add` works, and the
   prompt says a stated order is kept.
4. Batched `add` commands guessed ids wrong, and a re-sent block made duplicate parts. `gate` and
   `list` now print each dependency's request beside its id, and a repeated part is refused.
5. The prompt said a stuck worker "gets a worker to find" the missing fact, but the script
   refused new parts on delegated work. The prompt now says to add the finder as its own item.

The remaining held-out misses (3/15 on the second run) are all the same judgment: a two-part
request assigned whole. They were left as they are. Five held-out scenarios is a small set; a new
one is needed before tuning again.

## How much to trust this

- It is a development result. The first run on these scenarios scored v02 at 54/84 against 51/84
  for v01, on a one-shot harness. That run exposed real defects, which were then fixed: `ack`
  required a mailbox name the model kept omitting, `done` did not say when to send `finished`, and
  the steward sent a `note` beside every answer. The scores above are after those fixes, on the
  same scenarios. A fresh scenario set is needed to claim the gain generalizes.
- After the DeepSeek run the round limit went from three to five, because a model that read
  `--help` first ran out of rounds before acting; a real orchestrator has no such limit. Two
  scenarios were corrected (above). The 81/81 row is after all of this, on the same scenarios.
- Three changes were made to the eval itself after seeing results: the harness became multi-round
  so the model can read error messages, `GOAL.md` was added to what the model sees, and one
  scenario was removed because it required evidence the model could not obtain without a shell
  (the model correctly refused). One over-strict assertion was relaxed. These apply to both
  versions.
- Three trials per scenario is few. Scenario-level numbers move between runs.
- Only state commands are tested. The model cannot launch subagents or run a shell here.
- The scenarios were written by one model from the skill text, so they share its reading of it.
