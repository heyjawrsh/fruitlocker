---
title: v1 open questions, with recommendations
date: 2026-11-14
issue: heyjawrsh/fruitlocker#21
status: decided 2026-11-14 (Josh)
---

# v1 open questions

Josh asked for recommendations that keep fruitlocker robust, powerful, secure and very usable.

## 1. Who hosts the self-hosted CI runner

**Constraint.** The compatibility matrix needs real Apple `container` VMs. GitHub's hosted macOS runners can't nest virtualization (architecture spine, Deployment).

**Recommendation: two phases, and never on Josh's daily Mac long-term.**
- **Now through the feature epics:** hosted macOS runners do lint, unit tests and build against fakes. Integration checks run on Josh's Mac as local scripts, started by hand, the way spikes #4, #5 and #11 did.
- **From epic-compat-matrix on:** a dedicated, always-on Apple silicon Mac (a base Mac mini is enough) as the self-hosted runner, bare metal, under its own macOS user.
  - It only takes trusted triggers: pushes to `main`, tags, `workflow_dispatch`, and PRs a maintainer labels. Never fork PRs, because a runner on a public repo executes whatever code a PR brings.
  - Bare metal matters. Apple `container` inside a VM-based runner (Tart, Anka) needs nested virtualization, which isn't something to bet on.
- **Why not Josh's Mac as the runner:** test code would run with his user's access, and the DNS work has already wedged vmnet once (spike #4). A dedicated box caps both risks.
- Cloud alternatives (EC2 Mac dedicated hosts, MacStadium) work too, but cost more over a year than a Mac mini.

## 2. Docker-in-Docker detection

**Finding (tested 2026-11-14 on container 1.7.1):**
- `docker:29-dind` started with `--cap-add ALL` runs dockerd 29.9.3 (overlayfs, cgroup v2). Nested containers ran with `--network none` and `--network host`.
- Nested bridge networking fails, because Apple mounts `/proc/sys` read-only and dockerd can't turn on IP forwarding.
- `--publish-socket` only goes from container to host. The only host-to-container relay in the CLI is `--ssh`.

**Recommendation: stop detecting "DinD" and handle the two real mechanisms.**
1. **`--privileged` means all capabilities inside the container's own VM, never host devices.** Each container is its own VM, so the VM stays the boundary. This makes DinD (minus nested bridge networks), BuildKit and similar tools work. Log one warning per create. `--device` stays rejected. *This amends AD-11's rejected list and R13, so it needs Josh's yes.*
2. **Bind mounts of a Unix socket are caught by file type, not by path.** At create time, `stat` each bind source; a socket (`S_ISSOCK`) can't cross virtiofs.
   - If the source is a Docker socket, fruitlocker's own included, relaying fruitlocker's socket into the guest would make Traefik, Portainer, Testcontainers and devcontainers work. Containerization's SSH-agent forwarding suggests the runtime can relay host sockets inward. Not yet verified: spike it before promising it.
   - Until then, and for any other socket, reject with a clear error.
- Nested bridge networking stays unsupported until someone finds out whether Containerization can mount `/proc/sys` read-write.

## 3. Build our own engine, or join Socktainer

The brief rejected Socktainer with no recorded reason. Its source at v1.6.1 (2026-11-09) was read on 2026-11-14 against the spine. Nothing was run.

**Where Socktainer is strong**
- It covers most endpoints, with real exec/attach hijack plus TTY, a large archive implementation, stats, health, and restart backoff that follows moby's rules.
- Container DNS needs no root: one small forwarder VM per network relays to a host server on port 2054. That's easier to live with than our root helper and its admin prompt.
- Active: releases roughly weekly, outside PRs merged, and Podman Desktop's Apple Container extension uses it as its backend.

**Where it falls short of the spine**
- **State:** Docker settings live in labels plus three JSON files. There's no store, ledger or boot reconcile, and restart policies don't survive a Socktainer restart.
- **Silent success:** `network connect`/`disconnect` return 200 and do nothing. `network_mode: none` and `host` quietly become the default network. AD-11 requires a loud failure.
- **DNS:**
  - A security issue in its DNS server was reported privately to the maintainers on 2026-11-14. Details stay out of this repo until they publish a fix.
  - It returns one address per name, so scaled services get no multi-A.
- **Build:** only legacy `/build` through Apple's builder, without secrets, SSH or `.dockerignore`. No `/grpc`, and `/session` errors. Compose builds still work, because buildx falls back to a `docker-container` builder inside Socktainer (measured, #22).
- **Not implemented:** pause and commit. Also no app.
- **CI:** it runs against real Apple `container` for images, networks and volumes only. No `run`, Compose or build.

**Recommendation: decide on evidence, in about a week, before building either way.**
1. Run a pinned Compose sample set (for example from `docker/awesome-compose`) against Socktainer `main` on container 1.7.1, and get a real pass rate.
2. Report the DNS exposure to the maintainers privately (security advisory, not a public issue).
3. Open one design discussion upstream: a persistent spec store, failing loudly, and the spike #11 build path.
4. Then choose:
   - **Join (hybrid):** build the app on the Engine API with Socktainer as its backend, and contribute DNS scoping, the build path and durable restarts upstream. Pick this if the maintainers welcome a store and failing loudly, *and* the pass rate is about 70% or better.
   - **Build our own:** the spine as written. Pick this if either condition fails. The app is unaffected (AD-13: it talks only to the Engine API), so work on it is never wasted.

## Decisions (Josh, 2026-11-14)

1. **CI runner:** phased as recommended. A dedicated Mac mini runs as the self-hosted runner from epic-compat-matrix on, with trusted triggers only.
2. **`--privileged`:** allowed as all capabilities inside the container's VM, never host devices. `--device` stays rejected. Socket bind mounts get a clear error until a relay spike proves forwarding fruitlocker's socket inward. This amends AD-11 and R13.
3. **Socktainer:** measure first. Get a Compose pass rate, report the DNS exposure privately, and hold one upstream design discussion, then choose join (hybrid) or build. Epic work on the engine waits on that call. App and spikes don't.

## Progress on 3 (2026-11-14)

- Pass rate: **16 of 22 (73%)**, which clears the bar. Five failures are one cause, single-file bind mounts (#26). Details in `_bmad-output/socktainer-measure/`.
- DNS report sent privately.
- Design discussion open: socktainer/socktainer#521. The call waits on the maintainers' answer.
