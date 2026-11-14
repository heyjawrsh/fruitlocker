---
title: "Review: spine vs brief + addendum reconciliation"
target: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md
inputs:
  - _bmad-output/brief-fruitlocker/brief-fruitlocker.md
  - _bmad-output/brief-fruitlocker/addendum.md
created: 2026-11-13
lens: reconcile (requirements, scope, non-goals, risks, success criteria)
---

# Review: spine reconciled against brief and addendum

## Verdict

The core engine shape lands: one seam, no CLI scraping, emulations as controllers, loud failure for things that can't work. What's weaker is the product promise around it. "Install, open, `docker compose up`, it works" and "forget fruitlocker is there" have no architectural owner. One v1 gate criterion (`build`) has no architecture behind it. The spine also adds two constraints the brief never asked for, and one of them undercuts a differentiator the brief claims. Fix before the spine leaves draft.

Severity: **H** blocks a v1 success criterion or contradicts the brief. **M** is a requirement with no owner, or an unasked constraint with real cost. **L** is a convention to add or a wording fix.

## Top findings

### F1 (H): "Install, open, it works" has no owner. Engine readiness and degraded modes are undefined
- **Brief:** "Install the signed app, open it, run `docker compose up` in an existing project, and it works." "Success means switching their Docker context and forgetting fruitlocker is there." "Socket and app in one signed package."
- **Spine:**
  - Deployment marks Apple's pkg as a user-installed prerequisite `[ASSUMPTION]`, so it's no longer one package and no longer one install step.
  - Nothing says who brings `container-apiserver` up, or who installs its kernel, on first run and after a reboot. Apple's sanctioned path is `container system start`, and AD-2 forbids shelling out to the `container` CLI. As written, the spine has no legal way to start the runtime it depends on.
  - The helper is a root `SMAppService` daemon, so it needs user approval in System Settings. The spine doesn't say what the engine does when approval is declined or still pending. The likely result is Compose DNS failing quietly, which breaks the brief's "never silently".
  - AD-12 says "refuse to serve and tell the app why". AD-13 says the app's only channel is the Engine API socket. Read together, "refuse to serve" can't mean the socket is down, but the spine never says so.
- **Fix:** add an AD for engine readiness:
  - Name who starts the apiserver. Either grant an explicit, narrow exception to AD-2 for `container system start`/`status` (lifecycle only, never parsed for state), or find a launchd/XPC path and spike it.
  - The socket always serves `/_ping`, `/version` and `/fruitlocker/v1/status` with machine-readable reasons: apiserver missing or stopped, version gate failed, helper not approved, kernel missing.
  - While not ready, Docker endpoints return a 503-class `fruitlocker: engine not ready: <reason>`, never a partial success.
  - Compose DNS without the helper is a loud, named degraded mode, never a silent one.
  - Decide whether the Apple pkg stays external. If it does, reword the brief's "one signed package" and make the guided install part of the first-run AD.

### F2 (H): `build` is a v1 gate criterion with no architecture
- **Brief (Success Criteria, the v1 gate):** core commands include `build`. **Addendum:** `/build` with BuildKit progress.
- **Spine:** Capability map says "Build | open, see Deferred". Deferred says Docker 29 and Compose v5 build through buildx/Bake (`/session`, `/grpc`), not legacy `/build`, and mapping that onto Apple's builder is unproven. So the spine contradicts the addendum's endpoint list, which is probably right on the facts, and leaves a gate criterion unowned.
- **Fix:**
  - Promote the build spike to a named pre-v1 blocker with an issue, not a footnote.
  - Correct the addendum's endpoint list: legacy `/build` or the BuildKit session/gRPC surface.
  - If the spike fails, Josh amends the brief's gate (for example "build via `docker build` legacy builder only", or "build out of v1, listed in the matrix"). Don't leave the spine claiming v1 coverage it can't deliver.
  - Note that Compose samples with a `build:` key count against the 80% target, so this also risks the headline metric.

### F3 (M): two constraints the brief never asked for
1. **AD-11 bans `network connect`/`disconnect` on running containers.** The brief's "out by constraint" list is exact, and this isn't on it. The brief's Problem section names "network connect" as a Socktainer gap, which implies fruitlocker should close it. Making it a permanent loud failure quietly gives up a stated differentiator, and `network` is a v1 gate command.
   - **Fix:** move it out of AD-11's permanent list into Deferred, with a spike (hot-add NIC, or recreate-on-connect with the user warned).
   - If it truly can't be done, Josh adds it to the brief's "out by constraint" and the compat matrix lists it. Don't let the spine decide it alone.
2. **"Apple-native containers show in `docker ps` with a synthesized spec" `[ASSUMPTION]`.** The brief never asked for this, and it conflicts with the spine's own rules:
   - AD-3 says `FLStore` is the source of truth for every Docker object's spec. These objects have none.
   - AD-4's identity mapping (`fl-<12hex>`, daemon-minted 64-hex IDs) doesn't hold for them.
   - AD-2/AD-7 single-writer intent breaks once `docker rm` or `docker stop` can mutate objects another tool owns.

   **Fix:** drop it for v1 and hide Apple objects without `fl.docker.id`. If Josh wants it, define it as read-only with a derived ID rule, and add it to the brief.

