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

The core of the engine. `ContainerService` creates specs `pending`, materializes the Apple container at first start with only the `fl.docker.id` label, and recreates it when a spec edit needs it. The poller diffs runtime against observed state and suppresses intent-ledger matches; `ClientProcess.wait` and the poller feed one record-exit function so each run gets exactly one `die`. Boot resolves open ledger entries and sweeps labeled objects. Ports publish through Apple at materialization, with ephemeral ports kept in `host_ports`. `stats` and `archive` (`docker cp`) land here too. This epic also owns the extension points later epics plug into: the `NetworkLifecycle` port with a no-op implementation awaited on every start and stop path (AD-10), a hook inside the start operation before the `start` event, and the `inspect` assembly function, so networks, DNS, volumes, logs and restart add behavior without editing the same lifecycle code.

## Outcome

A developer runs `docker run -d -p 8080:80 nginx`, sees it in `docker ps`, reaches it on localhost, stops and removes it, and every step shows once on `docker events` (parent R5; R2 run, ps, inspect, stop, rm part).

## Done when

- `docker run`, `ps`, `inspect`, `stop`, `kill`, `rm`, `wait`, `rename`, `pause`, `unpause` work on 1.7.1 with Docker's output shapes (R2, R5).
- `-p` and `-P` publish ports reachable from the host; a conflicting port returns Docker's error; `inspect` reports the bindings (AD-19).
- `docker stats --no-stream` and `docker cp` in both directions work (R5).
- Killing a container's VM outside fruitlocker yields exactly one `die` on `/events`; a daemon restart with containers running loses no exit and adopts or sweeps every labeled object (AD-6, AD-16).
- Apple-native containers never appear in `docker ps -a` (AD-4).
- `--network container:<id>`, `--ipc host` and `--pid container:<id>` return 400 naming the option (R13, container create part).
- Every start and stop path awaits the `NetworkLifecycle` hooks, tested with a fake that records calls (AD-10, port only).
- Compatibility tests for run, ps, inspect, stop and rm pass on the local runner.
- Delivered: the change is in a signed build Josh runs on his Mac against Apple `container` 1.7.1, with core tests green in CI.

## Boundaries

- Owns: `ContainerService`, container endpoints, the poller, intent ledger, record-exit function, boot reconcile steps 5, 6 and 10, `host_ports`, container to image reference rows, the `NetworkLifecycle` port with a no-op, the start-operation hook and the `inspect` assembly function.
- Not here: network objects and attachments (epic-networks), volume references (epic-volumes), the real `NetworkController` (epic-compose-dns), restart and health columns (epic-restart-health), logs, attach and exec (epic-logs-exec).
- Handoff: epic-networks, epic-compose-dns, epic-volumes, epic-logs-exec and epic-restart-health plug into the extension points above.
- Must not change: `ImageService` owns image events; containers only add the reference row that blocks image deletion.

## References

- parent: _bmad-output/initiative-fruitlocker-v1/initiative-fruitlocker-v1.md, section Requirements (R2, R5, R10, R13)
- architecture: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md, AD-3, AD-4 (container IDs, join key, hostname), AD-6 (poller, intent ledger, record-exit), AD-7, AD-10 (NetworkLifecycle port only), AD-11 (container fields), AD-16 (steps 5, 6 and 10), AD-19

## Notes

- Assumption: [CONFIRMED by Josh 2026-11-14] `stats` and `archive` sit here rather than in epic-logs-exec, since neither waits on #12.
- Assumption: [CONFIRMED by Josh 2026-11-14] This epic will likely run past twelve stories; split it when its stories are planned (for example materialization and lifecycle, then poller and boot reconcile, then ports, stats and cp).
- Waits on epic-images because: `docker run` needs a pulled image and its ID.
- Assumption: [CONFIRMED by Josh 2026-11-14] To keep epics 5 to 8 from colliding in `ContainerService`, this epic owns the lifecycle extension points and later epics only plug in, rather than serializing epics 5 to 8. Josh to confirm.
