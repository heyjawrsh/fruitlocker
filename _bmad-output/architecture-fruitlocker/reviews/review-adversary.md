---
title: "Adversarial review: fruitlocker v1 architecture spine"
lens: divergence pairs (units that each obey every AD and still build incompatibly)
target: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md (status draft, 2026-11-13)
also_read: .memlog.md, spike-compose-dns.md (#4), spike-gateway-dns.md (#5)
date: 2026-11-13
---

# Adversarial review: fruitlocker v1 spine

## Verdict

**Not yet a build substrate.** The ownership split (AD-3), the single Apple client (AD-2) and the helper split (AD-9) are sound. But three ADs contradict each other once you build against them literally: AD-8 makes every controller a post-hoc event subscriber, while AD-10 requires the network controller to act *before* a stop. AD-7 relies on actor serialization, and Swift actors are reentrant. AD-3 has two buckets of state, spec and live runtime, and Docker needs a third: state the daemon observes and must keep. Each of these lets two careful builders ship parts that don't fit. The worst outcome, the #402/#4 vmnet wedge, takes down container networking for the whole Mac until a reboot.

13 pairs below, ranked by severity. Each ends with a concrete Rule to add or tighten.

## How to read a pair

- **Unit A / Unit B:** two pieces built independently, one level below the spine.
- **Both legal because:** the AD text each one follows.
- **Divergence:** how they fail to fit.
- **Rule:** the AD text that closes the gap.

---

## P1 — Pre-stop release vs event-driven controllers (CRITICAL, wedge risk)

- **Unit A:** `ContainerService.stop` (container actor). It calls `runtime.stop`, then publishes `kill`/`die`/`stop` "at the moment it happens" (AD-6).
- **Unit B:** `NetworkController`. Per AD-8 it "subscribes to the EventBus… and acts only through core services". On `stop` it checks whether that was the network's last running container and releases the gateway.
- **Both legal because:** AD-8 defines a controller as an event subscriber, and AD-6 has events published when the mutation happens.
- **Divergence:**
  - AD-10 says release happens *before* the last container stops. An event subscriber only hears about the stop afterwards, so B releases late. That is exactly the #402 window from spike #5 phase 7: mDNSResponder drops `*:53` while the gateway bind is still held.
  - The same problem hits "orders first starts". B can't hold back a start it only hears about afterwards.
  - Concurrent stops make it worse. `compose down` stops `db` and `web`, the last two containers on `pa_default`, and each "is this the last one?" check sees the other still running. Neither releases, and the bind stays held with zero containers.
  - Every other stop path skips a hook that lives only in `ContainerService.stop`: `kill`, `rm -f`, `restart`, the restart controller's own stop, daemon shutdown, and app quit (which shouldn't stop the daemon, but `SMAppService` unregister will).
- **Rule (tighten AD-8, AD-10):**
  - Add a `NetworkLifecycle` port in `FLCore` that `NetworkController` implements. It is the only allowed pre-mutation hook.
  - Every core path that starts or stops a container's VM, whatever the reason, calls `await lifecycle.willStart(id)` / `await lifecycle.willStop(id)` and waits for it to return before calling the runtime.
  - `NetworkController` keeps the per-network count of running containers itself, serialized under its own isolation. A container counts as not running from the moment `willStop` returns.
  - `willStop` for the last container returns only after the release has completed (see P2).
  - Exits the poller detects (crashes) can't be pre-empted. On `die` for the last container, release immediately; that window is accepted and must be documented.

## P2 — Two owners of the bound socket (CRITICAL, wedge risk)

- **Unit A:** `fruitlocker-helper`. It binds `<gw>:53`, sends the fd over XPC, keeps its copy, and closes that copy "when the daemon asks or when the daemon's connection drops" (AD-9, literally).
- **Unit B:** `FLDNS` / `NetworkController`. To release, it sends `release(gw)` to the helper. That is AD-10's "asks the helper to bind or release."
- **Both legal because:** AD-9 has the helper close its own copy, and AD-10 makes asking the helper the way to release.
- **Divergence:**
  - Once the fd is passed, the daemon and the helper hold two descriptors for one socket. The bind stays alive until *both* are closed.
  - B asks the helper to release, the helper closes its copy, and the daemon's copy keeps `<gw>:53` bound indefinitely. That is the #402 precondition, held open on purpose.
  - Or the reverse: a builder ports spike #5's helper-side guard (unbind when the bridge goes away or mDNSResponder drops `*:53`). The helper "releases" and nothing changes, because the daemon still holds the socket.
