#!/usr/bin/env bash
# usage: full.sh <name> <task text>. Runs the Haiku team, then surveys every session by resume.
B=${E2E_DIR:-/tmp/steward-e2e}; S=$(cd "$(dirname "$0")/../.." && pwd); n=$1; task=$2; d=$B/$n
rm -rf $d; mkdir -p $B; cp -r $S/evals/e2e/base $d; cd $d; git init -q
mkdir -p .opencode/skills/steward .opencode/agents && cp -r $S/skills/steward/. .opencode/skills/steward/ && cp $S/skills/steward/adapters/opencode/agents/*.md .opencode/agents/
sed -i 's|^# model: provider/model|model: claude-agent/haiku|' .opencode/agents/*.md
printf '{\n  "experimental": { "subagent_depth": 2 }\n}\n' > opencode.json
python3 .opencode/skills/steward/scripts/space.py --dir .steward init >/dev/null; python3 .opencode/skills/steward/scripts/space.py --dir .steward debug on >/dev/null
git add -A; git -c user.name=e2e -c user.email=e2e@x commit -qm skill
s=$(date +%s); PWD=$d timeout 3600 opencode run --model claude-agent/haiku --auto --format json "Use the steward skill for this goal. $task" > $B/$n.events.jsonl 2> $B/$n.err; e=$(date +%s)
echo "$n: $((e-s))s, check: $(./check.sh | tr '\n' ' ')" >> $B/summary5.txt
mk() { sed -e '1d;$d' -e "s|{WHO}|$1|g" -e "s|{THREAD}|${THREAD:-$B/thread.md}|g" -e "s|{ANSWER}|$d/.steward/survey/$1.md|g" -e 's/^ONE LAST STEP (you are \(.*\))\. Your task is done; this does not change it\./This is the user who started this run. Your task is done; this request does not change it. You are \1./' $S/evals/e2e/survey.txt; }
sid=$(python3 -c "import json;print(json.loads(open('$B/$n.events.jsonl').readline())['sessionID'])")
pids=""
for pair in "steward:$sid" "orchestrator:$(cat .steward/SESSION 2>/dev/null)" $(for a in .steward/agents/*/; do l=$(basename $a); echo "worker-$l:$(cat $a/SESSION 2>/dev/null)"; done); do
  who=${pair%%:*}; ses=${pair#*:}; [ -n "$ses" ] || { echo "$n $who: no session" >> $B/summary5.txt; continue; }
  PWD=$d timeout 1200 opencode run --session $ses --auto --format json "$(mk $who)" > $B/$n.survey-$who.jsonl 2>&1 & pids="$pids $!"; sleep 3
done
wait $pids
echo "$n surveys: $(ls $d/.steward/survey 2>/dev/null | tr '\n' ' ')" >> $B/summary5.txt
