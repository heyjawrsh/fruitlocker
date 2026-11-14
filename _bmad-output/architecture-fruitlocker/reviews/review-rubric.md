---
type: review
lens: rubric
target: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md
memlog: _bmad-output/architecture-fruitlocker/.memlog.md
date: 2026-11-13
---

# Rubric review: fruitlocker v1 architecture spine

## Verdict

**Not ready to bind the epics yet.** The core topology (AD-1 to AD-5, AD-9, AD-13 to AD-15) is sound and terse. Three things block it: the operational envelope is mostly silent, the security boundaries aren't stated, and three Compose-critical divergence points (ports, volumes, logs) are missing. A few Rules (AD-6, AD-7, AD-10, AD-11) also can't stop the divergence they name as written. All of it can be fixed forward with roughly four new ADs and some Rule tightening. Nothing here needs a restart.

Severity scale: **H** means two units will diverge, or a security hole ships, unless fixed before fan-out. **M** means a Rule is ambiguous enough that implementers will make different choices. **L** means polish or over-specification.

---

## 1. Operational envelope (dimension largely silent)

### F1 [H] No startup/crash-recovery reconcile, and no store↔Apple write ordering
*Affects: missing AD; touches AD-3, AD-6, AD-8, AD-10.*

The spine never says what happens when `fruitlockerd` starts while Apple containers are already running. That covers a crash, a Sparkle update, logout/login and a Mac reboot. Each controller will invent its own boot behavior:
- **Restart policies at boot.** Docker starts `always` and `unless-stopped` containers when the daemon starts. Nothing says whether the restart controller does that, or in what order relative to NetworkController.
- **Poller baseline.** Does the first snapshot emit events (spurious `start`/`die` floods on `/events`) or set a silent baseline?
- **DNS after restart.** The helper drops its fds when the daemon's connection drops (AD-9), so running Compose stacks lose service names until NetworkController rebinds. The rebind must follow the #5 guard, and the spine doesn't say it does.
- **Orphans.** There's no write order between `FLStore` and Apple for create, start and rm. A crash in between leaves either an Apple object with `fl.docker.id` and no spec, or a spec that claims an Apple object which doesn't exist. Nobody owns cleanup.

**Fix:** add an AD for startup reconcile.
- (a) The store is written before any Apple mutation. An Apple object whose `fl.docker.id` has no spec is an orphan that one `Reconciler` removes at startup.
- (b) Startup order is fixed: version gate (AD-12), then store migrate (F4), then poller baseline (silent, no events), then NetworkController rebinds per the guard, then restart controller applies boot policies, then the socket starts serving.
- (c) The API socket isn't served until reconcile finishes, or it serves `/_ping` only.

### F2 [H] Security boundaries of the socket and the helper aren't stated
*Affects: missing AD; touches AD-1, AD-9, Conventions "Socket and paths".*

- **Engine socket.** No mode or ownership is set, and nothing forbids TCP. The Docker socket is user-equivalent. Fix: the socket is Unix only, the file is `0600` and its directory `0700`, both owned by the user, and `fruitlockerd` never listens on TCP. Facade sockets for Testcontainers are post-v1 and must get their own AD.
- **Helper XPC peer.** The root helper accepts "gateways the daemon names", but the spine never says how the helper knows the caller *is* the daemon. As written, any local process could ask root to bind `:53` on any address. Fix: the helper accepts XPC only from peers whose code-signing requirement matches `sh.jawr.fruitlocker.daemon` and the team ID, checked by audit token. It binds only an address that is currently the IPv4 address of a vmnet bridge interface, and refuses everything else. AD-9's "never binds the wildcard" isn't enough on its own.
- **Multi-user.** The helper is system-wide, but the daemon is per-user (AD-1). Two logged-in users means two daemons asking one helper for binds. Fix: either declare v1 single-user (the helper serves one connection at a time and rejects a second) or key every bind by the peer's uid. Pick one.

### F3 [M] Version skew across the three processes and Sparkle updates
*Affects: AD-1, AD-13, `FLHelperProtocol`, Deployment.*

Sparkle replaces the bundle while the LaunchAgent and LaunchDaemon are running from inside it. Nothing fixes:
- that the app, daemon and helper come from the same build, or how skew is detected
- the `FLHelperProtocol` version handshake
- the compatibility promise for `/fruitlocker/v1/*`

Fix: all three ship in one bundle and are versioned together. `FLHelperProtocol` begins with a version handshake, and a mismatch makes the helper refuse and the daemon re-register it through `SMAppService`. After an update, the app restarts the daemon before it talks to it, and `/_ping` or `/fruitlocker/v1/status` reports the build. `/fruitlocker/v1` is additive only within v1.

### F4 [M] Store migration is deferred, but every epic will touch it
*Affects: Deferred "Store schema"; missing Rule.*

