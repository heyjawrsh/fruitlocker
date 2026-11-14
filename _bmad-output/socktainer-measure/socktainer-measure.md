---
title: Socktainer Compose pass rate
date: 2026-11-14
issue: heyjawrsh/fruitlocker#22
---

# Socktainer Compose pass rate

**Result: 16 of 22 (73%).** Socktainer `main` (fb8f893), container 1.7.1, macOS 26.7.3. This clears the "about 70%" bar in open-questions-v1 §3. The other join condition, maintainer interest, is pending on socktainer/socktainer#521.

## Method

- Samples: `docker/awesome-compose` at 30f4b7f, 31 HTTP samples. Left out: pihole (:53), wireguard, minecraft, plex, wasmedge-*, elasticsearch-logstash-kibana, aspnet-mssql.
- Pass means `up -d --build --wait` succeeds, the entry port answers HTTP 2xx/3xx within 120s, and `down -v` succeeds.
- Docker Desktop is the control. 22 of 31 pass there; the 9 that don't are sample rot (old werkzeug, a crates manifest, postgres 18 data path, Traefik's Docker client too old for API 1.44+, two broken builds). Only the 22 count.
- Harness and raw tables: `spikes/22-socktainer-measure/`.

## Failures

| Samples | Cause |
|---|---|
| nginx-aspnet-mysql, nginx-golang-mysql, react-express-mysql, react-java-mysql, sparkjava-mysql | Compose `secrets:` bind one file. Create fails with `path ... is not a directory`; the client sees only "Something went wrong." |
| gitea-postgres | Socktainer pulled a fresh `postgres:alpine` (18, new data path). Docker Desktop had an older cached tag. Drift, not Socktainer. |

Without the drift case it's 16 of 21 (76%).

## What else it showed

- **Builds work without `/grpc`.** buildx falls back to a `docker-container` builder (`buildx_buildkit_default`) running inside Socktainer, then loads images through `/images/load`. Slower first build, no user setup.
- **Single-file bind mounts are an Apple limit.** fruitlocker hits it too, and the spine doesn't cover it yet (#26).
- **The error surfacing proves the "fail loudly" point.** The right error exists in Socktainer's log and never reaches the user.
