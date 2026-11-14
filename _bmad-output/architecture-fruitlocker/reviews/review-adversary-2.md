---
lens: adversary (round 2)
target: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md (21 ADs, post round 1)
date: 2026-11-13
---

# Adversarial review, round 2: fruitlocker v1 spine

## Verdict

**Closer, still not a build substrate.** Round 1's holes are mostly closed in name: there is a lock, a ledger, a hook, an observed table. But the new rules don't say how they interact. The worst gap is NetworkLifecycle (AD-10). The spine never says which lock the hooks run under, so any reading of it either deadlocks against AD-7 or lets the #402 wedge back in. Next come the shape of AD-3's observed table (runEpoch keying breaks restart count and ports), intent-ledger entries that outlive a crash, and the die path, which has two emitters. Every finding below is a pair of units that each follow the text exactly and still don't fit together.

Format per finding: **A / B** (two units one level down), **Legal because** (the AD text each follows), **Divergence**, **Rule** (the AD to add or tighten).

---

## Critical

### F1: NetworkLifecycle hooks have no lock, so the lock order either deadlocks or doesn't serialize (AD-7 × AD-10)

- **A:** `ContainerService.start(c1)` takes c1's lock (AD-7), then awaits `NetworkLifecycle.willStart` (AD-10). `NetworkController` has to serialize per network so that concurrent last-stops can't both skip release. The natural choice is the network object lock for `netA`.
- **B:** `NetworkService.disconnect(netA, c1)` on a stopped c1. That's a spec edit (AD-11), so it takes `netA` and then `c1`, per AD-7's network → container order.
- **Legal because:** AD-7 gives a lock order and a per-object FIFO mutex. AD-10 says the hook is awaited before the runtime call, which means it runs while the container lock is held. Nothing says what the hook may lock.
- **Divergence:** A holds c1 and wants netA; B holds netA and wants c1. That's a deadlock, and `planRecreateNetworks` (stop, disconnect, rm, create, connect, start) makes the interleaving routine. If start instead takes netA up front per the order, then willStart re-takes netA on a non-reentrant FIFO mutex and deadlocks on itself. If the builder avoids both by giving the hook no lock at all, the result is F2.
- **Rule (tighten AD-7 and AD-10):** "NetworkLifecycle state is guarded by a per-network *lifecycle mutex*. It is a leaf lock: it ranks after container in the AD-7 order, and no AD-7 object lock is ever acquired while holding it. A hook that touches several networks takes their lifecycle mutexes in ascending network ID. Hooks never call a core service that takes an object lock."

### F2: The count and bind/release decisions race each other, and the loser leaves `:53` bound (AD-10 × AD-6 × AD-9)