- **Rule (tighten AD-9):**
  - The helper closes its copy as soon as the handover succeeds, and keeps no fds or bind state.
  - `fruitlockerd` is the only owner of every gateway socket. Release means the daemon closes its fd. If the daemon dies, the kernel closes it.
  - The helper never runs a guard of its own.
  - The daemon owns the bind preconditions: whether the bridge is up, from the host interface (route socket or SCDynamicStore), and whether mDNSResponder holds `udp4 *:53`. It reaches them through a `HostNetObserver` port in `FLCore`, implemented in `FLDNS`.
  - If the daemon can't see the mDNSResponder socket without privilege, the helper gets exactly one read-only query, `mdnsHoldsWildcard() -> Bool`, and the spine has to say so.

## P3 — Actor reentrancy breaks "one actor serializes mutations" (HIGH)

- **Unit A:** `ContainersActor.start(id)`. It reads the spec, `await runtime.create(...)`, `await runtime.start(...)`, then writes `materialized=true`.
- **Unit B:** `ContainersActor.remove(id, force:)`, called concurrently by `compose down` or a second CLI.
- **Both legal because:** AD-7 says one actor per kind serializes mutations, and Swift 6 strict concurrency compiles both without warnings.
- **Divergence:**
  - Swift actors are reentrant at every `await`. While `start` is suspended in an XPC call that takes seconds, `remove` runs, deletes the spec and the Apple object, and returns. `start` then resumes and writes `materialized=true` for a spec that no longer exists, or creates `fl-<id>` again.
  - A different builder "fixes" it by holding the actor for the whole operation (a non-suspending lock or a serial executor). Now every container mutation is serialized globally: Compose `up` with 10 services boots one VM at a time, and `docker stop` waits behind a slow pull-free boot.
  - Two builders, two concurrency models, and neither one breaks AD-7.
- **Rule (tighten AD-7):**
  - Mutations are serialized **per object**, not per kind. Each object ID has an async mutex (FIFO) held across every `await` in the operation.
  - The kind actor only guards the map of those mutexes and the in-memory indexes.
  - Different objects of the same kind mutate concurrently.
  - Reads (`ps`, `inspect`) never take an object lock.

## P4 — Cross-kind check-then-act (HIGH)