"The code owns the detail" is fine for the schema itself. The *migration policy* is cross-unit, though. Every epic adds tables or columns, and without one rule you get ad-hoc `CREATE TABLE IF NOT EXISTS` in one module and a migrator in another. Fix: add a Rule to AD-3 or a new AD:
- Migrations use GRDB `DatabaseMigrator`, are append-only, named and never edited.
- They run at startup before serving (F1), after a copy of the database file is taken.
- A store newer than the binary makes the daemon refuse to serve. Downgrade isn't supported.

### F5 [M] Uninstall is silent
*Affects: missing; touches AD-1, AD-15, Deployment.*

Who unregisters both `SMAppService` services, restores the previous Docker context (AD-15 records it, but nothing says the record is used at uninstall), removes `~/.fruitlocker`, and decides whether fruitlocker-owned Apple containers, networks and volumes are deleted or left? Fix: put one uninstall path in the app (menu item), used by the Homebrew cask `zap` too. It restores the context, unregisters the services, and asks before deleting Apple objects labeled `fl.docker.id`. The default is to leave user data.

### F6 [M] Apple's service bootstrap conflicts with AD-2
*Affects: AD-2, AD-12, Deployment.*

AD-2 says nothing shells out to the `container` CLI. The proof lane started the services with `container system start --enable-kernel-install`, which is CLI. If `ContainerAPIClient` has no start/install API, the daemon can't satisfy AD-2 and bring the apiserver up after a reboot. Fix: confirm whether the 1.7.1 client exposes system start. If it doesn't, either add a narrow, named exception (bootstrap and kernel install only, never output parsing) or make it an open question with a spike. Also say whether AD-12 is re-checked when the apiserver reconnects, since a user can upgrade Apple's pkg while the daemon runs.

### F7 [L] Dev/release environment isolation
*Affects: Conventions "Socket and paths", "Bundle and log ids".*

A dev build of `fruitlockerd` next to an installed release would share the socket, the store, the `fruitlocker` context and the helper's binds. Fix: one root override (`FRUITLOCKER_HOME`, or a dev bundle-id suffix) that moves the socket, store and context name together, and a rule that dev daemons never register the release helper.

### F8 [L] Logging is half-specified
*Affects: Conventions.*

OSLog subsystem and category are set, but "store and logs in `~/Library/Application Support/fruitlocker/`" implies file logs too. Pick one. The likely choice is OSLog only, with a diagnostics export through `/fruitlocker/v1`.

---

## 2. Missed divergence points for the level below

### F9 [H] Port publishing has no owner
*Affects: missing AD; Capability map.*

`ports:` is in most Compose files, and the spine is silent on it. Epics will diverge on:
- Apple-native publish versus a daemon-side userspace proxy
- who allocates ephemeral host ports (`-p 0:80`, `-P`) and whether the allocation is spec (stored) or runtime (read live, AD-3)
- conflict errors
- the default bind address
- how `NetworkSettings.Ports` is filled in

Fix: one AD that names the mechanism (or an open question with a spike) and places allocated host ports explicitly on the spec side or the runtime side of AD-3.

### F10 [H] Volume data location isn't fixed
*Affects: AD-3, AD-5 analogue missing.*

AD-3 puts volume *metadata* in the spec. Nothing says where volume *data* lives: Apple volumes (`container volume`), or daemon-managed directories bind-mounted in. That choice drives:
- the volumes epic
- Compose named volumes
- the app's volume views and sizes
- `docker volume rm`
- the #889 workaround

Fix: an "AD-5 for volumes". Either Apple's volume store is the only volume store and Docker volume names map to `fl-<…>` Apple volumes, or say the opposite explicitly. Also note that Docker keys volumes by *name*, not a 64-hex ID, and anonymous volumes get 64-hex names. AD-4 should say which applies.

### F11 [M] Container log source isn't fixed
*Affects: missing; touches AD-5 pattern.*

`docker logs`, Compose `logs -f`, the app's log view and `--since`/`--timestamps` all need one source. Is it Apple's log stream read live, or a daemon-captured copy? If the logs epic captures stdio to files while the app streams from Apple, the two will disagree. Fix: one line, either "Apple's container log is the only log store; the daemon keeps no copy" or the opposite.

### F12 [M] Apple-native containers have no defined Docker ID or write semantics
*Affects: AD-4, Conventions "Apple-native containers".*

AD-4 says the daemon mints IDs, but Apple-native containers have no `fl.docker.id`. If IDs are minted on each listing they change across restarts. If they're persisted, the store holds foreign objects, which contradicts AD-3. Can `docker rm`/`stop` act on them? Do Apple-native networks appear in `docker network ls`? Fix: derive the ID deterministically (for example `sha256(apple id)`, never stored), make foreign objects read-only through the Engine API except stop/rm (state which), and give the same rule for networks.

---

## 3. Rules that don't fully prevent their divergence