- **A:** The hook path: `willStop(c_last)` sees count reach 0, releases, and returns.
- **B:** The event path: `NetworkController` reacts to a `HostNetObserver` bridge-up event (AD-6 puts it on the bus) and binds, because "bridge up and mDNSResponder holds `udp4 *:53`" (AD-10).
- **Legal because:** AD-10 says bind when the bridge is up and mDNSResponder holds `*:53`, and release in willStop. It counts "from runtime attachments", and its rule says nothing about stops in flight.
- **Divergence (each one breaks AD-10's Prevents line):**
  1. c1 starts and its bridge-up event is queued. The user stops c1 at once: willStop releases (nothing is bound yet), then the queued bridge-up handler runs, sees bridge up and mDNS holding `*:53`, and **binds**. c1 stops, the bridge drops, mDNSResponder releases `*:53` while the helper's socket holds `<gw>:53`. That's the #402 window the spike rule exists to prevent.
  2. c1 and c2 are the last two on netA and get stopped concurrently (different container locks, so this is legal). Both willStop calls read count = 2 from runtime attachments, because neither VM has stopped yet. Neither thinks it's last, so neither releases.
  3. willStop(last) releases, then `runtime.stop` fails or times out and the container keeps running. No bridge event fires, so nothing ever rebinds. The Compose names for a running container stay dead until the next restart. The mirror case: willStart reserves, `runtime.start` fails, and the count is now too high, so a later true last-stop never releases.
  4. `NetworkController` is a reentrant actor. Two bind triggers for one gateway interleave across the helper XPC `await`. With `SO_REUSEADDR`, **both binds succeed**, so the daemon holds two fds and release closes only one. That's AD-9's "forgotten duplicate fd".
- **Rule (tighten AD-10, AD-9):**
  - "Every bind or release decision, whether from a hook, a `HostNetObserver` event or the backstop, runs under the network's lifecycle mutex (F1) and is recomputed from current state, never from an event's payload."
  - "The count is joined containers that are running or starting, minus those stopping. willStart and willStop reserve. A mandatory `didStart`/`didStop(ok | failed)` settles each reservation, and a failed one re-runs the guard."
  - "Bind only while count > 0 and no stop is reserved."
  - "`FLDNS` holds at most one socket per gateway: a second handover for a gateway it already holds is closed at once and logged."

### F3: Open intent-ledger entries outlive a crash and mute the backstop (AD-6 × AD-16 × AD-10)

- **A:** `ContainerService.stop(c1)` writes a ledger entry `{c1, running, stopped, g}` to `FLStore` and the daemon crashes before closing it.
- **B:** The poller after reboot. It "suppresses diffs that match an open entry".
- **Legal because:** AD-6 defines the entry as `{id, from, to, generation}` and gives it no epoch, no expiry and no boot handling. AD-16 step 5 takes a silent baseline and says nothing about the ledger.
- **Divergence:** At boot, step 8 restarts c1 (`always`). Days later c1 crashes: the poller sees running → stopped, which matches the stale entry, and suppresses it. No `die` is published, RestartController doesn't restart, and the AD-10 backstop (which fires on an unexpected `die`) never releases. If c1 was the network's last container, `<gw>:53` stays bound across mDNSResponder's release. That's the wedge.
- **Rule (tighten AD-6, AD-16):** "A ledger entry is `{dockerID, runEpoch, op, from, to, generation}` and matches only a diff on the same `runEpoch`. Boot step 5 resolves every open entry against the snapshot (completing it or rolling it back) before the baseline is taken. No entry survives boot."

---

## High

### F4: Observed keyed by `(dockerID, runEpoch)` can't hold the fields that span runs (AD-3 × AD-8 × AD-16)

- **A:** `ContainerService.start` bumps `runEpoch` (AD-3, "goes up on every start") and creates the new observed row. It owns only its own fields, so it doesn't copy `restartCount` or backoff.
- **B:** `RestartController` reads `restartCount` and backoff from the current epoch's row (it owns those fields per AD-3).
- **Legal because:** AD-3 keys observed state by `(dockerID, runEpoch)` and gives every field exactly one owner.
- **Divergence:**
  - Every restart lands in a fresh row with `restartCount = 0`, so `on-failure:3` never reaches 3 and restarts forever. Backoff resets too.
  - `manuallyStopped` and `generation` are per-container facts, but they sit in a per-run row. Boot step 8 reads `manuallyStopped` from whichever row the builder decided is "latest".
  - Docker resets the restart count on a *user* start, but the `start` event that RestartController sees doesn't say whether the user or the policy started the container.
  - Restart actions carry only `generation`, and policy starts don't bump it. So a restart scheduled from a `die` and another from the boot `resync` (F8) are both valid, and the container is started twice.
- **Rule (tighten AD-3, AD-8):**
  - "Observed is two tables. `container_observed(dockerID)` holds `generation`, `manuallyStopped`, `restartCount`, backoff and host-port allocations. `run_observed(dockerID, runEpoch)` holds health, start and exit times, and the exit code. Each column has one writer."
  - "The `start` event carries `fl.cause=user|policy|boot`."
  - "A restart action carries `(generation, runEpoch)` and is rejected unless both still match."

### F5: Ephemeral ports are allocated per start but baked in per Apple object (AD-19 × AD-3)

- **A:** `ContainerService.start` allocates `-P` and `0` host ports "at start into observed state" (AD-19). With F4's runEpoch keying, that's a new allocation on every start.
- **B:** The `FLAppleRuntime` create path publishes ports "when the container materializes" (AD-19). The Apple container is "created at first start and reused after that" (AD-3).
- **Legal because:** both sentences are in AD-19, and AD-3 lists ports among the edits Apple can't apply in place.
- **Divergence:** On the second start, observed says port P2 while the reused Apple object publishes P1, so `inspect` lies. If the builder treats P2 ≠ P1 as a ports change, `needsRecreate` fires and **every restart of a `-P` container wipes its writable layer.** Neither choice frees P1, so while c1 is stopped another container's start can be given P1, and c1's next start fails with a port conflict it didn't cause. Two concurrent starts of different containers (different locks, so legal) can also both choose the same free port, because the spine names no uniqueness point.
- **Rule (tighten AD-19):** "Ephemeral host ports are allocated when an Apple container is created (first start or recreate). They're stored per materialization in a `host_ports` table with a UNIQUE `(hostIP, hostPort, proto)` constraint, inserted in the same transaction as the materialization write. They're kept across stops and freed only on recreate or destroy. A plain start never allocates."

### F6: Two emitters for one `die` (AD-6 emitter table × `ClientProcess.wait`)

- **A:** `ContainerService` awaits `ClientProcess.wait` for the init process it bootstrapped (AD-6: "the fast path"). When the wait returns, it records the exit and emits `die`. Every container's init was started by the daemon, crashes included.
- **B:** The poller. It diffs its previous snapshot against the current one and emits the "unexpected" `die` (emitter table).
- **Legal because:** AD-6 names the wait as the fast path for daemon-started processes, and the table gives unexpected dies to the poller. The spine never says who consumes the wait, or when a ledger entry closes.
- **Divergence:**
  - A crash produces two `die` events, one from each emitter.
  - On a normal `docker stop`, ContainerService closes its intent when it commits. If the poller's next tick still sees running → stopped against its *previous snapshot*, there's no open entry left, so it emits a second `die`.
  - If the builder makes the poller the only path for crashes instead, the AD-10 backstop and RestartController both wait for a poll interval, which widens the #402 window.
- **Rule (tighten AD-6):**
  - "Exactly one `die` per `(dockerID, runEpoch)`. Whichever path first records the exit for that epoch in `run_observed` emits it, and any later path is a no-op."
  - "The wait result feeds the same record-exit function the poller uses."
  - "The poller diffs runtime against *observed* state, not against its last snapshot."

### F7: Recreate has no write order, no identity rule and no ledger shape (AD-3 × AD-4 × AD-6 × AD-16)

- **A:** `ContainerService.start` on a `needsRecreate` container: it deletes the old Apple container, then creates the new one, reusing the Apple ID.
- **B:** A second builder plays it safe: mint a new `fl-` ID, create, then delete the old one.
- **Legal because:** AD-3 gives a write order for the *first* materialization only (pending → create → materialized). AD-4 mints Apple IDs but never says whether a recreate keeps one. The AD-6 ledger expresses run-state transitions (`from → to`), not create or delete.
- **Divergence:**
  - A crashes between delete and create. The spec says `materialized` but no Apple object exists, and the AD-16 sweep handles only "pending spec" and "no spec", so this state matches neither.
  - B crashes between create and delete. Two Apple objects carry the same `fl.docker.id`, and AD-4 says that label is the only join key.
  - Both builds make the poller see an Apple destroy and create that no ledger entry can describe, so it publishes phantom events or drops real ones.
- **Rule (tighten AD-3, AD-16):**
  - "A recreate writes `spec.state = recreating{oldAppleID, newAppleID}` before any Apple call. Create new, delete old, then mark materialized with the new `specHash`."
  - "Ledger ops include `materialize` and `dematerialize`."
  - "Boot sweep: for `recreating`, finish forward; for materialized-but-missing, set `needsRecreate`; when two labeled objects share one Docker ID, keep the one the spec names and delete the other."

### F8: AD-8, AD-10 and AD-21 contradict each other on DNS membership, and the `bridge` network falls between them

- **Contradiction 1, AD-8 vs AD-21:** AD-8 says "the only [pre-mutation hook] allowed is `NetworkLifecycle`", and `NetworkController` implements it. AD-21 has `DNSViewController`, a different controller, remove entries "on `willStop`". There's no event before a stop (AD-6 publishes only after runtime success), so a legal `DNSViewController` can't see willStop. Builder A has NetworkController call DNSViewController, which breaks AD-8's "act only through core services". Builder B removes entries on the `stop` event, *after* the VM is gone, which breaks AD-21's timing.
- **Contradiction 2, AD-10 vs AD-21:** AD-10 counts "from runtime attachments", while AD-21 says "`NetworkController` reads membership from the same projection". The projection covers *user-defined* networks only. A NetworkController built on the projection never counts `bridge` members. Depending on the builder, it either never binds `bridge` or binds it and never releases it, and the second is a #402 wedge on the network every plain `docker run` uses. A NetworkController built on runtime attachments binds `bridge`'s gateway for an FLDNS that has no view for it.
- **Rule (tighten AD-8, AD-10, AD-21):**
  - "NetworkLifecycle hooks call `DNSViewController.withdraw(container)` synchronously before returning. That's the one allowed controller-to-controller call."
  - "Membership for counting is AD-21's projection, extended to every fruitlocker network."
  - "The `bridge` gateway is never bound. Guests on `bridge` use mDNSResponder, as Docker's default bridge uses the host's resolver."

### F9: Two definitions of "in use" break Compose's network recreate (AD-7 × AD-3 × AD-11)

- **A:** `NetworkService.remove(netA)` checks for references with AD-7's foreign-key rows in one transaction, finds none (Compose just disconnected the stopped containers), and deletes the Apple network.
- **B:** The stopped container's Apple object. Disconnect only edited the spec and set `needsRecreate` (AD-3, AD-11), so the Apple container is still materialized with `netA` attached.
- **Legal because:** AD-7 defines references as spec FK rows, and AD-3 defers the Apple change to the next start.
- **Divergence:** Compose v5's `planRecreateNetworks` (stop, disconnect, rm, create, connect, start) runs on every network config change. Apple either refuses the network delete because a materialized container is attached, which surfaces to Compose as a Docker error, or it deletes the network and leaves an Apple container pointing at nothing. Which one happens needs checking against 1.7.1, but neither is specified.
- **Rule (tighten AD-7):** "In-use for a network or volume is spec references *plus* materialized Apple attachments. `network rm` dematerializes (F7) any stopped container whose only remaining link is a stale materialized attachment, taking locks network → container, before the Apple delete."

### F10: Boot order is undercut by the step-5 resync, and it never re-runs (AD-16 × AD-8 × AD-12)

- **A:** `RestartController` reacts to the synthetic `resync` at step 5 the way it reacts to any state change. It sees an exited `always` container and starts it.
- **B:** Boot steps 6 (sweep), 7 (DNS rebind) and 8 (daemon-start restart rules).
- **Legal because:** AD-16 step 5 publishes `resync` "to every controller", and AD-8 says controllers subscribe and act.
- **Divergence:**
  - Restarts run before the sweep and before the DNS rebind. That's the exact ordering steps 6–8 exist to prevent. Step 8 then starts the same containers a second time.
  - The resync is computed before the sweep adopts pending objects, so adopted containers are invisible to every controller until their next event.
  - AD-10 creates `bridge` "on first boot", but the step isn't in the AD-16 order.
  - AD-12 re-checks the gate on apiserver reconnect but never re-runs steps 5–8. Exits during an apiserver outage show up either as a burst of unexpected dies, which skips the DNS-before-restart order, or silently.
- **Rule (tighten AD-16):**
  - "Controllers are inert until their own step. The resync is sent after the sweep. Step 8 is the only daemon-start restart path."
  - "Insert 'ensure `bridge`' between steps 6 and 7."
  - "An apiserver reconnect re-runs steps 3 and 5–8, with object endpoints returning 503 until it finishes."

---

## Medium

### F11: The poller and the container locks (AD-6 × AD-7 × AD-3)

`last exit` is owned by `ContainerService` (AD-3), and AD-6 publishes only after the store commits. So the poller has to record a crash by calling `ContainerService` under c1's lock. But a `docker stop -t 300` holds that lock for five minutes, and the poller is the "only code that reads Apple on a timer". One slow stop then stalls crash detection for every container, and with it the backstop. The obvious F6 fix ("close the intent once the poller confirms it") makes stop wait on the poller while the poller waits on stop's lock, which deadlocks. **Rule (AD-6):** "The poller never awaits an object lock. It hands observations to a per-object record task. Closing a ledger entry never waits on the poller."

### F12: `specHash` and "first network" have no canonical form (AD-3 × AD-19 × Compose)

At API ≥ 1.44, Compose sends `EndpointsConfig` as a JSON object, and the order of a Go map isn't stable. One builder calls "first network" the first key in the JSON, another the first by name. They disagree on where ports land (AD-19) and on what `inspect` reports. And if `specHash` hashes the raw spec, a reordered map, a label change or `update --restart` all set `needsRecreate` and wipe the writable layer. **Rule (AD-3, AD-19):** "`specHash` is computed over the canonical Apple `ContainerConfiguration` the spec produces, and nothing else. Network order is `gw_priority` descending, then network name. 'First network' means first in that order."

### F13: Foreign containers inflate the count (AD-4 × AD-10)

AD-10 counts "from runtime attachments", and the `container` CLI can attach an Apple-native container to an `fl-` network. AD-4 hides that container, so the poller publishes nothing when it stops. The result: fruitlocker's real last container stops with count 1, nothing is released, then the foreign container stops with no `willStop` and no `die`, and `<gw>:53` is still held. **Rule (AD-10):** "Count only joined containers (AD-4). The backstop also releases when a bridge's runtime attachment set has no joined container."

### F14: The single-connection helper blocks the daemon's own restart (AD-1 × AD-16 step 7)

If the daemon crashes, launchd restarts it within seconds. The helper may not have seen the old XPC connection invalidate yet, and it "rejects a second" connection (AD-1). Step 7's rebind then fails, and Compose names stay down for running containers. **Rule (AD-1):** "A new connection that passes the AD-9 peer check replaces the current one. The helper holds no state, so nothing is lost."

### F15: `rmi -f` versus a pending recreate (AD-5 × AD-7 × AD-3)

`ImageService` implements Docker's `rmi -f` on an image that a stopped container uses. One builder untags, another deletes from Apple's store; the FK row only blocks a non-force delete. A `needsRecreate` container can't be recreated without its image, so the next start fails. **Rule (AD-7):** "An image referenced by any container spec is never deleted from Apple's store. `-f` untags only."

### F16: The stale source-IP scope window is still open on crashes (AD-21 × AD-6)

On an unexpected exit, the entry is removed on `die`, and the poller can be a poll interval late with it (F6). If Apple gives the same IP to a new container on another network inside that interval, the new container's queries resolve with the dead container's scope. That's the cross-network leak AD-21 lists under Prevents. **Rule (AD-21):** "Source-IP entries are keyed by `(IP, network)`. They're installed from the starting container's runtime IPs inside its start operation, before the `start` event, and installing one atomically replaces any prior entry for that IP."

## Low

- **F17: The emitter table isn't total (AD-6).** It's missing container `restart`, `pause`/`unpause`, `exec_create`/`exec_start`/`exec_die`, `attach`, `resize`, the `prune` actions, and the `Type=daemon` action names. Meanwhile AD-3 has `ContainerService` emit a `Type=daemon` recreate event that the table assigns to "owning controller". Two builders will both claim `restart`. **Rule:** "The table lists every action the Engine API can emit. An action that isn't listed can't be emitted. `Type=daemon` rows list their `fl.*` action and emitter."
- **F18: Connect and disconnect have two writers (AD-7 × AD-11).** `NetworkService` handles `/networks/<id>/connect`, while `ContainerService` writes attachments at create and emits `connect`. **Rule:** "`ContainerService` owns container→network rows. `NetworkService` calls it, under locks taken network → container."
- **F19: Torn `inspect` (AD-3 × AD-7).** Reads take no lock, so spec and observed read in separate statements can straddle a recreate. **Rule:** "The `inspect` assembler reads spec and observed in one store read transaction."

## Probes that hold against the current text

- AD-16 does put DNS rebind (step 7) before restart rules (step 8). F10 is about the step-5 resync getting around that order, not the order itself.
- Kernel close on a daemon crash (AD-9) releases the socket correctly. A crash can't leave `<gw>:53` held, though F3 and F13 can.
