#!/bin/bash
# #22: run a pinned awesome-compose sample set against one engine.
# Usage: measure22.sh <dd|socktainer> <samples-dir> <out-dir> [sample ...]
#   dd         -> docker --context desktop-linux (control)
#   socktainer -> DOCKER_HOST=unix://$HOME/.socktainer/container.sock
# With sample names, runs only those (e.g. the ones that passed on dd).
# A sample passes when: up --build --wait succeeds, the entry port answers
# HTTP 2xx/3xx within 120s, and down -v succeeds.
set -u
ENGINE=$1; SAMPLES=$2; OUT=$3; shift 3
ONLY=" $* "
mkdir -p "$OUT"
RES="$OUT/results-$ENGINE.tsv"
printf 'sample\tup\tprobe\tdown\tsecs\tnote\n' > "$RES"

# sample:entry-port. Left out: pihole (:53), wireguard (UDP, NET_ADMIN),
# minecraft (not HTTP), plex (no port), wasmedge-* (wasm runtime),
# elasticsearch-logstash-kibana and aspnet-mssql (heavy, amd64-only db).
SET="angular:4200 apache-php:80 django:8000 fastapi:8000 flask:8000
flask-redis:8000 gitea-postgres:3000 nextcloud-postgres:80
nextcloud-redis-mariadb:80 nginx-aspnet-mysql:80 nginx-flask-mongo:80
nginx-flask-mysql:80 nginx-golang:80 nginx-golang-mysql:80
nginx-golang-postgres:80 nginx-nodejs-redis:80 nginx-wsgi-flask:80
portainer:9000 postgresql-pgadmin:5050 prometheus-grafana:3000
react-express-mongodb:3000 react-express-mysql:3000 react-java-mysql:3000
react-nginx:80 react-rust-postgres:3000 sparkjava:8080 sparkjava-mysql:8080
spring-postgres:8080 traefik-golang:80 vuejs:8080 wordpress-mysql:80"

if [ "$ENGINE" = dd ]; then
  DC=(docker --context desktop-linux compose)
  DK=(docker --context desktop-linux)
else
  SOCK="unix://$HOME/.socktainer/container.sock"
  DC=(env DOCKER_HOST="$SOCK" docker compose)
  DK=(env DOCKER_HOST="$SOCK" docker)
fi

# macOS has no coreutils timeout. perl execs the command itself, so the
# alarm kills compose and not a wrapper shell that would orphan it.
tmo() { perl -e 'alarm shift; exec @ARGV' "$@"; }

for entry in $SET; do
  s=${entry%%:*}; port=${entry##*:}; p="fl22-$s"; log="$OUT/$ENGINE-$s.log"
  [ "$ONLY" != "  " ] && [[ "$ONLY" != *" $s "* ]] && continue
  echo "== $s (port $port)" | tee "$log"
  (cd "$SAMPLES/$s" && "${DC[@]}" -p "$p" down -v --remove-orphans --timeout 5) >>"$log" 2>&1
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    printf '%s\tskip\tskip\tskip\t0\tport %s busy\n' "$s" "$port" | tee -a "$RES"
    continue
  fi
  t0=$(date +%s); note=""
  (cd "$SAMPLES/$s" && tmo 600 "${DC[@]}" -p "$p" up -d --build --wait --wait-timeout 300) >>"$log" 2>&1
  up=$?
  code=000
  for _ in $(seq 1 60); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$port/" || true)
    case $code in 2??|3??) break ;; esac
    /bin/sleep 2
  done
  case $code in 2??|3??) probe=ok ;; *) probe="fail($code)" ;; esac
  echo "-- ps" >>"$log"; (cd "$SAMPLES/$s" && "${DC[@]}" -p "$p" ps -a) >>"$log" 2>&1
  if [ "$up" != 0 ] || [ "$probe" != ok ]; then
    echo "-- logs" >>"$log"; (cd "$SAMPLES/$s" && "${DC[@]}" -p "$p" logs --tail 30) >>"$log" 2>&1
    note=$(grep -iE 'error|failed|not implemented|unsupported' "$log" | grep -vE '^\s*$' | head -1 | cut -c1-160 | tr '\t' ' ')
  fi
  (cd "$SAMPLES/$s" && tmo 180 "${DC[@]}" -p "$p" down -v --remove-orphans --timeout 10) >>"$log" 2>&1
  down=$?
  left=$("${DK[@]}" ps -aq --filter "label=com.docker.compose.project=$p" 2>/dev/null)
  if [ -n "$left" ]; then
    echo "-- leftovers: $left" >>"$log"
    "${DK[@]}" rm -f $left >>"$log" 2>&1
    [ "$down" = 0 ] && down=left
  fi
  secs=$(( $(date +%s) - t0 ))
  [ "$up" = 0 ] && up=ok || up="fail($up)"
  [ "$down" = 0 ] && down=ok || down="fail($down)"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$s" "$up" "$probe" "$down" "$secs" "$note" | tee -a "$RES"
done
ran=$(awk -F'\t' 'NR>1 && $2!="skip"' "$RES" | wc -l | tr -d ' ')
pass=$(awk -F'\t' 'NR>1 && $2=="ok" && $3=="ok" && $4=="ok"' "$RES" | wc -l | tr -d ' ')
echo "== $ENGINE: $pass/$ran pass" | tee -a "$RES"
