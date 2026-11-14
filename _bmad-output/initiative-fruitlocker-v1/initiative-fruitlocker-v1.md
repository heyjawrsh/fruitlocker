---
type: initiative
title: "fruitlocker v1: docker and Compose run unchanged on Apple container"
sources:
  - _bmad-output/brief-fruitlocker/brief-fruitlocker.md
  - _bmad-output/brief-fruitlocker/addendum.md
companions:
  - _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md
after: []
risk: high
---

# fruitlocker v1: docker and Compose run unchanged on Apple container

## Description

A Mac developer installs one signed app and their existing `docker` and `docker compose` workflow runs on Apple's `container` 1.7.1, one VM per container, with nothing changed. The engine is a Swift daemon serving the Docker Engine API on a Unix socket, plus a privileged DNS helper and a native macOS app. Scope comes from the brief and addendum; how it is built is settled in the architecture spine (AD-1 to AD-21), which every epic adopts.

## Outcome

A professional developer on an Apple silicon Mac switches their Docker context to fruitlocker and forgets it is there; the signal is the published compatibility pass rate (brief Success Criteria), with stars, outside contributors, cask installs and triage time as the adoption read at six months.

## Requirements

- R1 (brief Success Criteria, Compatibility): a pinned set of public Compose sample projects runs unchanged with `docker compose up`, `down`, `logs` and `exec`; the pass rate is published and is at least 80%.
- R2 (brief Success Criteria, Compatibility): the core docker CLI commands work against fruitlocker: run, ps, logs, exec -it, build, pull, push, images, volume, network, inspect, stop, rm; each has a passing compatibility test.
- R3 (brief Success Criteria, Compatibility): CI generates a public compatibility matrix against the pinned Apple `container` version.
- R4 (addendum Minimum Engine API): the daemon serves `/_ping`, `/version` and `/info` with API version negotiation on a local Unix socket.
- R5 (addendum Minimum Engine API): containers support create, start, stop, wait, stats and archive through the Engine API.
- R6 (addendum Minimum Engine API): container logs, attach and exec work, with HTTP hijacking and TTY resize.
- R7 (addendum Minimum Engine API): images support pull, push, tag, load and save, and `/auth` validates registry credentials.
- R8 (addendum Minimum Engine API): `/build` works with BuildKit progress; subject to the build spike outcome, which may amend the gate.
- R9 (addendum Minimum Engine API): networks and volumes work, with labels and filters.
- R10 (addendum Minimum Engine API; brief The engine): `/events` streams container, image, network and volume state changes, built by polling Apple until apple/container#484 lands.
- R11 (brief The engine): restart policies and healthchecks behave as Docker does, though Apple's runtime has neither.
- R12 (brief The engine): containers on a Compose network reach each other by service name and alias over DNS.
- R13 (brief Scope, Out by constraint): host networking, `container:` network mode, shared PID or IPC, Docker-in-Docker, host privileged mode and device passthrough each fail with a clear error, never silently.
- R14 (brief The app): a native SwiftUI app with a menu-bar presence starts and stops the engine and shows containers, images, volumes and networks grouped by Compose project.
- R15 (brief The app): the app streams a container's logs and opens a shell in it.
- R16 (brief The app): on first run the app points the user's docker context at fruitlocker's socket, with an undo.
- R17 (brief Scope, In v1): fruitlocker ships as a signed, notarized direct download and a Homebrew cask.
- R18 (brief The experience): a user installs the signed app, opens it, runs `docker compose up` in an existing project, and it works.

## Constraints

- Apple silicon on macOS 26 and later only; no Intel, Linux or Windows hosts (brief Scope, Platforms).
- Built on the `ContainerAPIClient` XPC seam at apple/container 1.7.1; no parsing of `container` CLI output (brief What Makes This Different; addendum Technical constraints).
- Apache-2.0, and every dependency Apache-2.0-compatible (brief Scope, In v1).
- No Mac App Store or sandboxed distribution; no paid tier, accounts, telemetry or hosted services (brief Scope, Out of v1).
- No Docker trademarks in the name or branding; "Docker-compatible" is the most it says (brief Scope, Out of v1).
- The v1 architecture spine (AD-1 to AD-21) is binding; epics implement it and never re-decide it (architecture-fruitlocker.md).

## Done when

- The pinned Compose sample set passes at 80% or better with `up`, `down`, `logs` and `exec`, and the rate is on the public matrix (R1, R3).
- Every v1 gate command in R2 has a passing compatibility test on the pinned Apple `container` 1.7.1, or Josh has amended the gate for `build` after #11.
- A notarized build installs from the direct download and from the Homebrew cask, and Sparkle updates it in place with both services still approved (R17).
- On a clean Mac with Apple `container` installed, Josh installs the app, opens it, runs `docker compose up` in an existing project and it works (R18).
- Each unsupported option in R13 returns a Docker-shaped 400 naming the option.

