---
id: 8
type: epic
title: "Restart policies and healthchecks"
parent: initiative-fruitlocker-v1
covers: ["R11", "R10"]
sources: []
companions: []
after: []
refined: false
risk: medium
---

# Restart policies and healthchecks

## Description

Two controllers in `FLCore` give Docker's behavior that Apple lacks. `RestartController` applies `no`, `on-failure[:N]`, `always` and `unless-stopped` with Docker's backoff, writes `restartCount`, and owns the only daemon-start restart path from `manuallyStopped`. `HealthController` runs healthchecks, writes health per run, emits `health_status`, and never changes run state. Actions carry `(generation, runEpoch)` and are dropped when stale.

## Outcome

A Compose project with `restart: unless-stopped` and `depends_on: condition: service_healthy` behaves as it does on Docker, across a daemon restart (parent R11).

## Done when

- Each restart policy restarts or not as Docker does after a non-zero exit, a clean exit and `docker stop` (R11).
- After a daemon restart, `always` and `unless-stopped` containers come back and manually stopped ones do not (AD-16 step 9).
- `docker inspect` shows health and its log; `/events` shows `health_status` from `HealthController` only (R10, health part).
- A Compose sample using `service_healthy` starts in order on the local runner.
- Delivered: the change is in a signed build Josh runs on his Mac against Apple `container` 1.7.1, with core tests green in CI.

## Boundaries

- Owns: `RestartController`, `HealthController`, boot steps 9 and 10 for them.
- Not here: `NetworkController` and `DNSViewController` (epic-compose-dns).
- Must not change: health never triggers a restart (AD-8).

## References

- parent: _bmad-output/initiative-fruitlocker-v1/initiative-fruitlocker-v1.md, section Requirements (R11, R10)
- architecture: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md, AD-3 (restartCount, backoff, health columns), AD-6 (health_status), AD-8, AD-16 (steps 9 and 10)

## Notes

- Waits on epic-containers because: it needs observed state, `runEpoch`, generations and the record-exit function.
- Waits on epic-logs-exec because: a policy restart goes through the start path that wires the AD-20 log source, so one container keeps one log across restarts.
- Waits on epic-networks because: the `service_healthy` Compose sample needs its project network.
