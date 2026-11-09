---
title: "Addendum: fruitlocker product brief"
created: 2026-11-09
updated: 2026-11-09
---

# Addendum

Depth that belongs downstream (PRD, architecture) or earned a place but doesn't fit the brief.

## v1 wedge: options considered

| Ecosystem | What it needs from the API | Why it was or wasn't first |
|---|---|---|
| **docker CLI + Compose (chosen)** | The full core: build, networks, volumes, labels and filters, events, attach/exec hijack, and service DNS between containers | Biggest audience and payoff. Longest path, because it hits the hardest parts (networking across VMs, events without upstream support). Chosen so the rest builds on it. |
| Dev Containers | build, exec/attach with hijack and TTY, archive, mounts, labels. Mostly one container, though Compose-based devcontainers are common | Narrower and demos well. Largely covered once Compose works. |
| Testcontainers | create/start/logs/wait/exec, port mapping, and Ryuk mounting the socket inside a container (Docker-outside-of-Docker through a facade socket) | Smallest surface, and its own test suites can score compatibility. Good candidate for the next target. |

## Build vs join (settled 2026-11-09, recorded for context)

- **Build our own engine and app (chosen).** A GUI alone would duplicate Orchard (MIT, 1,754 stars). An app that owns the socket is the open space.
- **Build on Socktainer and contribute upstream.** Rejected. Socktainer (Apache-2.0, 631 stars, targets Engine API v1.51) is prior art and a reference only.
- **Fork Socktainer.** Rejected for the same reason.
- **Language: Swift.** It shares Containerization and `ContainerAPIClient`, and matches every serious competitor. Go, for its Moby API types, was considered in recon.

## Technical constraints for architecture

- Seam: `ContainerAPIClient` from apple/container 1.7.1's Package.swift (one of its 25 libraries; pins Containerization 0.54.0), over XPC to `com.apple.container.apiserver`. Shown to work from an unsandboxed, same-user app. Not shown to work sandboxed.
- Compatibility promises: the apiserver XPC API is stable within 1.x. The CLI is only "generally" backward compatible. Private helpers carry no promise. App data is forward-compatible within a major only.
- CLI JSON shapes changed at 1.0 (for example, `inspect` state moved to `status.state`). Don't build on CLI scraping.
- Upstream blockers to watch: events (#484), restart policies (#2142), healthchecks (#1918), concurrent read-only named volumes (#889), Compose (#1846).
- Minimum Engine API list and sources: `~/Ops/Vault/projects/fruitlocker/recon/run/gap/report.md`.

## Parked roadmap

- **After v1:** Dev Containers and Testcontainers as certified targets, with Testcontainers' own suites as the scoring harness.
- **Not ruled out:** Kubernetes (kiac and Orchard already cover it) and an extensions system.
