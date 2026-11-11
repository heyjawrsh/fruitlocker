#!/bin/zsh
# fruitlocker spike #4: exercise flresolver.py against two Compose-style projects.
# Assumes `container system start` is running and flresolver.py is NOT yet running.
# Usage: zsh run.sh <logdir>
set -u
HERE=${0:A:h}
OUT=${1:-/tmp/fl-spike}
mkdir -p $OUT
C=container
IMG=alpine:3.20
X() { echo "\n\$ $*"; "$@" 2>&1 | grep -v '^\[[0-9]/[0-9]\]'; echo "[exit ${pipestatus[1]}]"; }
lbl() { echo --label com.docker.compose.project=$1 --label com.docker.compose.service=$2; }

CTRS=(pa-db-1 pa-web-1 pa-web-2 pa-multi-1 pa-tools-1 pb-db-1 pb-tools-1)
NETS=(pa_default pa_back pb_default)
cleanup() {
  for n in $CTRS; do $C rm -f $n >/dev/null 2>&1; done
  for n in $NETS; do $C network rm $n >/dev/null 2>&1; done
}
cleanup

echo "## 1. start resolver (must win :53 before any guest does DNS; mDNSResponder grabs it on demand)"
for i in {1..60}; do netstat -an -p udp | grep -qE '[*.]53 ' || break; sleep 1; done
netstat -anv -p udp | grep -E '[*.]53 ' || echo ":53 free"
python3 -I $HERE/flresolver.py > $OUT/resolver.log 2>&1 &
RPID=$!
sleep 2
head -3 $OUT/resolver.log
netstat -anv -p udp | grep -E "[*.]53 " | awk '{print $1, $4, $(NF-7)}'

echo "## 2. projects: pa (db, web x2, multi on 2 nets, tools) and pb (db, tools)"
for n in $NETS; do $C network create $n >/dev/null; done
$C run -d --name pa-db-1    $(lbl pa db)    --label fl.aliases=postgres --network pa_default $IMG sleep 900 >/dev/null
$C run -d --name pa-web-1   $(lbl pa web)   --network pa_default $IMG sleep 900 >/dev/null
$C run -d --name pa-web-2   $(lbl pa web)   --network pa_default $IMG sleep 900 >/dev/null
$C run -d --name pa-multi-1 $(lbl pa multi) --network pa_default --network pa_back $IMG sleep 900 >/dev/null
$C run -d --name pa-tools-1 $(lbl pa tools) --network pa_back $IMG sleep 900 >/dev/null
$C run -d --name pb-db-1    $(lbl pb db)    --network pb_default $IMG sleep 900 >/dev/null
$C run -d --name pb-tools-1 $(lbl pb tools) --network pb_default $IMG sleep 900 >/dev/null
X $C ls
sleep 2  # let the poller see them

Q() { X $C exec $1 nslookup $2; }
echo "## 3. pa-web-1 (pa_default)"
for h in db postgres web pa-db-1 multi tools pb-db-1 example.com; do Q pa-web-1 $h; done
echo "## 4. pb-tools-1 (pb_default): its own db, nothing from pa"
for h in db web postgres; do Q pb-tools-1 $h; done
echo "## 5. pa-multi-1 (pa_default + pa_back): sees both"
for h in db tools web; do Q pa-multi-1 $h; done
echo "## 6. pa-tools-1 (pa_back only): sees multi, not db"
for h in multi db; do Q pa-tools-1 $h; done

echo "## 7. connectivity by name"
X $C exec pa-web-1 ping -c1 -W2 db
X $C exec pb-tools-1 ping -c1 -W2 db

echo "## 8. scaled service round-robin (10 lookups of web from pa-db-1)"
X $C exec pa-db-1 sh -c 'for i in 1 2 3 4 5 6 7 8 9 10; do nslookup -type=a web 2>/dev/null | awk "/^Address: /{print \$2; exit}"; done | sort | uniq -c'

echo "## 9. restart: name follows new IP"
X $C stop pa-db-1
sleep 2
Q pa-web-1 db
X $C start pa-db-1
sleep 2
X $C ls
Q pa-web-1 db

echo "## 10. forwarding: internet, apk, split DNS via scutil"
X $C exec pa-web-1 sh -c 'apk add -q bind-tools >/dev/null 2>&1 && echo apk-ok'
X $C exec pa-web-1 sh -c 'for i in 1 2 3 4 5; do dig +noall +stats example.com | grep "Query time"; done'
X $C exec pa-web-1 sh -c 'for i in 1 2 3 4 5; do dig +noall +stats db | grep "Query time"; done'
X $C exec pa-web-1 dig +short MX gmail.com
X $C exec pa-web-1 dig +short TXT example.com

echo "## 11. non-vmnet source is dropped (query from this Mac to its LAN IP)"
LAN=$(ipconfig getifaddr en0 || ipconfig getifaddr en1)
X dig +tries=1 +time=2 @$LAN example.com

echo "## 12. resolver stops: guests fall back to vmnet default"
kill $RPID; sleep 1
X $C exec pa-web-1 nslookup example.com
X $C exec pa-web-1 nslookup db

echo "## 13. baseline: vmnet default DNS (mDNSResponder proxy), resolver stopped"
X $C run --rm $IMG sh -c 'apk add -q bind-tools >/dev/null 2>&1; for i in 1 2 3 4 5; do dig +noall +stats example.com | grep "Query time"; done'


cleanup
echo "\n## resolver log"
cat $OUT/resolver.log
