---
title: "Product Brief: fruitlocker"
status: draft
created: 2026-11-09
updated: 2026-11-09
inputs:
  - _bmad-output/research-apple-container/research-apple-container.md
issue: https://github.com/heyjawrsh/fruitlocker/issues/3
---

# Product Brief: fruitlocker

## Executive Summary

fruitlocker is an open-source, Docker-compatible container app for Apple silicon Macs. It runs on Apple's own `container` runtime instead of a Linux VM shared by every container. It has two parts: a Swift daemon that serves the Docker Engine API on a local socket, and a native macOS app on top of it.

Apple's `container` hit 1.x this fall. It's Apache-2.0, maintained by Apple, and puts each container in its own lightweight VM. But it has no Docker Engine API, and the whole Docker ecosystem (the `docker` CLI, Compose, Dev Containers, Testcontainers, IDE and CI integrations) expects `docker.sock`. So today a Mac developer can use Apple's runtime or their existing tools, but not both.

v1 closes that gap for the most common workflow: `docker` and `docker compose` against an ordinary `compose.yaml`, with nothing changed. Nobody ships that today. The timing works because 1.x promises a stable `container-apiserver` XPC API within the major version, and publishes `ContainerAPIClient` as a linkable Swift library. That means fruitlocker can build on a typed, supported seam instead of scraping CLI output.

## The Problem

A developer on an M-series Mac runs a local stack every day: an app, Postgres, Redis, maybe a worker, all in one `compose.yaml`. Their options:

