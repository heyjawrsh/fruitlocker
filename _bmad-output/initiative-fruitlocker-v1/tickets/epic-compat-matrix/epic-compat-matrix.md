---
id: 11
type: epic
title: "Public compatibility matrix"
parent: initiative-fruitlocker-v1
covers: ["R1", "R2", "R3"]
sources: []
companions: []
after: []
refined: false
risk: medium
---

# Public compatibility matrix

## Description

Turns the local compatibility runner into the public v1 gate. A pinned set of public Compose sample projects and a test per gate command run on a self-hosted Apple silicon runner against the pinned Apple `container` version, never on fork-PR code, with an image smoke test per Apple release. CI publishes the matrix and the pass rate.

## Outcome

Anyone can read which Compose samples and commands pass on which Apple `container` version, and the rate is 80% or better (parent R1, R3; R2 coverage across commands).

## Done when

- The pinned Compose sample set and its pass rate are published by CI; the rate is 80% or better with `up`, `down`, `logs`, `exec` (R1, R3).
- Every R2 gate command has a test in the matrix, passing, or `build` is marked per Josh's amended gate (R2).
- The self-hosted runner never runs fork-PR code (spine Deployment).
- An image smoke test runs per Apple release (AD-12).
- Delivered: the change is in a signed build Josh runs on his Mac against Apple `container` 1.7.1, with core tests green in CI.

## Boundaries

- Owns: `Compat/` sample pins, the matrix runner on the self-hosted runner, the public matrix output.
- Not here: the local runner (epic-engine-foundation) and each epic's own compatibility tests.

## References

- parent: _bmad-output/initiative-fruitlocker-v1/initiative-fruitlocker-v1.md, section Requirements (R1, R2, R3)
- architecture: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md, AD-12 (image smoke test per Apple release); spine Deployment, CI

## Notes

- Open question: Who hosts the self-hosted Apple silicon runner? Josh decides before this epic starts (spine Deferred).
- Assumption: [CONFIRMED by Josh 2026-11-14] Which public Compose samples are pinned is chosen when this epic is refined; earlier epics pick one sample each for their own checks.
- Waits on epic-compose-dns, epic-volumes, epic-logs-exec, epic-restart-health and epic-build because: the samples need names, volumes, logs, exec, healthchecks and build to pass.
