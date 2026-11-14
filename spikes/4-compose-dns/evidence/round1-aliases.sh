#!/bin/zsh
# fruitlocker spike #4: Compose service networking on Apple container 1.7.1
set -u
C=container
X() { echo "\n\$ $*"; "$@" 2>&1; echo "[exit $?]"; }

cleanup() {
  for n in fl-db fl-web fl-cache fl-other fl-multi fl-http; do $C rm -f $n >/dev/null 2>&1; done
  for n in fl-a fl-b; do $C network rm $n >/dev/null 2>&1; done
}
cleanup

echo "## 1. networks"
X $C network create --label com.docker.compose.project=spike fl-a
X $C network create fl-b
X $C network inspect fl-a

echo "## 2. containers with aliases"
X $C run -d --name fl-db --network fl-a,alias=db,alias=postgres alpine:3.20 sleep 600
X $C run -d --name fl-web --network fl-a,alias=web alpine:3.20 sleep 600
X $C run -d --name fl-other --network fl-b,alias=other alpine:3.20 sleep 600
X $C run -d --name fl-multi --network fl-a,alias=multi --network fl-b alpine:3.20 sleep 600
X $C ls --format json

echo "## 3. guest DNS config"
X $C exec fl-web cat /etc/resolv.conf
X $C exec fl-web cat /etc/hosts
X $C exec fl-web ip -4 addr

echo "## 4. name resolution from fl-web (same network fl-a)"
for h in db postgres fl-db web multi other fl-other fl-db.fl-a; do
  X $C exec fl-web nslookup $h
done

echo "## 5. reachability by IP"
DBIP=$($C inspect fl-db | python3 -c 'import json,sys; d=json.load(sys.stdin)[0]; print(json.dumps(d.get("networks") or d.get("status",{}).get("networks")))')
echo "fl-db networks: $DBIP"
X $C exec fl-web ping -c1 -W2 db
X $C exec fl-other ping -c1 -W2 db
X $C exec fl-multi ping -c1 -W2 db
X $C exec fl-multi ping -c1 -W2 other
X $C exec fl-multi ip -4 addr

echo "## 6. published port to host localhost"
X $C run -d --name fl-http --network fl-a,alias=http -p 127.0.0.1:18080:8080 alpine:3.20 sh -c 'mkdir -p /w && echo fruitlocker-ok > /w/index.html && httpd -f -p 8080 -h /w'
sleep 2
X curl -s -m 5 http://127.0.0.1:18080/
X $C exec fl-web wget -qO- -T 3 http://http:8080/

echo "## 7. host reachability from guest"
X $C exec fl-web sh -c 'ip route; wget -qO- -T 3 http://192.168.64.1:18080/ || true'

echo "## 8. IP stability across stop/start"
X $C inspect fl-db
X $C stop fl-db
X $C start fl-db
sleep 2
X $C inspect fl-db
X $C exec fl-web nslookup db

cleanup
echo "\ndone"
