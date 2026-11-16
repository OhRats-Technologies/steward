#!/usr/bin/env bash
# Done when: both translations exist and look translated, README links both near the top,
# and README's original text is otherwise intact.
cd "$(dirname "$0")"; ok=1
for f in README.fr.md README.es.md; do [ -s $f ] && [ $(wc -w < $f) -ge 80 ] || { echo "FAIL $f missing or short"; ok=0; }; done
grep -qiE "\b(le|les|des|fichier|ligne)\b" README.fr.md 2>/dev/null || { echo "FAIL README.fr.md not French"; ok=0; }
grep -qiE "\b(el|los|archivo|línea|lineas|líneas)\b" README.es.md 2>/dev/null || { echo "FAIL README.es.md not Spanish"; ok=0; }
head -8 README.md | grep -q "README.fr.md" && head -8 README.md | grep -q "README.es.md" || { echo "FAIL links not at top of README.md"; ok=0; }
grep -vE "README\.(fr|es)\.md" README.md | grep -vE "^\s*$" > /tmp/.a; grep -vE "^\s*$" .README.orig > /tmp/.b
diff -q /tmp/.a /tmp/.b >/dev/null || { echo "FAIL README.md text changed beyond the links"; ok=0; }
[ $ok = 1 ] && echo PASS; [ $ok = 1 ]