## Boundaries

- Out of v1: Dev Containers and Testcontainers as certified targets, Kubernetes, an extensions system, a Testcontainers facade socket (brief After v1; spine Deferred).
- Out of v1: Apple-native objects in Docker views; Apple alias DNS (spine AD-4, AD-9).
- Out of v1: Mac App Store, sandboxing, telemetry, accounts (brief Scope, Out of v1).
- Touch point: Apple `container` pkg and `container-apiserver`, a user-installed prerequisite consumed over XPC; owner: epic-engine-foundation.
- Touch point: container registries, consumed for pull, push and `/auth`; owner: epic-images.
- Touch point: mDNSResponder's `udp4 *:53` and vmnet bridges, observed only; owner: epic-compose-dns.
- Touch point: the user's Docker contexts, edited only to add and switch to `fruitlocker`; owner: epic-app.
- Touch point: Sparkle appcast host and the Homebrew cask tap, configured only; owner: epic-release.
- Tracer path: `docker version` on the socket (engine-foundation), then `docker pull` (images), `docker run` (containers), a user network (networks), name resolution between two services (compose-dns), then the full Compose samples on the matrix (compat-matrix) from a notarized install (release).

## References

- brief: _bmad-output/brief-fruitlocker/brief-fruitlocker.md, sections Success Criteria, Scope, The Solution
- addendum: _bmad-output/brief-fruitlocker/addendum.md, sections Minimum Engine API for v1, Technical constraints for architecture
- architecture: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md, all ADs, Consistency Conventions, Deployment & environments, Deferred
- spike: _bmad-output/spike-compose-dns/spike-compose-dns.md (folded into AD-9, AD-21)
- spike: _bmad-output/spike-gateway-dns/spike-gateway-dns.md (folded into AD-10)

## Notes

- Assumption: [ASSUMPTION] v1 is one initiative with epics, not a parent over several initiatives: one product, one solo maintainer, one release.
- Assumption: [ASSUMPTION] Adoption targets (stars, contributors, cask installs, triage time) are the Outcome's signal, not Requirements lines: no epic can build them.
- Open question: Who hosts the self-hosted Apple silicon runner for the compatibility matrix? Josh decides; blocks the public matrix (spine Deferred).
- Open question: If the build spike (#11) fails, Josh amends the v1 gate for `build`; epic-build waits on that call (spine Deferred).
- Decision: 2026-11-14 Sliced by "one source capability per epic, delivered together"; module boundaries are not epic boundaries because everything ships in one bundle (slice.md rule).
- Decision: 2026-11-14 [ASSUMPTION] Networks and Compose DNS are separate epics: #14 blocks only `FLDNS`, and plain user networks are usable by Compose before names resolve.
- Decision: 2026-11-14 [ASSUMPTION] Images come before containers: `docker run` needs a pulled image, so the images epic is the first one with Docker objects.
- Decision: 2026-11-14 [ASSUMPTION] The opening epic carries the platform baseline: package scaffold, CI on hosted macOS against fakes, a Developer ID signed bundle that registers the daemon LaunchAgent with `SMAppService`, and a local compatibility runner. Notarization, Sparkle, cask and uninstall wait for epic-release.
- Decision: 2026-11-14 [ASSUMPTION] `EventBus` and the `/events` endpoint land in the opening epic; each later epic adds its own emitters from the Conventions table. The poller, intent ledger and record-exit land with containers.
- Decision: 2026-11-14 [ASSUMPTION] Container `stats` and `archive` sit in epic-containers, not epic-logs-exec, because neither waits on the stdio spike (#12).
- Decision: 2026-11-14 [ASSUMPTION] Logs and exec come before restart and health: `logs` and `exec` are v1 gate commands for Compose, restart and health are not named in the gate.
- Decision: 2026-11-14 [ASSUMPTION] The public matrix and self-hosted runner are their own epic near the end; earlier epics run their integrated checks on the local compatibility runner on Josh's Mac.
- Decision: 2026-11-14 [ASSUMPTION] Tree check found epics 5 to 8 would collide in `ContainerService` start and stop paths. epic-containers owns the extension points (`NetworkLifecycle` no-op, start-operation hook, `inspect` assembly) instead of serializing 5 to 8. Also added: volumes after networks, restart-health after logs-exec, logs-exec and restart-health after networks, build after containers.
- Open question: How does the field table spot Docker-in-Docker beyond `--privileged` (for example a mounted `docker.sock`) for R13? Settled when epic-engine-foundation is refined.
- Decision: 2026-11-14 Spine already settles shared decisions; no `bmad-architecture` run and no opening-epic decision stories. App UI structure goes to `bmad-ux` when epic-app is refined (spine Deferred).