- **Unit A:** `VolumesActor.remove("data")`. It asks the containers actor whether any container references `data`, gets "no", and deletes.
- **Unit B:** `ContainersActor.create(-v data:/x)`. It asks the volumes actor whether `data` exists, gets "yes", and commits the spec. (Docker semantics also allow it to create `data` implicitly when it's missing, which is a cross-kind write.)
- **Also:** `rm -v` (containers then volumes), `network rm` against attached containers, `rmi` against containers that use the image (see P6), and `network connect` while stopped against `network rm`.
- **Both legal because:** AD-7 gives each kind its own actor and says nothing about operations that span kinds.
- **Divergence:**
  - Interleaved, both succeed. The container now references a volume that's gone, and `start` fails with an Apple error that AD-11 maps to "the nearest Docker status."
  - Builders will pick different fixes: lock ordering, asking the other actor, or a store constraint. Some combinations deadlock under per-object locks (P3), with volume rm waiting on a container and container create waiting on a volume.
- **Rule (new AD, "references live in the store"):**
  - Every reference between Docker objects (container→network, container→volume, container→image ID, network→containers) is a row in `FLStore` with a foreign key.
  - Every check-then-act that crosses kinds is a single store transaction: existence, in-use and implicit create are checked and written atomically.
  - Actors never call another kind's actor to check an invariant.
  - When an operation needs runtime locks on objects of more than one kind, it takes them in a fixed order: network → volume → image → container, ascending ID within a kind.

## P5 — User `docker stop` vs restart controller (HIGH)

- **Unit A:** `ContainerService.stop` publishes `die` (exit 143 or 137) and then `stop`.
- **Unit B:** `RestartController`. On `die` with policy `always` or `unless-stopped`, it waits out the backoff and calls `ContainerService.start`.
- **Also:** the poller sees the same exit in its next snapshot.
- **Both legal because:** AD-6 says the poller emits only for changes "the daemon didn't cause" without saying how causality is known. AD-3 has no field for "manually stopped".
- **Divergence:**
  - **Causality race.** The poller's snapshot lands after the VM exits but before `stop` returns and records that the daemon caused it. The poller emits a second `die` with no "manual" marker. B treats it as a crash and restarts the container the user just stopped.
  - **Manual-stop flag has no home.** Docker ignores `always` after a manual stop until the daemon restarts, and ignores `unless-stopped` permanently. That flag isn't desired config, so it's arguably not in AD-3's spec. It isn't Apple runtime either. One builder puts it in the spec, another keeps it in memory, and the two disagree after a daemon restart (P9).
  - **Stale backoff.** B is sleeping in a backoff when the user runs `docker stop`. B wakes and calls `start`.
- **Rule (new AD, "intent ledger and generations"):**
  - Before calling the runtime, every core mutation records an expected transition `{id, from, to, generation}` under the object lock.
  - The poller suppresses any diff that matches an open expectation, and the service clears the expectation after publishing.
  - Every user-originated mutation increments the container's `generation`.
  - A controller action carries the generation it observed. The service rejects it with a stale-generation result if the generation has since moved, so controllers never use plain calls.
  - `manuallyStopped` is persisted (P7).

## P6 — "Created at docker start": first start or every start? (HIGH)

- **Unit A:** `ContainerService.start`. If `fl-<12hex>` exists it starts it, otherwise it creates it from the spec. This is cheap, and the writable layer survives as Docker requires.
- **Unit B:** `NetworkService.connect` on a stopped container. It edits only the spec, as AD-3 allows and AD-11 permits for stopped containers. `rename` does the same, and so would any future `update`.
- **Both legal because:** AD-3 says "the Apple container is created from the spec at `docker start`" without saying whether that is the first start or every one.
- **Divergence:**
  - Under A, a `network connect` done while stopped never reaches Apple, which has no connect (#4). The container restarts on its old networks while `inspect` shows the new one.
  - Builder C reads AD-3 as recreate on every start. Spec edits then apply, but every stop/start wipes the container filesystem, which breaks Docker semantics: databases, `apk add` state, and anything written in the container.
  - Lazy materialization also breaks things that assume an object exists:
    - `docker rmi` (image actor) sees no Apple container using the image, because the container was created but never started. It deletes the image, and `docker start` later fails, where Docker would have refused the `rmi`.
    - `docker cp` and `export` on a created container have no Apple object to act on.
- **Rule (tighten AD-3):**
  - The Apple container is created at first start and reused on later starts.
  - A spec field `materializedFrom: specHash` records what it was built from. Edits that Apple can't apply in place (network set, mounts, env) mark the spec `needsRecreate`.
  - On a start with `needsRecreate`, the service either recreates (when the image's rootfs is unmodified) or fails with 400 `fruitlocker: network connect on a stopped container requires recreate: …`. Pick one in the spine.
  - The image ID is resolved and stored in the spec at `create`.
  - `rmi` checks the spec's image references (P4), not Apple's.

## P7 — No home for daemon-observed state (HIGH)

- **Unit A:** `HealthController` keeps `{status, failingStreak, log}` in memory, keyed by Docker ID, and publishes `health_status`.
- **Unit B:** the `inspect` handler builds `State.Health`, `RestartCount`, `StartedAt`/`FinishedAt`, `ExitCode`, `OOMKilled` from `FLStore` (spec) plus a live apiserver read, which is all AD-3 allows.
- **Both legal because:** AD-3 says the spec holds desired config and the apiserver holds runtime status "never persisted as truth." AD-8 says controllers read the spec.
- **Divergence:**
  - `State.Health` and `RestartCount` are neither desired spec nor Apple runtime, so B can't see A's state.
  - Compose `depends_on: condition: service_healthy` reads health through `inspect`, so every healthy dependency hangs.
  - A probe exec that lands while the restart controller is cycling the container fails, so A counts a failure against the new run and flips it to `unhealthy`.
  - If a builder wires "unhealthy ⇒ restart" into either controller, the two controllers fight. Plain Docker never restarts a container for being unhealthy.
- **Rule (new AD, "observed state"):**
  - Add a third state class, **daemon-observed state**, persisted in `FLStore` in a separate table from the spec and written only by its named owner:
    - `HealthController` owns health.
    - `RestartController` owns restart count and backoff.
    - `ContainerService` owns `manuallyStopped`, `generation`, and the last exit code and times seen.
  - Observed state is keyed by `(dockerID, runEpoch)`. `runEpoch` increments on every start, and health resets on a new epoch.
  - Health never changes run state.
  - `inspect` = spec + observed + live runtime, assembled in a single core function.

## P8 — Who owns the DNS name table (HIGH)

- **Unit A:** `FLDNS`. It builds `name → [IP]` and `srcIP → (container, networks)` from EventBus payloads, plus a runtime read for IPs. It is an adapter and can't call core services.
- **Unit B:** the `inspect` handler, which emits `NetworkSettings.Networks[*].DNSNames`. That field exists from API 1.44, the spine's minimum, and lists name, short ID, hostname and aliases.
- **Unit C:** `NetworkController`, which keeps its own membership view for "last container" (P1).
- **Both legal because:** AD-8 lists Compose DNS as a controller, AD-9 puts answering in `FLDNS`, and AD-6 puts IPs only behind the poller. None of them names who *computes* the table.
- **Divergence:**
  - **Three membership views.** A uses the compose service label and `fl.aliases`, as the #4 prototype did. B uses Docker's rules. C counts spec attachments. They drift.
  - **Bridge network.** A serves names on Docker's `bridge` network. Docker's default bridge has no name resolution, so behavior differs from Docker.
  - **Stale source IPs.** A keeps `srcIP → container` after a stop. The IP changes on restart (#4), so when another container reuses that IP on the same network it inherits the old container's scope, and queries get wrong-project answers.
  - **Event payloads.** Docker events don't carry IPs, so A invents its own payload format and the bus schema forks.
- **Rule (new AD, "one DNS view"):**
  - `DNSViewController` in `FLCore` is the only code that computes the name table. It projects spec + observed + runtime IPs per *user-defined* network into an immutable, versioned `DNSView` that it pushes to `FLDNS` through a port.
  - `FLDNS` holds no derivation logic.
  - The names come from the same function that fills `DNSNames` in `inspect`.
  - A container's entries, its source-IP entry included, are removed on `willStop` or `die`, before its IP can be reused.
  - The `bridge` network gets forwarding only, never names.
  - `NetworkController` reads membership from the same projection.

## P9 — Daemon restart with running VMs (MEDIUM-HIGH)

- **Unit A:** the poller. Its first snapshot after boot is the baseline, so there is nothing to diff against and nothing is emitted.
- **Unit B:** `RestartController` acts only on `die` events.
- **Unit C:** `NetworkController` tracks bridges "by event, not by polling" (AD-10).
- **Both legal because:** AD-6 defines the poller as a diff engine, and AD-3 forbids persisting runtime as truth, so the previous snapshot is gone.
- **Divergence:**
  - **Missed exits.** A container that died while the daemon was down produces no `die`, so B never restarts it.
  - **Daemon-start semantics.** Docker starts `always` containers, and `unless-stopped` containers that weren't manually stopped, when the daemon starts, and clears the manual-stop flag for `always`. No unit owns that.
  - **No DNS.** The helper closed its copies when the connection dropped (AD-9), so every running network has lost its socket. C gets no "bridge up" event for a bridge that is already up, so it never rebinds, and DNS stays down until a container restarts.
  - **API before ready.** The API socket accepts requests before any of this has been reconciled.
- **Rule (new AD, "boot reconcile"):**
  - On start, `fruitlockerd` runs a reconcile phase before it opens the Engine API object endpoints. `/_ping`, `/version` and `/fruitlocker/v1/status` are served throughout (P12).
  - The poller publishes one synthetic `resync(snapshot)` to every controller. Each controller derives its state from spec + observed + snapshot rather than from event history, and the host observer reports current bridges and the mDNSResponder state.
  - The restart controller applies Docker's daemon-start rules from the persisted `manuallyStopped`.
  - Who starts `container-apiserver` when it isn't running is unassigned, given AD-2's ban on shelling out. Decide it.

## P10 — Join key: label vs ID prefix, and the 12-hex collision (MEDIUM)

- **Unit A:** the poller maps Apple → Docker by parsing `fl-<12hex>` and looking it up by prefix in `FLStore`.
- **Unit B:** the orphan sweeper (or the Apple-native classifier) maps by the `fl.docker.id` label (AD-3).
- **Unit C:** the ID minter, which checks only that the 64-hex ID is unique.
- **Both legal because:** AD-3 says the label is the back-reference, and AD-4 says the Apple ID is derived from the Docker ID. Both are true, so both are valid join keys.
- **Divergence:**
  - **Hand-made `fl-` objects.** A user runs `container run --name fl-0123456789ab`. A adopts it as a fruitlocker container. B calls it Apple-native.
  - **Prefix collisions.** C mints two IDs that share a 12-hex prefix. A store collision is about 50% likely around 2^24 objects, so it's rare but not impossible over a long-lived store, and any stale `fl-*` Apple object makes it a near-certainty for that prefix. The second `create` collides with Apple, or worse, A attaches the old Apple object to the new spec.
  - **Ambiguous lookups.** Handlers resolve `docker stop abc` differently. Docker's order is full ID, then exact name, then unique prefix, and an ambiguous prefix is an error.
  - **Hostname.** Apple's hostname defaults to `fl-<12hex>`, while Docker's default hostname is the short ID, which also appears in `DNSNames`.
- **Rule (tighten AD-4):**
  - The `fl.docker.id` label is the only Apple → Docker join key. The `fl-` prefix is reserved.
  - An Apple object with an `fl-` ID and no matching label is treated as foreign and never adopted.
  - The minter re-rolls until the 12-hex prefix is unique across every kind in `FLStore` and every Apple object the last snapshot listed.
  - One `Resolver` in `FLCore` applies Docker's lookup order, and every handler uses it.
  - The guest hostname comes from the spec (default: the short ID) and is never derived from the Apple ID.

## P11 — Crash between Apple create and store commit; Apple-native classification (MEDIUM)

- **Unit A:** `ContainerService.start` calls `runtime.create(fl-x, label)`, and the daemon crashes before it records `materialized`.
- **Unit B:** the Apple-native path (Consistency Conventions). Any Apple container without a spec shows in `docker ps` with a synthesized spec.
- **Unit C:** an orphan sweeper that deletes labeled Apple objects with no spec.
- **Both legal because:** the convention is tagged `[ASSUMPTION]` and doesn't say whether the synthesized spec is persisted. No AD covers write ordering.
- **Divergence:**
  - **One leftover, three treatments.** After a crash, B shows the leftover as a phantom Apple-native container and C deletes it. If a user had run `container stop` on a real fruitlocker container in the meantime, C could delete that too.
  - **Classification flips.** `docker rename` on an Apple-native container writes a spec, because AD-3 says names live only in the spec. From then on it looks fruitlocker-created, so restart, health and DNS start applying to a container fruitlocker never configured.
  - **Uncounted members.** A user attaches an Apple-native container to a fruitlocker-owned Apple network with Apple's CLI. `NetworkController`'s spec-based count ignores it, so the release-before-last-stop guard misfires (P1).
- **Rule (new AD, "provenance and write order"):**
  - **Write order.** Write the spec with `materialization=pending`, then create the Apple object, then mark it `materialized`. On boot, a labeled object whose spec is `pending` is adopted, and a labeled object with no spec is deleted.
  - **Provenance.** Each container's `origin ∈ {fruitlocker, apple}` is set the first time the daemon sees it and never changes. Specs synthesized for `origin=apple` are computed on read and never persisted.
  - **Allowed operations.** Mutations on `origin=apple` are limited to start, stop, kill, rm, logs, exec and inspect. Anything else returns 400.
  - **Counting.** Network membership counts are taken from runtime attachments, so they include Apple-native members.

## P12 — App channel: AD-12 "refuse to serve" vs AD-13 "only this socket" (MEDIUM)

- **Unit A:** the daemon's version gate. When the apiserver version is wrong it "refuses to serve", so it never binds the socket, or it answers every request with 500.
- **Unit B:** the app. It gets status, helper state and warnings only from `/fruitlocker/v1/*` over that socket (AD-13).
- **Unit C:** a `/fruitlocker/v1/networks` endpoint that returns DNS and bridge state per network, keyed by the Apple ID `fl-…` or by gateway IP.
- **Both legal because:** AD-12 and AD-13 are each followed to the letter, and nothing constrains the shape of `/fruitlocker/v1`.
- **Divergence:**
  - **Gated with no channel.** Under the gate, the app has no channel to learn *why* the engine refused. AD-12 says "tell the app why," and AD-13 forbids any other channel.
  - **Unjoinable keys.** The app joins C's data with Engine API objects keyed by 64-hex Docker IDs and can't match them.
  - **Second event stream.** One builder adds polling or a `/fruitlocker/v1` event stream for helper and DNS state. That is a second event path, which AD-6 was written to prevent.
- **Rule (tighten AD-12, AD-13):**
  - The socket is always bound. Under the gate, `/_ping`, `/version` and `/fruitlocker/v1/*` work normally and every other endpoint returns 503 with `fruitlocker: engine unavailable: <reason>`.
  - `/fruitlocker/v1` never lists or embeds Docker objects. It may reference one only by its full Docker ID, and per-object extras live under `/fruitlocker/v1/<kind>/<dockerID>/…`.
  - Changes to engine-only state are published on the same `EventBus`, and appear in `/events`, as `Type=daemon` events with `fl.*` attributes.

## P13 — Who emits which event (MEDIUM)

- **Unit A:** `ContainerService.start` emits network `connect` for each attachment, then container `start`.
- **Unit B:** `NetworkController` emits network `connect` when it sees the container's bridge come up.
- **Both legal because:** AD-6 says any mutation the daemon performs publishes "its" event, without saying whose mutation an attachment is. Separately, "at the moment it happens" doesn't say whether that is before or after the runtime call returns.
- **Divergence:**
  - **Duplicate events.** `/events` gets two `connect` events, or none if each builder assumed the other would emit it.
  - **Phantom events.** One builder publishes `start` before the runtime call and the call fails. Another publishes after the store write.
  - **Order guarantees.** Compose and other `/events` consumers see a different order of `create`, `connect` and `start` depending on which unit runs first.
- **Rule (tighten AD-6):**
  - Add an emitter table to Consistency Conventions: one row per Docker event `(Type, Action)` naming its single emitting unit.
  - Events are published only after the runtime call succeeds *and* the store write commits.
  - For each object, the bus delivers events in publication order. Network `connect` and `disconnect` are emitted by `ContainerService` inside the start and stop operations.

---

## Smaller holes

- **Helper absent.** The user can refuse the admin prompt, and #5 says approach 2 (Apple alias DNS) is the answer then. The spine never mentions it. One builder fails `compose up` loudly (AD-11's spirit) and another silently ships without names. Rule: with no helper, Compose networks get no names, a `/fruitlocker/v1` warning, and one `Type=daemon` event. Whether approach 2 ships is a decision for the spine to record.
- **AD-7 vs AD-6.** AD-7 says only "core services" call runtime ports, and AD-6 has the poller read the apiserver. Name the poller as a core service, or the one exception.
- **Default `bridge` bootstrap.** Nothing owns creating the fruitlocker `bridge` network on first boot, or minting its ID, or says whether Apple's `default` is hidden from `docker network ls`. Two builders will answer differently.
- **Shared named volumes.** Compose often mounts one volume into several services. Whether Apple volumes can be mounted by two running VMs at once is unverified. If they can't, VolumeService and ContainerService need a rule (fail loudly per AD-11). Check it before building volumes.
- **`/events?since=`.** It needs a bounded history buffer on the in-process bus. Set its size and say who owns it, or two consumers will get different replay behavior.

## Not challenged

AD-1, AD-2, AD-5, AD-14 and AD-15 produced no divergent pair under this lens.
