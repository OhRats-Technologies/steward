# Evals

Executable scenarios testing whether a smaller model can drive `.steward/` from the skill prompts alone.

## Scenario Harness (`run.py`)

`scenarios.jsonl` has 27 scenarios (15 steward, 12 orchestrator). Each builds a brainspace, shows the model `GOAL.md`, the ledger, and any unacked mail, gives it one event, executes the `space.py` commands it replies with (up to five rounds), and checks the resulting state deterministically.

```sh
python3 evals/run.py --selfcheck
python3 evals/run.py --model claude-haiku-5-5 --repeats 3
python3 evals/run.py --model 'opencode-go/deepseek-v4.1-flash#low' --repeats 3
```

- A `provider/model[#variant]` id runs through `opencode run`; anything else runs through `claude -p`.
- `--selfcheck` verifies every scenario's reference solution passes and that doing nothing fails.
- Raw JSONL outputs are written to `evals/results/` (gitignored).

`decompose-train.jsonl` and `decompose-heldout.jsonl` hold additional orchestrator decomposition scenarios (pass via `--scenarios`).

## End-to-End Fixtures (`e2e/`)

`e2e/full.sh <name> "<task>"` runs a full team in OpenCode against a fixture repo under `e2e/` (`base/`, `debug-base/`, `debug-big/`) with debug mode enabled, then surveys each session using `e2e/survey.txt`. These are manual local runs and are not run in CI.
