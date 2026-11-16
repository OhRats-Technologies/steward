#!/usr/bin/env bash
# Done when every test passes and tests/ is unchanged.
cd "$(dirname "$0")"
git diff --quiet HEAD -- tests/ || { echo "FAIL tests/ was modified"; exit 1; }
python3 -m unittest discover -s tests -t . 2>&1 | tail -3
python3 -m unittest discover -s tests -t . >/dev/null 2>&1 && echo PASS
