#!/bin/bash
# Spike #11 harness: docker driver -> fruitlocker stand-in -> custom BuildKit
# (moby exporter) in an Apple container -> Apple image store.
# Run from spikes/11-build-path. Needs: container 1.7.1 running, docker CLI
# with buildx, Compose v5, Go via mise, uv. Leaves nothing behind.
set -u
cd "$(dirname "$0")"
H=$HOME/.fl11
SOCK=$H/e.sock
LOG=evidence/engine.log
OUT=evidence/run.log
BK_IMG=docker.io/moby/buildkit:v0.35.0
: > "$OUT"; : > "$LOG"
say() { echo "== $*" | tee -a "$OUT"; }
run() { "$@" >>"$OUT" 2>&1; }
ok=0; fail=0
check() { if eval "$2"; then ok=$((ok+1)); echo "PASS $1" | tee -a "$OUT"; else fail=$((fail+1)); echo "FAIL $1" | tee -a "$OUT"; fi; }
wait_log() { for _ in $(seq 1 30); do container logs "$1" 2>&1 | grep -q "running server" && return 0; /bin/sleep 1; done; return 1; }

cleanup() {
  say cleanup
  pkill -f fakeengine.py
  docker buildx rm fl11-stock >/dev/null 2>&1
  docker context rm -f fl11 >/dev/null 2>&1
  container rm -f fl11-stock fl11-flbk >/dev/null 2>&1
  container volume rm fl11-bkstate >/dev/null 2>&1
  for i in $(container image ls | awk '$1 ~ /^fl11\// || $1=="untagged" || $1=="fruitlocker/buildkit" {print $1":"$2}'); do
    container image rm "$i" >/dev/null 2>&1
  done
  container image ls --format json 2>/dev/null | /usr/bin/python3 -I -c 'import json,sys
for i in json.load(sys.stdin):
    n = i["configuration"]["name"]
    if n.startswith("untagged@"): print(n)' | while read -r n; do container image rm "$n" >/dev/null 2>&1; done
  /bin/rm -rf "$H"
}
trap cleanup EXIT

mkdir -p "$H/export"
say "versions"
run docker version --format 'docker {{.Client.Version}}'
run docker buildx version
run docker compose version
run container --version

say "1. stock BuildKit in an Apple container, used only to build the custom image"
container image pull "$BK_IMG" >/dev/null 2>&1
container run -d --name fl11-stock --cap-add ALL -p 127.0.0.1:12340:1234 "$BK_IMG" --addr tcp://0.0.0.0:1234 >/dev/null
wait_log fl11-stock
run docker buildx create --name fl11-stock --driver remote tcp://127.0.0.1:12340

say "2. build custom buildkitd (moby exporter) and its image"
(cd flbuildkitd && CGO_ENABLED=0 GOOS=linux GOARCH=arm64 mise exec -- go build -o bin/buildkitd .) >>"$OUT" 2>&1
(cd flbuildkitd && docker buildx build --builder fl11-stock -f Dockerfile.image -t fruitlocker/buildkit:spike \
  --output type=oci,dest="$H/flbk.tar" .) >>"$OUT" 2>&1
container image load -i "$H/flbk.tar" >>"$OUT" 2>&1
check "custom image loaded" "container image ls | grep -q 'fruitlocker/buildkit'"

say "3. start custom builder: all caps, state on a volume (overlayfs), drop dir"
container volume create fl11-bkstate >/dev/null 2>&1
container run -d --name fl11-flbk --cap-add ALL -p 127.0.0.1:12341:1234 \
  -v "$H/export:/fl-export" -v fl11-bkstate:/var/lib/buildkit \
  fruitlocker/buildkit:spike --addr tcp://0.0.0.0:1234 --oci-worker-snapshotter=overlayfs >/dev/null
wait_log fl11-flbk
check "builder uses overlayfs" "container logs fl11-flbk 2>&1 | grep -q 'snapshotter:overlayfs'"

say "4. stand-in engine + context"
(FL11_BK_PORT=12341 FL11_EXPORT_DIR="$H/export" nohup uv run -q --no-project --with grpcio \
  python -I fakeengine.py "$SOCK" "$LOG" >/dev/null 2>&1 &)
for _ in $(seq 1 30); do grep -q start "$LOG" 2>/dev/null && break; /bin/sleep 1; done
docker context create fl11 --docker "host=unix://$SOCK" >/dev/null
export FL11_TOK=dummy

say "5. docker build, no flags (default docker driver)"
docker --context fl11 build --secret id=tok,env=FL11_TOK -t fl11/app:plain ctx >>"$OUT" 2>&1
check "docker build -t loads into Apple store" "container run --rm fl11/app:plain 2>/dev/null | grep -q 'secret-ok'"

say "6. buildx build --load"
docker --context fl11 buildx build --load --secret id=tok,env=FL11_TOK -t fl11/app:load ctx >>"$OUT" 2>&1
check "buildx --load" "container image ls | grep -E '^fl11/app +load' >/dev/null"

say "7. buildx build --output type=oci (client-side export)"
docker --context fl11 buildx build --secret id=tok,env=FL11_TOK --output type=oci,dest="$H/out.tar" ctx >>"$OUT" 2>&1
check "oci output to client" "[ -s '$H/out.tar' ]"

say "8. untagged build"
docker --context fl11 build -q --secret id=tok,env=FL11_TOK ctx >>"$OUT" 2>&1
check "untagged lands as untagged@sha256" "container image ls | grep -q '^untagged'"

say "9. compose build (bake), two services in parallel"
(cd proj2 && docker --context fl11 compose build) >>"$OUT" 2>&1
check "compose service a" "container run --rm fl11/multi-a:1 2>/dev/null | grep -q from-a"
check "compose service b" "container run --rm fl11/multi-b:1 2>/dev/null | grep -q from-b"

say "10. buildx bake"
(cd proj && docker --context fl11 buildx bake --set app.tags=fl11/bake-app:1) >>"$OUT" 2>&1
check "bake" "container image ls | grep -q 'fl11/bake-app'"

say "11. linux/amd64 RUN"
docker --context fl11 build --no-cache --platform linux/amd64 -t fl11/amd:1 -f evidence/Dockerfile.amd64 ctx >>"$OUT" 2>&1
check "amd64 RUN" "container run --rm fl11/amd:1 2>/dev/null | grep -q x86_64"

say "12. cache and history through /grpc"
check "buildx du" "docker --context fl11 buildx du 2>/dev/null | grep -q Total"
check "buildx history ls" "docker --context fl11 buildx history ls 2>/dev/null | grep -q Completed"
check "builder prune" "docker --context fl11 builder prune -f >/dev/null 2>&1"

say "engine requests (non-grpc)"
grep -vE '/grpc|/session|_ping|closed|md keys|stream end' "$LOG" | sed -E "s/ err='I[0-9]+[^']*'//" >> "$OUT"
say "result: $ok passed, $fail failed"
