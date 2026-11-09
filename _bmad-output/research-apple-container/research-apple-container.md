---
type: research
slug: apple-container
date: 2026-11-09
sources:
  - ~/Ops/Vault/projects/fruitlocker/recon/run/surface/report.md
  - ~/Ops/Vault/projects/fruitlocker/recon/run/gap/report.md
  - ~/Ops/Vault/projects/fruitlocker/recon/run/landscape/report.md
  - ~/Ops/Vault/projects/fruitlocker/recon/run/proof/proof.md
run: fruitlocker-recon-20261109T085603Z-p63854 (Ringer, 4/4 PASS)
issue: https://github.com/heyjawrsh/fruitlocker/issues/1
---

# Research: Apple container as a Docker Desktop foundation

## Verdict

A generic open-source GUI for Apple container is already crowded. The open space is **Docker ecosystem compatibility**: one signed, supported app that gives `docker`, `docker compose`, Dev Containers and Testcontainers a working `docker.sock` on Apple's runtime, with a GUI on top. Nobody ships that today.

## What we know (verified)

**The foundation is real and moving fast.**
- apple/container is Apache-2.0, 51k stars, and released **1.7.1 on 2026-11-06**. Containerization (the Swift package underneath) is also Apache-2.0.
- Requires Apple silicon and macOS 26. Each container runs in its own lightweight VM.
- Architecture: `container` CLI → `container-apiserver` (launchd Mach service, XPC) → helpers for images, vmnet networking, and one runtime helper per container. Guest control is gRPC over vsock; builds use a BuildKit builder VM.

**It can be driven by a wrapper.** The proof lane ran a script on this Mac, unsandboxed. It started the services non-interactively (`system start --enable-kernel-install`), ran alpine as a named container, parsed `container inspect` JSON, found a marker in the logs, removed the container, and restored the service state. JSON output exists for list, stats, inspect, status, and most `list` commands; `run`, `exec`, `logs`, `build`, pull and push are plain text.

**There is no Docker Engine API.** Docker Compose's maintainers say Compose needs the Moby API, which Apple does not expose. Everything in the Docker ecosystem (Compose, Dev Containers, Testcontainers, IDE and CI integrations) keys off `docker.sock`.

## The gap a compatibility layer must close

Minimum Engine API for unchanged tools: `/_ping`, `/version`, `/info` with version negotiation; containers (create, start, stop, wait, logs, stats, attach and exec with HTTP hijacking and TTY resize, archive); images (pull, push, tag, load, save, `/build` with BuildKit progress); networks and volumes with labels and filters; `/events`; `/auth`. Full list and sources in the gap report.

Things that cannot map literally onto one-VM-per-container:
- `--network host`, `network_mode: container:<id>`, shared PID/IPC namespaces, and localhost sidecars.
- `--privileged`, devices and capabilities only affect the guest VM.
- Docker-in-Docker. Docker-outside-of-Docker through a facade socket is feasible.

## Landscape

| Project | Lane | License | Stars | Note |
|---|---|---|---|---|
| Orchard (andrew-waters/orchard) | Native SwiftUI GUI, XPC-native, Compose, k8s, menu bar | MIT | 1,754 | Direct hit for "GUI". Says it "does not expose a Docker-compatible API socket." |
| Socktainer | Headless Docker API daemon | Apache-2.0 | 631 | Proves demand. Self-described **partial** (Engine API v1.51 target, gaps in pause, commit, network connect, restart policies). Podman Desktop's Apple container extension runs on it. |
| Container-Compose | docker-compose.yml runner | Apache-2.0 | 997 | "(limited) Docker Compose support" |
| Container Desktop, contained-app, AppleContainerDesktop, iContainer, Crane, others | GUIs | mixed | 30 to 870 | Long tail; several unlicensed or stale |
| kiac | Kubernetes on Apple container | MIT | 390 | Kubernetes is not a wedge |
| OrbStack, Docker Desktop, Podman Desktop, Rancher Desktop, Colima, Lima | Established tools | mixed | | None run on Apple container natively, except Podman via Socktainer |

Stars, licenses and release dates spot-checked with `gh api` on 2026-11-09.

## Update: container 1.7.1 (refresh run fruitlocker-recon-20261109T093019Z-p95622)

This Mac was upgraded to 1.7.1 (clean install). The 0.10 findings above about API instability are superseded:

- **Stable seam.** 1.x promises the `container-apiserver` XPC API stays forward and backward compatible within a major version. The CLI is "generally" backward compatible. Private helpers carry no promise. App data is forward-compatible within a major only.
- **Linkable client.** 1.7.1's Package.swift publishes 25 libraries, including `ContainerAPIClient`, and pins Containerization 0.54.0. An unsandboxed, same-user Swift app can call `ContainerClient()` over XPC to `com.apple.container.apiserver`. A sandboxed or App Store app was not shown to work.
- **No Compose.** Apple ships none (issue #1846 is still open). `container cluster` is an experimental Kubernetes plugin with no compatibility guarantee.
- **JSON broke at 1.0.** Output shapes were normalized at 1.0 (for example, `inspect` state moved to `status.state`), so 0.10 parsers can't be reused. 1.x adds YAML and TOML output too.
- **Open blockers for Docker parity:** restart policies (#2142), healthchecks (#1918), and an events stream (#484). Without an events stream, a daemon has to poll for state. Concurrent read-only named volumes (#889) is also open. Guest memory still isn't returned to macOS.
- **Proof on 1.7.1 passes.** No flag changes from 0.10. Only the JSON shape changed.

Implication: fruitlocker's engine can be a Swift daemon linking `ContainerAPIClient`, which gives it typed XPC and no CLI scraping. It would need its own events, restart and health layers to match Docker semantics.

## Open questions for the brief

1. **Version baseline.** Target container 1.x (≥ 1.7.1) on macOS 26, Apple silicon only. Resolved.
2. **Build vs join.** Decided 2026-11-09: build fruitlocker's own Docker Engine API daemon and native app. Socktainer is reference prior art. Socktainer (Apache-2.0) already owns the shim's foundation and Orchard (MIT) the GUI. Options: build our own engine and app; build the app on top of Socktainer and contribute upstream; or fork. This decides the whole architecture.
3. **Language.** Swift/SwiftUI matches every serious competitor and Apple's own APIs. The shim could be Swift (shares Containerization) or Go (reuses Moby API types).
4. **Coverage gap.** Web search failed in the landscape lane, so paid or non-GitHub entrants are under-sampled.
