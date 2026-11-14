---
id: 1
type: epic
title: "Engine answers on the socket"
parent: initiative-fruitlocker-v1
covers: ["R4", "R10", "R13"]
sources: []
companions: []
after: []
refined: false
risk: medium
---

# Engine answers on the socket

## Description

Stands up the platform every other epic builds on: the Swift package with the module layout and dependency rule from the spine, CI on GitHub-hosted macOS running core tests against fakes, and a Developer ID signed `fruitlocker.app` shell that registers `fruitlockerd` as a per-user LaunchAgent through `SMAppService`. The daemon binds `~/.fruitlocker/run/docker.sock` 0600 in a 0700 directory, boots in AD-16 order through step 4, bootstraps Apple's services if down, runs the 1.7.1 version gate, migrates the GRDB store, and serves `/_ping`, `/version`, `/info`, `/events` and `/fruitlocker/v1/*` status and diagnostics. The request-field table exists and rejects every R13 option with Docker's 400 shape; unimplemented endpoints return 501.

## Outcome

A contributor can install a dev build and point `docker` at the socket; `docker version` and `docker info` answer, so every later epic has a deployed engine to add to (parent R4).

## Done when

- `docker version` and `docker info` against the socket negotiate API 1.44 to 1.51 on a Mac with Apple `container` 1.7.1 (R4).
- With Apple's apiserver stopped or on an unsupported version, `/_ping`, `/version` and `/fruitlocker/v1/*` answer and every other endpoint returns 503 `fruitlocker: engine unavailable: <reason>` (AD-12).
- `docker run --network host`, `--pid host`, `--privileged` and `--device` each return 400 naming the option (R13; container create itself is 501 until epic-containers).
- `/events` streams `Type=daemon` `fl.gate` events from the `EventBus`, with `since=` served from its history buffer (R10, bus part).
- CI on GitHub-hosted macOS runs `FLCore` tests against fake ports; a local compatibility runner under `Compat/` runs one real-VM check on Josh's Mac.
- A signed dev bundle registers the daemon with `SMAppService` and it survives the app quitting (AD-1); `FRUITLOCKER_HOME` runs an isolated dev daemon.
- Delivered: the change is in a signed build Josh runs on his Mac against Apple `container` 1.7.1, with core tests green in CI.

## Boundaries

- Owns: package scaffold, CI, signing setup, socket, boot order steps 1 to 4, version gate, store and migrations framework, `EventBus`, field table, error shapes, OSLog and diagnostics export.
- Not here: any Docker object handlers (later epics), the poller and intent ledger (epic-containers), the helper LaunchDaemon (epic-compose-dns), notarization, Sparkle and cask (epic-release).
- Touch point: Apple `container` pkg and `container-apiserver`, detected and started with `container system start` exit code only (AD-2); owner: this epic.

## References

- parent: _bmad-output/initiative-fruitlocker-v1/initiative-fruitlocker-v1.md, section Requirements (R4, R10, R13)
- architecture: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md, AD-1 (daemon LaunchAgent part), AD-2, AD-6 (EventBus and /events), AD-11, AD-12 (apiserver gate), AD-13 (/fruitlocker/v1 base), AD-16 (steps 1 to 4), AD-17, AD-18

## Notes

- Assumption: [CONFIRMED by Josh 2026-11-14] Developer ID signing and `SMAppService` registration belong here, not in epic-release, because AD-9 peer checks and LaunchAgent registration need a signed bundle from the start.
- Assumption: [CONFIRMED by Josh 2026-11-14] A local compatibility runner on Josh's Mac is enough for each epic's integrated verification until epic-compat-matrix stands up the self-hosted runner.
- Assumption: [CONFIRMED by Josh 2026-11-14] Josh holds a Developer ID certificate and Team ID usable for dev signing; setup is a hitl step on the first story that needs it.