### F4 (M): stopping or crashing the engine is undefined. AD-13 can't start the engine
- **Brief:** the app "starts and stops the engine".
- **Spine:**
  - AD-13 makes the socket the only app↔daemon channel. A stopped daemon has no socket, so the app can't start it that way.
  - AD-9: the helper closes its fds when the daemon's connection drops. After an engine stop or crash, Apple containers keep running (Apple owns runtime, AD-3), but Compose DNS, restart and health all go dead with no signal to the user.
- **Fix:**
  - State in AD-1 or AD-13 that the app controls daemon lifecycle through `SMAppService`/launchd. That isn't app↔daemon IPC, so AD-13 stays true.
  - Define "stop engine": either stop fruitlocker-owned containers first, or leave them running and document the DNS, restart and health outage.
  - Add a launchd `KeepAlive` rule for crashes, and decide whether the helper holds the fds through a short grace window on disconnect so a daemon restart doesn't drop DNS.

### F5 (M): quiet non-goals and constraints dropped
- **No telemetry, no hosted services (brief non-goal):** nowhere in the spine. Sparkle adds an update feed and has opt-in system profiling.
  - **Fix:** add a convention. The only outbound traffic is to registries the user names and to an appcast on GitHub Releases. Sparkle system profiling is off. No crash reporter phones home.
- **Contributor path easy from day one (brief risk, solo maintainer):**
  - The spine gives contributors fakes-based core tests, which is good.
  - Fork PRs never reach the compat runner, though.
  - Nothing says how a contributor runs `fruitlockerd` from `swift run` without a signed bundle and an approved root helper.
  - Xcode 27.2 / Swift 6.4.2 is listed as the build toolchain.

  **Fix:** add a dev-loop convention: the daemon runs unbundled with DNS off or on a high port, and the helper is optional in dev. Add a maintainer-triggered path (label or `workflow_dispatch`) for running the compat matrix on fork PRs. State the minimum toolchain contributors need.
- **Apache-2.0 license (brief scope):** not carried.
  - **Fix:** one convention line saying dependencies must be Apache-2.0-compatible. Hummingbird, NIO, GRDB and Sparkle all pass today.
