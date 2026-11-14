---
id: 10
type: epic
title: "Native app runs the engine"
parent: initiative-fruitlocker-v1
covers: ["R14", "R15", "R16"]
sources: []
companions: []
after: []
refined: false
risk: medium
---

# Native app runs the engine

## Description

The SwiftUI menu-bar app is UI only. It controls the daemon process only through `SMAppService` and reads and writes engine state only over the socket: the Engine API for Docker objects and `/fruitlocker/v1/*` for engine-only concerns. It shows containers, images, volumes and networks grouped by Compose project, streams logs and opens a shell through the same core service the CLI uses, surfaces warnings, and on first run creates and switches to a `fruitlocker` Docker context, recording the previous one for undo. It learns whether Apple `container` is installed from the daemon's `/fruitlocker/v1` status (the app never contacts Apple, AD-2) and guides its install.

## Outcome

A developer opens the app, sees their Compose projects and their state, tails a service's logs, opens a shell, and can undo the context switch (parent R14, R15, R16).

## Done when

- The menu-bar app starts, stops and restarts the engine through `SMAppService` and shows its state from `/fruitlocker/v1` (R14, AD-13).
- Containers, images, volumes and networks show grouped by Compose project and update from `/events` (R14).
- The log view matches `docker logs` for the same container, and the shell is an interactive exec (R15, AD-20).
- First run creates the `fruitlocker` context and switches to it; undo restores the recorded context; no other context or `DOCKER_HOST` is touched (R16, AD-15).
- With Apple `container` missing, the app says so and links Apple's signed pkg.
- Delivered: the change is in a signed build Josh runs on his Mac against Apple `container` 1.7.1, with core tests green in CI.

## Boundaries

- Owns: `App/` Xcode project UI, context handling, prerequisite guidance.
- Not here: the uninstall path and Sparkle (epic-release); any second app to daemon channel (forbidden by AD-13).
- Touch point: the user's Docker contexts, add and switch only; owner: this epic.

## References

- parent: _bmad-output/initiative-fruitlocker-v1/initiative-fruitlocker-v1.md, section Requirements (R14, R15, R16)
- architecture: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md, AD-1 (UI only), AD-13, AD-15

## Notes

- Waits on epic-logs-exec because: the log view and shell reuse its one log source and exec.
- Waits on epic-networks and epic-volumes because: the views need their endpoints.
- Assumption: [ASSUMPTION] Run `bmad-ux` on this epic before its stories are planned; the spine defers app UI structure to it.
- Assumption: [ASSUMPTION] The app shell from epic-engine-foundation (signing, LaunchAgent registration) is reused here, not rebuilt.
