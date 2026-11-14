---
id: 12
type: epic
title: "Signed release, updates and uninstall"
parent: initiative-fruitlocker-v1
covers: ["R17", "R18"]
sources: []
companions: []
after: []
refined: false
risk: high
---

# Signed release, updates and uninstall

## Description

Ships v1. The bundle is notarized and published as a direct download that Sparkle 2.10.1 updates in place, and as a Homebrew cask pointing at the same build. #15 proves that `SMAppService` approval survives an in-place update and that the agent and daemon restart onto the new binary. One uninstall path, in the app menu and the cask's `zap`, restores the recorded Docker context, unregisters both services and asks before deleting labeled Apple objects, keeping user data by default.

## Outcome

A developer installs fruitlocker from the website or `brew install --cask`, it updates itself, and uninstall leaves their Docker setup as it was (parent R17, R18).

## Done when

- A notarized build installs from the direct download and from the Homebrew cask (R17).
- A Sparkle update from one build to the next keeps both services approved and running the new binary (AD-1, #15).
- Uninstall from the app menu and from `brew uninstall --zap` restores the previous Docker context and unregisters both services; labeled Apple objects stay unless the user says delete (AD-15).
- On a clean Mac with Apple `container` installed, Josh installs, opens the app, runs `docker compose up` in an existing project and it works (R18).
- Delivered: the change is in a signed build Josh runs on his Mac against Apple `container` 1.7.1, with core tests green in CI.

## Boundaries

- Owns: notarization, Sparkle appcast, the Homebrew cask, the uninstall path, release CI.
- Not here: Developer ID signing setup (epic-engine-foundation).
- Touch point: Sparkle appcast host and the Homebrew cask tap, configured only; owner: this epic.

## References

- parent: _bmad-output/initiative-fruitlocker-v1/initiative-fruitlocker-v1.md, section Requirements (R17, R18)
- architecture: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md, AD-1 (one bundle, services re-registered on update), AD-15 (uninstall restores context); spine Deployment

## Notes

- Waits on #15 (Sparkle plus SMAppService spike) because: it blocks the first release.
- Waits on epic-app and epic-compat-matrix because: the release ships the app and gates on a passing matrix.
- Assumption: [ASSUMPTION] R18's clean-Mac check is the release gate and lives here, not in epic-compat-matrix, because it needs the notarized install.