- **Stay on Docker Desktop, OrbStack, Colima or Podman.** These work, but they don't run on Apple's runtime. [ASSUMPTION] Some users want off them for cost, licensing, resource use or plain preference for Apple's stack.
- **Use Apple `container` directly.** Everything has to be rewritten as `container` commands. Apple ships no Compose (apple/container#1846 is still open). Container-Compose describes itself as "limited."
- **Use Socktainer.** It's the closest thing to a socket. It's headless and calls itself partial, with gaps in pause, commit, network connect and restart policies.
- **Use a GUI like Orchard.** It's polished, but it says outright that it "does not expose a Docker-compatible API socket," so `docker compose` still doesn't work.

What it costs them: either they keep two container stacks, or they give up Apple's runtime for anything that touches Compose.

## The Solution

**The engine.** A Swift daemon that links `ContainerAPIClient`, talks to `com.apple.container.apiserver` over XPC, and serves the Docker Engine API on a Unix socket. It adds what Apple doesn't have yet but Compose expects:
- an events stream, built by polling until apple/container#484 lands
- restart policies (#2142)
- healthchecks (#1918)
- service-to-service networking for Compose projects

**The app.** A native SwiftUI macOS app with a menu-bar presence. It starts and stops the engine, and shows containers, images, volumes and networks grouped by Compose project. It streams logs, opens a shell, and points the user's `docker` context at fruitlocker's socket. [ASSUMPTION] Setting the context happens automatically on first run, with an undo.

**The experience.** Install the signed app, open it, run `docker compose up` in an existing project, and it works.

## What Makes This Different

- **Socket and app in one signed package, on Apple's runtime.** Orchard has the app but no socket. Socktainer has a partial socket but no app. Container-Compose has neither.
- **Built on the supported seam.** It runs on the 1.x XPC client API, which Apple promises stays compatible within the major version. It doesn't parse CLI text, whose JSON shapes already broke once at 1.0.
- **Compatibility is the product.** Success is measured by real Compose files running unchanged, and a public compatibility matrix says what works and what doesn't.

To be honest about the moat: there isn't a technical one. Socktainer could close its gaps, or Apple could ship Compose or a Docker-compatible API. fruitlocker's edge is execution, depth of compatibility, and a polished app, and staying ahead means moving fast and being upfront about gaps.

## Who This Serves

**Primary:** a professional developer on an Apple silicon Mac running macOS 26, who uses `docker` and `docker compose` daily for local dev stacks. They want Apple's runtime without rewriting scripts, Makefiles or compose files. For them, success means switching their Docker context and forgetting fruitlocker is there.

**Secondary:**
- **Dev Containers and Testcontainers users.** They aren't the v1 target, but much of what they need overlaps.
- **Contributors.** Swift and macOS developers who want a serious open-source project around Apple's runtime.

## Success Criteria

Stakes: public open-source adoption. Compatibility comes first, because adoption follows "it just works."

**Compatibility (the v1 gate):**
- [ASSUMPTION] A fixed set of real-world Compose projects runs unchanged with `docker compose up/down/logs/exec`, with a published pass rate and a target of at least 80% at v1. The candidate set is a pinned subset of public sample repos.
- The core `docker` CLI works: run, ps, logs, exec -it, build, pull, push, images, volume, network, inspect, stop/rm.
- A public compatibility matrix, generated from CI against the pinned `container` version.

**Adoption** ([ASSUMPTION] targets, to revisit at v1):
- 1,000 GitHub stars and 10 outside contributors with merged PRs within 6 months of v1.
- Homebrew cask installs tracked as the usage signal (no in-app telemetry).
- Issues triaged within a week.

## Scope

**In v1**
- The Engine API surface that docker CLI and Compose need:
  - `/_ping`, `/version`, `/info` with version negotiation
  - container lifecycle, logs, stats, wait
  - attach and exec with HTTP hijack and TTY resize, plus archive
  - images: pull, push, tag, load, save, and `/build` with BuildKit progress
  - networks and volumes with labels and filters
  - `/events`
  - `/auth`
- Docker semantics that Apple lacks, emulated in the daemon: events, restart policies, healthchecks, Compose service DNS
- A native app for engine control, resource views, logs and shell, Compose project grouping, and Docker context setup
- Signed and notarized direct download. [ASSUMPTION] Also a Homebrew cask.
- Apache-2.0 license, matching apple/container, Containerization and Socktainer.

**Out of v1 (non-goals)**
- Mac App Store or sandboxed distribution. XPC to the apiserver hasn't been shown to work from a sandbox.
- A paid tier, accounts, telemetry or hosted services.
- Docker trademarks in the name or branding. "Docker-compatible" is the most it says.

**Out by constraint.** These don't map onto one VM per container:
- Intel Macs, macOS before 26, and Linux or Windows hosts
- literal `--network host` and `network_mode: container:<id>`
- shared PID and IPC namespaces
- Docker-in-Docker
- host-level `--privileged` and device passthrough

Each one fails with a clear error, never silently.

**Not v1, not ruled out**
- Dev Containers and Testcontainers as certified targets
- Kubernetes
- an extensions system

## Risks and Open Questions

- **Compose networking across VMs.** It's unproven that service names, aliases and inter-container DNS can be made to behave like a Compose network on vmnet. This is the biggest technical unknown, so spike it first.
- **Events by polling.** Without apple/container#484, state changes come from polling. The cost and latency at a realistic container count are unknown.
- **Upstream gaps.** Concurrent read-only named volumes (#889) are open. Guest memory isn't returned to macOS.
- **Being overtaken.** Apple could ship Compose or an Engine API, or Socktainer could reach parity. The plan if that happens: compete on the app, and contribute upstream.
- **Solo maintainer.** It's a public project with one owner. The contributor path has to be easy from day one.
- **Coverage gap.** Web search failed during recon, so paid or non-GitHub competitors are under-sampled.

## Vision

In two to three years, fruitlocker is the default way to run containers on a Mac if you want Apple's runtime. The order: Compose first, then Dev Containers and Testcontainers, then whatever the ecosystem keys off `docker.sock` next. Where Apple's runtime is missing something (events, restart, health), fruitlocker builds a stopgap and pushes the real fix upstream, so the daemon gets thinner over time.