### F13 [M] AD-6 needs a causality mechanism
"The poller publishes only for changes the daemon didn't cause" can't be implemented without saying how the poller knows. Some implementers will dedupe by time window, others by expected state. It's also ambiguous who emits `die` after `docker stop`: the stop service or the poller. Fix: split ownership by event type. Core services publish intent events (`create`, `destroy`, `rename`, `connect`, `kill`). The poller is the only publisher of observed runtime transitions (`start` completion, `die`, `oom`). Alternatively, core services record an expected-transition token that the poller consumes. Pick one.

### F14 [M] AD-7's per-kind actors leave cross-kind races open
`network rm` racing a `container create` that references the network, or `volume rm` racing a start that mounts the volume, runs across two actors. Nothing orders them, and AD-10 also wants to order container start/stop per network. Fix: say that reference checks and the referencing write happen in one `FLStore` transaction (foreign keys), and that container start/stop call NetworkController's pre-start/pre-stop hooks synchronously. Alternatively, define a lock order (network, then volume, then container) for operations that touch more than one kind.

### F15 [M] AD-10's "release before the last container stops" only covers stops the daemon causes
Exits caused by crash, OOM, a stop from Apple's CLI, or a restart-controller loop can't be pre-empted. Fix: state the fallback (release on the poller's `die` or the bridge-down event, immediately) and accept the residual #402 window as a known risk. Also say whether host interface events (route socket or SCDynamicStore) go onto the `EventBus`. AD-6 currently implies the poller is the only external event source.

### F16 [M] AD-11 lists options but no classification rule
Every create body carries dozens of `HostConfig` fields (`CapAdd`, `Ulimits`, `ShmSize`, `Sysctls`, `SecurityOpt`, …). With only a list of forbidden options, each handler author decides for themselves whether an unknown field is ignored, warned or rejected, which is exactly the silent no-op AD-11 exists to stop. Fix: every request field is classified once, in one table in `FLEngineAPI`, as supported, accepted-with-warning (Docker's `Warnings` array) or rejected. Any field not in the table is rejected when it is non-default.

### F17 [L] AD-9 has no fallback contract if the fd handover fails
The Deferred spike may fail. Spike #5's fallback is a packet relay over XPC, which changes `FLHelperProtocol`. Fix: build `FLDNS` against a `DatagramSocket` port so either delivery path plugs in, and say so in AD-9.

---

## 4. Deferred items

- **Store schema:** fine for the schema, but the migration policy must come out of Deferred (F4).
- **#8 mitigation:** "restart the network helper" may mean `launchctl` on Apple's private helper, which collides with AD-2 (F6). Note that constraint now.
- **fd handover:** see F17.
- **Build, hijack, poll interval, UI, runner host, after-v1:** contained. None of them lets two units diverge.

## 5. Tech currency

Nothing obviously wrong. Swift 6.4.2/Xcode 27.2, Hummingbird 2.28.1, NIO 2.105.0, GRDB 7.12.0, Sparkle 2.10.1 and container 1.7.1/Containerization 0.54.0 all match the memlog's 2026-11-13 check. Engine API max v1.51 against docker 29.9.3 (API v1.57) depends on CLI downward negotiation, which is already flagged `[ASSUMPTION]`. Keep it in the first compatibility run. Containerization 0.54.0 is transitive and doesn't need its own Stack row; that's optional.

## 6. Over-specification

- **AD-9's resolver bullet** (source-IP keying, multi-A, AAAA NODATA, `scutil --dns`) is internal to `FLDNS` and binds no other unit. Move it to the FLDNS story or seed and keep a pointer to #4.
- **"It tracks bridges by event, not by polling" (AD-10)** is an implementation detail of one controller, unless F15 makes it an EventBus source. If it does, keep it there.
- **Deployment CI rationale** ("because GitHub's runners have no nested virtualization") belongs in the memlog, which already has it. The spine needs only the rule: compatibility runs on a self-hosted Apple silicon runner, and fork PRs never run there.
- **AD-12 and AD-14 "Prevents" lines** are fine. No other rationale leaks.

## 7. Memlog ↔ spine consistency

Consistent overall. The spine widens two things, and both are improvements: AD-7 covers store ports as well as runtime ports, and AD-11 adds `disconnect`. The memlog's Hummingbird decision lists "build session" as a hijacked endpoint. The spine leaves it out, which is correct, because Build is deferred.

## Suggested additions (summary)

| New/changed | Content |
|---|---|
| AD-16 Startup reconcile | F1: write order, orphan sweep, fixed boot sequence, serve after reconcile |
| AD-17 Local security boundary | F2: Unix socket 0600 and no TCP; helper peer code-sign check; bind only live vmnet bridge addresses; single-user or per-uid |
| AD-18 Ports | F9: mechanism, plus spec-vs-runtime ownership of allocated ports |
| AD-5b Volumes, one-line log-source rule | F10, F11 |
| AD-3 / new | F4: migration policy |
| AD-1 / AD-13 | F3: one-bundle versioning, helper handshake, `/fruitlocker/v1` additive |
| Tighten AD-6, AD-7, AD-10, AD-11, AD-4 | F13 to F16, F12 |
| Deployment | F5 uninstall, F7 dev isolation; F6 as an open question |