- **Upstream gaps (brief risk):** the spine is silent on both.
  - Concurrent read-only named volumes (apple/container#889) should be an AD-11 loud failure or a named matrix known-failure.
  - Guest memory not being returned to macOS needs a default VM resource convention: what the daemon passes when Compose sets no `mem_limit` or `cpus`.

## Other findings

| # | Sev | Spine section | Finding | Fix |
|---|---|---|---|---|
| F6 | M | Deferred (#8 mitigation) | "Restart the network helper" means Apple's private vmnet helper. The addendum says private helpers carry no promise, and AD-2 bars the CLI path to restart it. | Mark that option as off-seam. If chosen, it needs an explicit AD-2 exception and a version-gated guard. |
| F7 | M | AD-14 | The rule is per-request `X-Registry-Auth`, never stored. Unverified that `ContainerAPIClient` accepts per-request credentials rather than reading Apple's keychain entries (`container registry login`). | Tag `[ASSUMPTION]` and verify in the first pull/push story. If Apple only reads its keychain, AD-14 needs rewording. |
| F8 | M | Deferred (runner host) | The public compat matrix is a v1 gate criterion, and its runner host is an open question. | Raise it to a v1 blocker with an owner. Say where the matrix is published (Pages, README badge, release asset). |
| F9 | L | AD-8 / AD-6 | Vision: "the daemon gets thinner over time". AD-8's sunset clause covers restart, health, DNS and network ordering, but not the events poller (#484). | Add the poller to the sunset clause: when #484 lands, the poller is replaced by the upstream stream. |
| F10 | L | Deferred (poll interval) | Brief risk: polling cost and latency are unknown. The Deferred item has no acceptance bar, and restart latency depends on it. | Set a target to measure against (exit seen within N s at M containers, CPU under X%). |
| F11 | L | Deployment | Brief states direct download and Homebrew cask as scope, not assumptions. | Drop `[ASSUMPTION]` from the channels; keep it on Sparkle only. Brew cask with Sparkle needs `auto_updates true`. Note that cask install counts (the brief's usage signal) undercount Sparkle-updated users. |
| F12 | L | AD-15 | "Forget it's there" breaks if `DOCKER_HOST` is set, because it overrides the context silently. | The app detects `DOCKER_HOST` or a conflicting `DOCKER_CONTEXT` and surfaces it as a compatibility warning via `/fruitlocker/v1`. AD-15 still doesn't edit it. |
| F13 | L | Capability map | No rows for addendum items `stats`, `archive` (`docker cp`), `wait`, TTY resize, or Compose project grouping in the app (from `com.docker.compose.*` labels in the spec). | Add rows so each has an owner. Hijack and resize go to the attach/exec story. |
| F14 | L | Conventions (API version) | v1.51 max / 1.44 min is `[ASSUMPTION]`, matching Socktainer. Not checked against Compose v5.7.1's minimum or the features it needs. | Verify against the pinned Compose before locking. |
| F15 | L | AD-1 | Non-goal "no App Store or sandboxed distribution" is implied (Developer ID, root helper) but not stated. | Add "unsandboxed, Developer ID only" to AD-1 so nobody tries to sandbox the app later. |

## Coverage ledger

Key: ✔ covered · ◐ partial · ✘ missing · ⚠ contradicted.

| Source item | Status | Where / note |
|---|---|---|
| Swift daemon serving Engine API on a Unix socket | ✔ | AD-1, AD-13, Conventions |
| Native app on top | ✔ | AD-1, AD-13 |
| Events stream by polling until #484 | ◐ | AD-6. No sunset (F9), no latency bar (F10) |
| Restart policies, healthchecks | ✔ | AD-8 |
| Compose service networking | ✔ | AD-9, AD-10 (fd-handover spike deferred) |
| App: menu-bar presence | ◐ | Deferred to `bmad-ux`, acceptable |
| App: starts and stops the engine | ⚠ | AD-13 can't start a stopped daemon; stop semantics undefined (F4) |
| App: resource views grouped by Compose project | ◐ | Labels in spec (AD-3); no map row (F13) |
| App: logs, shell | ✔ | AD-13 |
| App: docker context on first run, with undo | ✔ | AD-15 |
| "Install, open, compose up, works" | ✘ | F1 |
| One signed package | ⚠ | Apple pkg external (F1) |
| Supported seam, no CLI scraping | ✔ | AD-2, AD-12 |
| Public compatibility matrix | ◐ | Compat/, CI; runner host and publish location open (F8) |
| Contributes upstream / daemon thins | ◐ | AD-8 (F9) |
| Apple silicon, macOS 26+ | ✔ | Stack (arm64-only not stated, trivial) |
| Gate: ≥80% pinned Compose samples, published | ◐ | Compat/; at risk from build (F2) |
| Gate: core commands incl. build, network | ⚠ | build unowned (F2); running-container network connect banned (F3) |
| Gate: CI matrix against pinned container | ◐ | F8 |
| Adoption: cask installs as signal, no telemetry | ✘ | F5, F11 |
| Adoption: 10 outside contributors | ◐ | Fakes help; dev loop and fork compat missing (F5) |
| Issues triaged in a week | n/a | Process |
| Engine API surface per addendum | ◐ | F13, F14 |
| Signed, notarized download + cask | ✔ | Deployment (F11 wording) |
| Apache-2.0 | ✘ | F5 |
| Non-goal: App Store / sandbox | ◐ | Implied (F15) |
| Non-goal: paid tier, accounts, telemetry, hosted services | ✘ | F5 |
| Non-goal: Docker trademarks in branding | ✔ | Nothing violates; context, bundle and module names are clean |
| Out by constraint list + loud errors | ✔ / ⚠ | AD-11 covers all; adds an unlisted item (F3) |
| After v1: Dev Containers, Testcontainers, k8s, extensions | ✔ | Deferred |
| Risk: Compose networking across VMs | ✔ | AD-9/AD-10 adopted from #4/#5 |
| Risk: events by polling | ◐ | F10 |
| Risk: #889 RO volumes, guest memory | ✘ | F5 |
| Risk: solo maintainer, contributor path | ◐ | F5 |
| Addendum: same-user, unsandboxed seam | ✔ | AD-1 LaunchAgent; root helper never touches apiserver (AD-2) |
| Addendum: XPC stable in 1.x | ✔ | AD-12 |
| Addendum: private helpers carry no promise | ⚠ | #8 mitigation option (F6) |
| Addendum: CLI JSON changed; don't scrape | ✔ | AD-2 |
| Addendum: watch #484, #2142, #1918, #889, #1846 | ◐ | #889 absent (F5); #1846 has no arch impact |
| Addendum: Testcontainers facade socket (later) | ✔ | Deferred; AD-13's single-socket rule is app↔daemon only, so it doesn't block a later facade |

## Spine assertions the brief never asked for

| Assertion | Risk | Recommendation |
|---|---|---|
| AD-11: `network connect`/`disconnect` on running containers is unsupported | Gives up a stated differentiator and a gate command | F3: defer and spike, or amend the brief |
| Convention: Apple-native containers in `docker ps` | Breaks AD-3/AD-4/AD-7 | F3: drop for v1 |
| Deployment: Apple pkg not bundled | Breaks "one package, it just works" | F1: decide and reword one side |
| AD-14: credentials never stored | Reasonable, but feasibility unverified | F7 |
| Self-hosted runner never runs fork PRs | Correct for security; costs contributors | F5: maintainer-triggered path |
| Bridge maps to a fruitlocker-owned Apple network | Fine, grounded in #8 | Keep |
| AD-12: exact 1.7.1 link, same-major runtime gate | Fine, matches addendum | Keep; F1 defines what "refuse to serve" looks like |
