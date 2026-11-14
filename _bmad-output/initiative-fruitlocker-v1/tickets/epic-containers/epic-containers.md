---
id: 3
type: epic
title: "Containers run, stop and report"
parent: initiative-fruitlocker-v1
covers: ["R2", "R5", "R10", "R13"]
sources: []
companions: []
after: []
refined: false
risk: high
---

# Containers run, stop and report

## Description

The core of the engine. `ContainerService` creates specs `pending`, materializes the Apple container at first start with only the `fl.docker.id` label, and recreates it when a spec edit needs it. The poller diffs runtime against observed state and suppresses intent-ledger matches; `ClientProcess.wait` and the poller feed one record-exit function so each run gets exactly one `die`. Boot resolves open ledger entries and sweeps labeled objects. Ports publish through Apple at materialization, with ephemeral ports kept in `host_ports`. `stats` and `archive` (`docker cp`) land here too.

## Outcome

A developer runs `docker run -d -p 8080:80 nginx`, sees it in `docker ps`, reaches it on localhost, stops and removes it, and every step shows once on `docker events` (parent R5; R2 run, ps, inspect, stop, rm part).

## Done when

- `docker run`, `ps`, `inspect`, `stop`, `kill`, `rm`, `wait`, `rename`, `pause`, `unpause` work on 1.7.1 with Docker's output shapes (R2, R5).
- `-p` and `-P` publish ports reachable from the host; a conflicting port returns Docker's error; `inspect` reports the bindings (AD-19).
- `docker stats --no-stream` and `docker cp` in both directions work (R5).
- Killing a container's VM outside fruitlocker yields exactly one `die` on `/events`; a daemon restart with containers running loses no exit and adopts or sweeps every labeled object (AD-6, AD-16).
- Apple-native containers never appear in `docker ps -a` (AD-4).
- Compatibility tests for run, ps, inspect, stop and rm pass on the local runner.
- Delivered: the change is in a signed build Josh runs on his Mac against Apple `container` 1.7.1, with core tests green in CI.

## Boundaries

- Owns: `ContainerService`, container endpoints, the poller, intent ledger, record-exit function, boot reconcile steps 5, 6 and 10, `host_ports`, container to image and container to volume reference rows.
- Not here: network objects and attachments (epic-networks), restart and health columns (epic-restart-health), logs, attach and exec (epic-logs-exec).
- Must not change: `ImageService` owns image events; containers only add the reference row that blocks image deletion.

## References

- parent: _bmad-output/initiative-fruitlocker-v1/initiative-fruitlocker-v1.md, section Requirements (R2, R5, R10, R13)
- architecture: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md, AD-3, AD-4 (container IDs, join key, hostname), AD-6 (poller, intent ledger, record-exit), AD-7, AD-11 (container fields), AD-16 (steps 5, 6 and 10), AD-19

## Notes

- Assumption: [ASSUMPTION] `stats` and `archive` sit here rather than in epic-logs-exec, since neither waits on #12.
- Assumption: [ASSUMPTION] This epic will likely run past twelve stories; split it when its stories are planned (for example materialization and lifecycle, then poller and boot reconcile, then ports, stats and cp).
- Waits on epic-images because: `docker run` needs a pulled image and its ID.
