---
title: "Addendum: fruitlocker product brief"
created: 2026-11-09
updated: 2026-11-09
---

# Addendum

Supporting detail for the PRD and architecture that doesn't fit in the brief.

## v1 wedge: options considered

| Ecosystem | What it needs from the API | Why it was or wasn't first |
|---|---|---|
| **docker CLI + Compose (chosen)** | The full core: build, networks, volumes, labels and filters, events, attach/exec hijack, Compose service networking | Biggest audience and payoff. Longest path, because it hits the hardest parts: networking across VMs, and events without upstream support. Chosen so the rest builds on it. |
| Dev Containers | build, exec/attach with hijack and TTY, archive, mounts, labels. Mostly one container, though Compose-based devcontainers are common. | Narrower and demos well. Largely covered once Compose works. |
| Testcontainers | create/start/logs/wait/exec, port mapping, and Ryuk mounting the socket inside a container (Docker-outside-of-Docker through a facade socket) | Smallest surface, and its own test suites can score compatibility. |

## Build vs join (decided 2026-11-09)

- **Build our own engine and app (chosen).** A GUI alone would duplicate Orchard (MIT, 1,754 stars). An app that owns the socket is the open space.
- **Build on Socktainer and contribute upstream.** Rejected. Socktainer (Apache-2.0, 631 stars, targets Engine API v1.51) stays prior art and a reference.
- **Fork Socktainer.** Rejected.
- The rationale for rejecting both Socktainer options wasn't captured. TODO: Josh to add one line.
- **Language: Swift.** It shares Containerization and `ContainerAPIClient`, and matches every serious competitor. Recon also weighed Go, for its Moby API types.

## Minimum Engine API for v1

- `/_ping`, `/version`, `/info` with version negotiation
- Containers: create, start, stop, wait, logs, stats, archive, and attach and exec with HTTP hijacking and TTY resize
- Images: pull, push, tag, load, save, and `/build` with BuildKit progress
- Networks and volumes, with labels and filters
- `/events`
- `/auth`

Full list and sources are in the private recon notes: `~/Ops/Vault/projects/fruitlocker/recon/run/gap/report.md`.

## Technical constraints for architecture

- **Seam.** `ContainerAPIClient`, a library in apple/container 1.7.1 that pins Containerization 0.54.0. It talks XPC to `container-apiserver` (Mach service `com.apple.container.apiserver`). It's been shown to work from an unsandboxed, same-user app, but not from a sandboxed one.
- **Compatibility promises.** The apiserver XPC API is stable within 1.x. The CLI is only "generally" backward compatible. Private helpers carry no promise. App data is forward-compatible within a major only.
- **CLI JSON.** Output shapes changed at 1.0 (for example, `inspect` state moved to `status.state`). Don't build on CLI scraping.
- **Upstream issues to watch:**
  - events: apple/container#484
  - restart policies: apple/container#2142
  - healthchecks: apple/container#1918
  - concurrent read-only named volumes: apple/container#889
  - Compose: apple/container#1846

## Research limits

Web search failed in the recon landscape lane, so paid and non-GitHub competitors are under-sampled.

## Parked roadmap

- **Likely next:** Dev Containers and Testcontainers as certified targets. Which goes first isn't decided. Testcontainers' own suites could serve as the scoring harness.
- **Not ruled out:** Kubernetes (kiac covers it, and Orchard has k8s support) and an extensions system.
