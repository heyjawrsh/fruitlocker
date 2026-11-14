---
title: "Product Brief: fruitlocker"
status: final
created: 2026-11-09
updated: 2026-11-09
inputs:
  - _bmad-output/research-apple-container/research-apple-container.md
issue: https://github.com/heyjawrsh/fruitlocker/issues/3
---

# Product Brief: fruitlocker

## Executive Summary

fruitlocker is an open-source, Docker-compatible container app for Apple silicon Macs. It runs on Apple's own `container` runtime instead of a Linux VM shared by every container. It has two parts: a Swift daemon that serves the Docker Engine API on a local socket, and a native macOS app on top of it.

Apple's `container` is on 1.7.1, released 2026-11-06. It's Apache-2.0, maintained by Apple, and puts each container in its own lightweight VM. But it has no Docker Engine API, and the whole Docker ecosystem (the `docker` CLI, Compose, Dev Containers, Testcontainers, IDE and CI integrations) expects `docker.sock`. So today a Mac developer can use Apple's runtime or their existing tools, but not both.

v1 closes that gap for the most common workflow: `docker` and `docker compose` against an ordinary `compose.yaml`, with nothing changed. Nobody ships that today. The timing works because 1.x ships `ContainerAPIClient`, a supported Swift client for Apple's XPC API.

## The Problem

A developer on an M-series Mac runs a local stack every day: an app, Postgres, Redis, maybe a worker, all in one `compose.yaml`. Their options:

- **Stay on Docker Desktop, OrbStack, Colima or Podman.** These work, but they don't run on Apple's runtime. Some users want off them for cost, licensing, resource use or plain preference for Apple's stack.
- **Use Apple `container` directly.** Everything has to be rewritten as `container` commands. Apple ships no Compose (apple/container#1846 is still open). The third-party Container-Compose describes itself as "limited."
- **Use Socktainer.** It serves a Docker-compatible socket on Apple's runtime, but it's headless and calls itself partial, with gaps in pause, commit, network connect and restart policies.
- **Use a GUI like Orchard.** It's polished, but it says outright that it "does not expose a Docker-compatible API socket," so `docker compose` still doesn't work.

What it costs them: either they keep two container stacks, or they give up Apple's runtime for anything that touches Compose.

## The Solution

**The engine.** A Swift daemon that links `ContainerAPIClient` and talks over XPC to Apple's `container-apiserver` (Mach service `com.apple.container.apiserver`). It serves the Docker Engine API on a Unix socket. It also adds what Apple doesn't have yet but Compose expects:
- an events stream, built by polling until apple/container#484 lands
- restart policies (apple/container#2142)
- healthchecks (apple/container#1918)
- Compose service networking: service names, aliases and DNS between containers

**The app.** A native SwiftUI macOS app with a menu-bar presence. It starts and stops the engine, and shows containers, images, volumes and networks grouped by Compose project. It streams logs and opens a shell. On first run it points the user's `docker` context at fruitlocker's socket, with an undo.

**The experience.** Install the signed app, open it, run `docker compose up` in an existing project, and it works.

## What Makes This Different

- **Socket and app in one signed package, on Apple's runtime.** Each alternative above has one half or neither.
- **Built on the supported seam.** It runs on the 1.x XPC client API, which Apple promises stays compatible within the major version. It doesn't scrape CLI output, whose JSON shapes already changed once at 1.0.
- **Compatibility is the product.** Success is measured by real Compose files running unchanged, and a public compatibility matrix says what works and what doesn't.

There's no technical moat. Socktainer could close its gaps, or Apple could ship Compose or an Engine API. The edge is execution, depth of compatibility and a polished app. If fruitlocker gets overtaken anyway, it competes on the app and contributes upstream.

## Who This Serves

**Primary:** a professional developer on an Apple silicon Mac running macOS 26, who uses `docker` and `docker compose` daily for local dev stacks. They want Apple's runtime without rewriting scripts, Makefiles or compose files. For them, success means switching their Docker context and forgetting fruitlocker is there.

**Secondary:**
- **Dev Containers and Testcontainers users.** They aren't the v1 target, but much of what they need overlaps.
- **Contributors.** Swift and macOS developers who want a serious open-source project around Apple's runtime.

## Success Criteria

Stakes: public open-source adoption. Compatibility comes first, because adoption follows "it just works."

**Compatibility (the v1 gate):**
- A pinned set of public Compose sample projects runs unchanged with `docker compose up`, `down`, `logs` and `exec`. The pass rate is published, and the v1 target is at least 80%.
- The core `docker` CLI commands work: run, ps, logs, exec -it, build, pull, push, images, volume, network, inspect, stop and rm.
- CI generates a public compatibility matrix against the pinned `container` version.

**Adoption** (targets, to revisit at v1):
- 1,000 GitHub stars, and 10 outside contributors with merged PRs, within 6 months of v1.
- Homebrew cask installs are the usage signal. There's no in-app telemetry.
- Issues get triaged within a week.

## Scope

**In v1**
- The Engine API surface that the `docker` CLI and Compose need. The endpoint list is in the addendum.
- In the daemon, emulations of the Docker behavior Apple's runtime lacks (see The engine).
- A native app for engine control, resource views, logs and shell, Compose project grouping, and Docker context setup
- A signed, notarized direct download and a Homebrew cask
- An Apache-2.0 license, matching apple/container, Containerization and Socktainer

**Out of v1 (non-goals)**
- Mac App Store or sandboxed distribution. XPC to the apiserver hasn't been shown to work from a sandbox.
- A paid tier, accounts, telemetry or hosted services.
- Docker trademarks in the name or branding. "Docker-compatible" is the most it says.

**Platforms:** Apple silicon on macOS 26 and later only. No Intel Macs, and no Linux or Windows hosts.

**Out by constraint.** These don't map onto one VM per container:
- literal `--network host` and `network_mode: container:<id>`
- shared PID and IPC namespaces
- Docker-in-Docker
- host-level `--privileged` and device passthrough

Each of these fails with a clear error, never silently.

**After v1**
- *Likely next:* Dev Containers and Testcontainers as certified targets. Which one goes first isn't decided.
- *Not ruled out:* Kubernetes, and an extensions system.

## Risks and Open Questions

- **Compose service networking across VMs.** It's unproven that service names, aliases and DNS between containers can behave like a Compose network on vmnet. This is the biggest technical unknown, so it gets spiked first.
- **Events by polling.** Until apple/container#484 lands, state changes come from polling. The cost and latency at a realistic container count are unknown.
- **Upstream gaps.** Concurrent read-only named volumes (apple/container#889) are still open, and guest memory isn't returned to macOS.
- **Solo maintainer.** It's a public project with one owner, so the contributor path has to be easy from day one.

## Vision

In two to three years, fruitlocker is the default way to run containers on a Mac if you want Apple's runtime. The order: Compose first, then Dev Containers and Testcontainers, then whatever the ecosystem keys off `docker.sock` next. Where Apple's runtime is missing something (events, restart, health), fruitlocker builds a stopgap and pushes the real fix upstream, so the daemon gets thinner over time.
