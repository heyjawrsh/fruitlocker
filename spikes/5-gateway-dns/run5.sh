#!/bin/zsh
# fruitlocker spike #5: drive gwbind.py (running as root in another terminal)
# through bind/unbind cycles while guests on several networks keep resolving.
# Usage: zsh run5.sh <ctl-file> <helper-log>
set -u
CTL=$1 HLOG=$2
C=container IMG=alpine:3.20
X() { echo "\n\$ $*"; "$@" 2>&1 | grep -v '^\[[0-9]/[0-9]\]'; echo "[exit ${pipestatus[1]}]"; }
p53() { echo "-- :53 sockets"; netstat -anv -p udp | awk '$4 ~ /\.53$/ {print "  ", $1, $4}'; }
# one-line lookup result: "<ctr> <name> -> <answers or error>"
L() {
  local r
  r=$($C exec $1 nslookup -type=a $2 2>&1 | awk '/^Address: /{a=a" "$2} /NXDOMAIN/{n=1} /refused|timed out|no servers/{e=1} END{if(e)print "ERROR"; else if(a)print a; else if(n)print " NXDOMAIN"; else print " ?"}')
  echo "  $1 $2 ->$r"
}
ctl() { print -r -- "$1" > $CTL; sleep 1.5; echo "-- ctl: ${1:-<empty>}"; }
gw() { $C ls --format json | /usr/bin/python3 -I -c "import json,sys; print(next(n['ipv4Gateway'] for c in json.load(sys.stdin) if c['id']=='$1' for n in c['status']['networks']))"; }
hlog() { echo "-- helper log (new lines)"; tail -n +$((HL+1)) $HLOG | sed 's/^/   /'; HL=$(wc -l < $HLOG); }

CTRS=(fl5-a1 fl5-b1 fl5-d1)
NETS=(fl5_a fl5_b)
cleanup() { for n in $CTRS; do $C rm -f $n >/dev/null 2>&1; done; for n in $NETS; do $C network rm $n >/dev/null 2>&1; done; }

umask 022; : > $CTL
[[ -s $HLOG ]] && grep -q ready $HLOG || { echo "helper not running (no 'ready' in $HLOG)"; exit 1; }
HL=$(wc -l < $HLOG)
cleanup

echo "## 1. setup: d1 on default first (holds its bridge, avoids apple/container#2051), then a1 on fl5_a, b1 on fl5_b"
$C run -d --name fl5-d1 --network default $IMG sleep 1800 >/dev/null
for n in $NETS; do $C network create $n >/dev/null; done
$C run -d --name fl5-a1 --network fl5_a   $IMG sleep 1800 >/dev/null
$C run -d --name fl5-b1 --network fl5_b   $IMG sleep 1800 >/dev/null
GA=$(gw fl5-a1) GB=$(gw fl5-b1) GD=$(gw fl5-d1)
echo "gateways: a=$GA b=$GB default=$GD"
echo "-- host bridges: $(ifconfig | awk '/^bridge/{i=$1} /inet 192.168/ && i{print i, $2}' | tr '\n' ' ')"
base=$(for c in $CTRS; do L $c example.com; L $c fl5-probe; done); echo "$base"
p53
[[ $base == *ERROR* ]] && { echo "baseline broken before the helper did anything; aborting"; cleanup; exit 2; }

echo "## 2. helper binds fl5_a's gateway only"
ctl "up $GA"
p53; hlog
for c in $CTRS; do L $c fl5-probe; L $c example.com; done
hlog

echo "## 3. helper releases: fl5_a falls straight back to mDNSResponder"
ctl ""
L fl5-a1 example.com; L fl5-a1 fl5-probe
p53; hlog

echo "## 4. 10 up/down cycles, querying in each state"
ok=0
for i in {1..10}; do
  ctl "up $GA" >/dev/null; r1=$(L fl5-a1 fl5-probe); r2=$(L fl5-a1 example.com)
  ctl "" >/dev/null;       r3=$(L fl5-a1 example.com); r4=$(L fl5-a1 fl5-probe)
  if [[ $r1 == *10.55.55.55 && $r2 != *ERROR* && $r3 != *ERROR* && $r4 == *NXDOMAIN ]]; then ok=$((ok+1)); else echo "  cycle $i FAIL: $r1 | $r2 | $r3 | $r4"; fi
done
echo "  cycles passed: $ok/10"
p53

echo "## 5. two gateways at once; default network untouched"
ctl "up $GA
up $GB"
for c in $CTRS; do L $c fl5-probe; done
L fl5-d1 example.com
hlog

echo "## 6. guest restart with the helper holding fl5_a"
ctl "up $GA"
X $C stop fl5-a1
sleep 3; echo "-- bridges: $(ifconfig -l)"; hlog
X $C start fl5-a1
sleep 3; L fl5-a1 fl5-probe; L fl5-a1 example.com
hlog

echo "## 7. all guests stop with the helper still asking for fl5_a; then restart"
X $C stop fl5-a1 fl5-b1 fl5-d1
for i in {1..90}; do netstat -an -p udp | awk '$1=="udp4" && $4=="*.53" {f=1} END{exit !f}' || break; sleep 1; done
echo "-- after stop (${i}s)"; p53; hlog
X $C start fl5-d1
sleep 3; L fl5-d1 example.com; p53
X $C start fl5-a1
sleep 3; L fl5-a1 fl5-probe; L fl5-a1 example.com; L fl5-d1 example.com
p53; hlog

echo "## 8. release and clean up"
ctl ""
L fl5-a1 example.com; L fl5-d1 example.com
cleanup
sleep 2; p53; hlog
