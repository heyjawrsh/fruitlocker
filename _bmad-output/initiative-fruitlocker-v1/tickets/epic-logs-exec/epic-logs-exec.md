---
id: 7
type: epic
title: "Logs, attach and exec"
parent: initiative-fruitlocker-v1
covers: ["R2", "R6", "R10"]
sources: []
companions: []
after: []
refined: false
risk: high
---

# Logs, attach and exec

## Description

Every consumer of container output (`docker logs`, Compose `logs`, attach, later the app's log view) reads one source through one core service, chosen by #12, and containers keep running and writing across a daemon restart. Attach and exec use the decided hijack pattern: a custom Hummingbird `ServerChildChannel` that reads the head and full body, writes `101` or `200`, then strips the HTTP codecs. TTY resize works.

## Outcome

A developer runs `docker compose logs -f` and `docker exec -it <svc> sh` and they behave as on Docker (parent R6; R2 logs, exec -it part).

## Done when

- `docker logs`, `logs -f`, `--since`, `--timestamps` work and match what the app will show (R6, AD-20).
- `docker exec -it <c> sh` gives an interactive shell with working resize; exec with a body and stdin half-close works (spine Deferred, hijack).
- `docker attach` and `docker run -it` work (R6).
- After a daemon restart, a running container keeps writing and `docker logs` shows output from before and after (AD-20).
- Compose `logs` and `exec` pass on a pinned sample on the local runner (R1 inputs).
- Delivered: the change is in a signed build Josh runs on his Mac against Apple `container` 1.7.1, with core tests green in CI.

## Boundaries

- Owns: the log source and its core service, the hijack child channel, attach, exec, resize endpoints, `exec_create`/`exec_start`/`exec_die` events.
- Not here: the app's log view and shell (epic-app reuses this service over the socket).

## References

- parent: _bmad-output/initiative-fruitlocker-v1/initiative-fruitlocker-v1.md, section Requirements (R2, R6, R10)
- architecture: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md, AD-6 (attach, exec emitters), AD-20; spine Deferred: hijack pattern

## Notes

- Waits on #12 (stdio and log ownership spike) because: it decides AD-20's source before any logs or attach work begins.
- Waits on epic-containers because: logs and exec need running containers and `ContainerService`.
