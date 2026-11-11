#!/bin/zsh
# fruitlocker spike #4, round 3: per-project FQDN aliases + guest search domain.
# No system [dns] domain, no /etc/resolver changes, no sudo.
set -u
C=container
X() { echo "\n\$ $*"; "$@" 2>&1; echo "[exit $?]"; }
IMG=alpine:3.20
DA=pa.fruitlocker.internal   # Compose project "pa"
DB=pb.fruitlocker.internal   # Compose project "pb"

cleanup() {
  for n in pa-db-1 pa-web-1 pa-multi-1 pa-http-1 pb-db-1; do $C rm -f $n >/dev/null 2>&1; done
  for n in pa_default pa_back pb_default; do $C network rm $n >/dev/null 2>&1; done
}
cleanup

echo "## 1. networks (one per Compose network)"
X $C network create pa_default
X $C network create pa_back
X $C network create pb_default

echo "## 2. containers: same service name 'db' in two projects"
X $C run -d --name pa-db-1   --dns-search $DA --network pa_default,alias=db.$DA,alias=postgres.$DA $IMG sleep 900
X $C run -d --name pa-web-1  --dns-search $DA --network pa_default,alias=web.$DA $IMG sleep 900
X $C run -d --name pb-db-1   --dns-search $DB --network pb_default,alias=db.$DB $IMG sleep 900
X $C run -d --name pa-multi-1 --dns-search $DA --network pa_default,alias=multi.$DA --network pa_back,alias=multi-back.$DA $IMG sleep 900
X $C ls

echo "## 3. guest DNS config"
X $C exec pa-web-1 cat /etc/resolv.conf
X $C exec pa-web-1 cat /etc/hosts
X $C exec pa-web-1 hostname
X $C exec pa-multi-1 ip -4 addr
X $C exec pa-multi-1 cat /etc/resolv.conf

echo "## 4. resolution from pa-web-1"
for h in db postgres db.$DA web multi multi-back pa-db-1 db.$DB; do X $C exec pa-web-1 nslookup $h; done
echo "## 4b. resolution from pb-db-1 (other project)"
for h in db web db.$DA; do X $C exec pb-db-1 nslookup $h; done
echo "## 4c. host side, direct query to container DNS"
X dig +short @127.0.0.1 -p 2053 db.$DA
X dig +short @127.0.0.1 -p 2053 db.$DB
X dig +short @127.0.0.1 -p 2053 pa-db-1

echo "## 5. reachability"
X $C exec pa-web-1 ping -c1 -W2 db
X $C exec pb-db-1 ping -c1 -W2 db.$DA
X $C exec pa-multi-1 ping -c1 -W2 db

echo "## 6. published port + service-to-service HTTP"
X $C run -d --name pa-http-1 --dns-search $DA --network pa_default,alias=http.$DA -p 127.0.0.1:18080:8080 $IMG sh -c 'mkdir -p /w && echo fruitlocker-ok > /w/index.html && httpd -f -p 8080 -h /w'
sleep 3
X curl -s -m 5 http://127.0.0.1:18080/
X $C exec pa-web-1 wget -qO- -T 3 http://http:8080/

echo "## 7. guest to host"
X $C exec pa-web-1 ip route
X $C exec pa-web-1 nslookup host.container.internal

echo "## 8. IP + name after stop/start"
X $C ls
X $C stop pa-db-1
X $C exec pa-web-1 nslookup db
X $C start pa-db-1
sleep 2
X $C ls
X $C exec pa-web-1 nslookup db

echo "## 9. alias collision across projects with same FQDN"
X $C run -d --name pa-db-2 --network pa_default,alias=db.$DA $IMG sleep 5
$C rm -f pa-db-2 >/dev/null 2>&1

cleanup
echo "\ndone"
