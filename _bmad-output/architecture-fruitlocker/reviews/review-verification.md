# Verification review: fruitlocker v1 architecture spine

- **Lens:** Was each committed technical decision checked against primary sources, or asserted from memory?
- **Reviewed:** `architecture-fruitlocker.md` and `.memlog.md`, branch `10-architecture`, 2026-11-13
- **Method:** `gh api` against tagged source (not READMEs where code was available), Apple doc JSON, web search. Local host checked too: `swift --version` 6.4.2, Xcode 27.2, macOS 26.7.3, `container --version` 1.7.1.

## Verdict

All the Stack versions are real and current. Several fit claims are wrong or only half right once you read the 1.7.1 and v5.7.1 source. Two decisions (AD-14, AD-12) rest on assumptions that ContainerAPIClient 1.7.1 contradicts. AD-3 has an unstated gap that Compose v5's network-recreate path will hit. Hijack is feasible on Hummingbird, but not with the stock upgrade handler.

## Findings (ordered by severity)

### F1 — HIGH — AD-14 can't be built on ContainerAPIClient 1.7.1

- **Wrong:** AD-14 says the daemon uses `X-Registry-Auth` for the request in hand only. `ClientImage.pull(reference:platform:scheme:containerSystemConfig:progressUpdate:maxConcurrentDownloads:)` and `push(platform:scheme:containerSystemConfig:progressUpdate:)` take no credentials at all.
- **Evidence:**
  - The images helper (`ImagesService.withAuthentication`) gets auth only from its own process environment (`authenticationFromEnv(host:)`), then from the keychain (`KeychainHelper(securityDomain: Constants.keychainID).lookup(hostname:)`).
  - So per-request auth can't be passed through. Making it work would mean writing the credentials into Apple's keychain, which is persisting them and breaks AD-14.
  - Sources:
    - https://github.com/apple/container/blob/1.7.1/Sources/Services/ContainerAPIService/Client/ClientImage.swift (lines ~254–295, ~423–444)
    - https://github.com/apple/container/blob/1.7.1/Sources/Services/ContainerImagesService/Server/ImagesService.swift (lines ~431–455)
- **Fix:** Pick one of these and record it in AD-14:
  - (a) Anonymous pulls go through Apple. Authenticated pull and push fail loudly under AD-11 until Apple accepts per-request auth (file an upstream issue).
  - (b) The daemon does registry transfer itself with Containerization's `RegistryClient`, then calls `ClientImage.load`. AD-5 still holds, but the work is bigger.
  - (c) Rely on `container registry login` keychain entries, and say plainly that `docker login` creds aren't used.

### F2 — HIGH — AD-12's compatibility claim doesn't cover images

- **Wrong:** AD-12 assumes everything `ContainerAPIClient` does falls under "the apiserver's 1.x XPC promise". It doesn't.
  - `ContainerClient`, `NetworkClient`, `ClientVolume`, `ClientProcess` and `ClientHealthCheck` talk to `com.apple.container.apiserver`.
  - `ClientImage` talks straight to `com.apple.container.core.container-core-images`.
- **Evidence:**
  - The README says: "The `container-apiserver` XPC API compatibility preserves forward and backward compatibility within a major version. Other non-public XPC helpers do not guarantee CLI or API compatibility across different versions."
  - Every image operation (pull, push, tag, list, delete, load, save, and so AD-4's image IDs) goes through that uncovered helper.
  - Sources:
    - https://github.com/apple/container/blob/1.7.1/README.md (lines ~105–108)
    - https://github.com/apple/container/blob/1.7.1/Sources/Services/ContainerAPIService/Client/ClientImage.swift (line 97)
- **Fix:** Rewrite AD-12. The `>=1.7.1, same major` gate covers the apiserver only. Image paths are guaranteed only on the tested Apple version. Either gate on an exact or allow-listed `container` version, or warn and degrade image endpoints when the installed version differs from the tested one. Add an image smoke test to the compatibility matrix for every Apple release.

### F3 — HIGH — AD-3 doesn't say what happens when a materialized container's spec changes; Compose v5 depends on it

- **Wrong:** AD-3 covers spec edits *before* first start only.
  - Apple's `ContainerConfiguration.networks` is set at `create`. 1.7.1 has no update route (routes: containerList, Create, Bootstrap, CreateProcess, StartProcess, Wait, Delete, Stop, Dial, Resize, Kill, State, Logs, Event, Stats, DiskUsage, CopyIn, CopyOut, Export, Clean).
  - Compose v5.7.1 `planRecreateNetworks` runs **stop → network disconnect → remove/create network → network connect → start** on *existing, previously started* containers. Its comment says "they keep their identity and are not recreated: a network definition change alone is not a reason to lose container state."
  - On Apple, that means deleting and recreating the Apple container, which throws away its writable rootfs.
- **Evidence:**
  - https://github.com/docker/compose/blob/v5.7.1/pkg/compose/reconcile.go (lines ~320–420)
  - https://github.com/docker/compose/blob/v5.7.1/pkg/compose/executor_ops.go (lines 54–68)
  - https://github.com/apple/container/blob/1.7.1/Sources/Services/ContainerAPIService/Client/XPC+.swift (`enum XPCRoute`)
  - https://github.com/apple/container/blob/1.7.1/Sources/ContainerResource/Container/ContainerConfiguration.swift
- **Fix:** Add a rule to AD-3:
  - The Apple container is created at *first* start and reused on later starts.
  - A spec change that needs re-materialization (network attach set, anything else fixed at create) on a container that already has an Apple object is either (i) applied by recreate, explicitly documented as losing the rootfs (and maybe logged as a compat warning), or (ii) rejected under AD-11.
  - Decide which, because Compose will hit it whenever a network's config changes.
  - Also: AD-11's ban on `network connect`/`disconnect` for *running* containers is safe for Compose. At API ≥1.44 Compose only calls connect/disconnect after stopping. Below 1.44 it connects after create and before start (`service_containers.go` ~264–282).

### F4 — MEDIUM — "Hummingbird hijack fit" is feasible, but the stock upgrade path rejects Docker's exec request

- **Confirmed:**
  - Hummingbird 2.28.1 binds Unix sockets (`BindAddress.unixDomainSocket(path:)`, via POSIX `ServerBootstrap`, with `cleanupExistingSocketFile: true`).
  - It sets `allowRemoteHalfClosure: true` on child channels, which Docker's `CloseWrite` needs.
  - It lets you plug in a custom `ServerChildChannel` through `HTTPServerBuilder`. `hummingbird-websocket` 2.8.1's `HTTP1WebSocketUpgradeChannel` is the pattern to copy.
- **Wrong:** The obvious build is a `NIOTypedHTTPServerUpgradeHandler` with a `tcp` upgrader, and it fails on `POST /exec/{id}/start`.
  - The moby client sends `Connection: Upgrade`, `Upgrade: tcp` *with a JSON body* (`ExecStartRequest{Detach,Tty,ConsoleSize}`).
  - NIO 2.105.0's upgrader state machine returns `invalidHTTPOrdering` on any body part in an upgrade request.
  - Unix sockets also aren't available with `NIOTSListenerBootstrap`, so the Hummingbird app must use the POSIX event-loop group.
- **Evidence:**
  - https://github.com/hummingbird-project/hummingbird/blob/2.28.1/Sources/HummingbirdCore/Server/Server.swift (lines ~250–300, 362)
  - https://github.com/hummingbird-project/hummingbird/blob/2.28.1/Sources/HummingbirdCore/Server/ServerChildChannel.swift
  - https://github.com/hummingbird-project/hummingbird-websocket/blob/2.8.1/Sources/HummingbirdWebSocket/WebSocketChannel.swift
  - https://github.com/apple/swift-nio/blob/2.105.0/Sources/NIOHTTP1/NIOTypedHTTPServerUpgraderStateMachine.swift (lines ~205–226)
  - https://github.com/moby/moby/blob/client/v0.6.2/client/container_exec.go (lines 132–144)
  - https://github.com/moby/moby/blob/client/v0.6.2/client/hijack.go (lines 18–50)
- **Fix:** Change the Deferred note to "custom hijack `ServerChildChannel`":
  - Route the request and read head plus full body through the normal HTTP1 decoder.
  - Write `101 UPGRADED` (or `200` with `application/vnd.docker.raw-stream` / `multiplexed-stream` when there's no Upgrade header).
  - Then remove the HTTP codec handlers and hand over the raw channel.
  - The first attach/exec story should test exec with a body, and stdin half-close.

### F5 — MEDIUM — Passing daemon-owned stdio at bootstrap couples container output to fruitlockerd's lifetime

- **Not addressed by the spine:**
  - `ContainerClient.bootstrap(id:stdio:)` is the only way to get the init process's streams. Attach-before-start, which Compose `up` uses, needs the daemon to pass its own pipes there.
  - The runtime tees them with `MultiWriter(handles: [h, containerLog])`, and `write` throws on the first failing handle.
  - If fruitlockerd exits (crash, Sparkle update, `launchctl kickstart`), writes to the dead pipe fail *before* the log-file write. Apple's log then stops getting output.
  - A slow reader also back-pressures the container's stdout.
  - Apple's log merges stdout and stderr with no timestamps, so `docker logs --timestamps`, `--since` and stream demux can't come from it.
- **Evidence:**
  - https://github.com/apple/container/blob/1.7.1/Sources/Services/RuntimeLinux/Server/RuntimeService.swift (lines ~243–262, `struct MultiWriter`)
  - https://github.com/apple/container/blob/1.7.1/Sources/Services/ContainerAPIService/Client/ContainerClient.swift (lines 123–160, 268–290)
- **Fix:** Add a convention, or a short AD, on stream ownership and spike it.
  - Option: the daemon owns logs (writes its own json-file-style log with stream tags and timestamps) and a supervisor keeps the pipe readers alive across restarts.
  - Option: detached containers get `nil` stdio, logs come from `logs(id:)`, and attach-before-start and `-it` accept the coupling.
  - Either way, test that a daemon restart doesn't wedge or silence running containers.

### F6 — MEDIUM — The root helper's XPC listener has no peer validation

- **Not addressed:**
  - AD-9 has a root process handing bound `:53` sockets to whoever asks over XPC, and nothing says the helper checks its caller.
  - The API exists: `xpc_connection_set_peer_code_signing_requirement` (macOS 12+), and `XPCPeerRequirement` for the Swift `XPCListener`/`XPCSession` API (macOS 26+, matching the deployment target).
- **Confirmed:**
  - fd passing works. `xpc_fd_create` is available on macOS 10.7+ and "performs the equivalent of a dup(2)".
  - apple/container's own `XPCMessage.set(key:value: FileHandle)` uses `xpc_fd_create`/`xpc_fd_dup` across processes.
- **Corollary:** Because of the dup, the helper "closing its copy" doesn't release the bind. The daemon's copy keeps `<gateway>:53` bound. AD-10's "release before last container stops" has to close the **daemon's** fd as well.
- **Evidence:**
  - https://developer.apple.com/documentation/xpc/xpc_fd_create(_:)
  - https://developer.apple.com/documentation/xpc/xpc_connection_set_peer_code_signing_requirement(_:_:)
  - https://developer.apple.com/documentation/xpc/xpcpeerrequirement
  - https://github.com/apple/container/blob/1.7.1/Sources/ContainerXPC/XPCMessage.swift (lines 231–275)
- **Fix:**
  - Add to AD-9: the helper accepts only peers whose signature matches Team ID + `sh.jawr.fruitlocker.daemon`, and the daemon checks the helper the same way.
  - Add to AD-10: release means the daemon closes its fd, and the helper closes its own.

### F7 — LOW — AD-4's image ID choice doesn't match Docker 29 and costs an extra lookup

- **Questionable:**
  - "Image IDs are the Apple image config digest" copies Docker's *classic* store.
  - Docker 29 defaults new installs to the containerd image store, where the image ID is the manifest/index digest.
  - That digest is exactly what Apple's `ImageDescription.descriptor.digest` already is.
  - Getting a config digest needs `manifest(for: platform)`, which is per platform and is another image-helper call (see F2).
- **Evidence:**
  - https://docs.docker.com/engine/release-notes/29/
  - https://github.com/moby/moby/issues/51779
  - https://github.com/apple/container/blob/1.7.1/Sources/ContainerResource/Image/ImageDescription.swift
- **Fix:** Use `descriptor.digest` as the image ID, matching Docker 29's containerd-store default. Or keep the config digest, but record why.

### F8 — LOW — The Engine API row holds up, but the decision log is wrong about what docker 29.9.3 serves

- **Confirmed (the `[ASSUMPTION]` tag can come off):**
  - docker CLI v29.9.3 vendors `moby/moby/client v0.6.2` and `api v1.56.1`, and Compose v5.7.1 pins the same. That client's `MaxAPIVersion = "1.56"` and `MinAPIVersion = "1.40"`.
  - Negotiation downgrades to whatever `/_ping` reports. Serving max 1.51 therefore works with both, and min 1.44 is above the client floor.
  - 1.44 is also the cutoff where Compose sends every network in `EndpointsConfig` at create (`apiVersion144`). Below 1.44 it does `NetworkConnect` after create and before start.
- **What 1.51 gives up:**
  - Compose gates `HostConfig.Umask` on 1.56. At 1.51 it would be silently dropped, so treat it under AD-11.
  - `interface_name` needs 1.49 and image mounts need 1.48, both under 1.51.
- **Wrong in the decision log:**
  - The decision log says "Moby Engine API latest v1.57 (docker 29.9.3)". Engine 29.9.3 serves max **1.56** (`daemon/config/config.go`), with a default min of **1.40**.
  - `api/v1.57.0` was tagged 2026-11-13, alongside `docker-v29.10.0-rc.2`.
  - docker 29.10.0 is at rc.2 now, so the compatibility targets are about to move.
- **Evidence:**
  - https://github.com/moby/moby/blob/client/v0.6.2/client/client.go (lines 105–115, 330–360)
  - https://github.com/moby/moby/blob/docker-v29.9.3/daemon/config/config.go (lines 61–71)
  - https://github.com/docker/cli/blob/v29.9.3/vendor.mod (lines 36–37)
  - https://github.com/docker/compose/blob/v5.7.1/go.mod (lines 17, 32–33)
  - https://github.com/docker/compose/blob/v5.7.1/pkg/compose/api_versions.go
  - https://github.com/docker/compose/blob/v5.7.1/pkg/compose/create.go (lines 667–735)
- **Fix:**
  - Drop `[ASSUMPTION]` from the Engine API row and note "clients negotiate down to ≥1.40, Compose needs ≥1.44 for multi-network create".
  - List fields from 1.52–1.56 (Umask and others) that must be rejected under AD-11, not silently dropped.
  - Correct the decision log line.

### F9 — LOW — Things asserted but not checked

- **SMAppService:**
  - Agent and daemon registration from the bundle is confirmed: macOS 13+, plists in `Contents/Library/LaunchAgents` and `Contents/Library/LaunchDaemons`, `BundleProgram` relative to the bundle, user approval in Login Items.
  - Apple's docs put no sandbox or App Store requirement on it, so Developer ID is fine.
  - **Not verified:**
    - How a Sparkle in-place update behaves with a registered daemon and agent: does approval persist, and are the agent and daemon restarted against the new binary?
    - Whether a SMAppService daemon needs re-approval when the binary's signature changes.
  - Fix: add this to Deferred as a packaging spike, or test it in the first release dry-run.
  - The deployment diagram should also show the two plists.
  - Sources:
    - https://developer.apple.com/documentation/servicemanagement/smappservice
    - https://developer.apple.com/documentation/servicemanagement/updating-helper-executables-from-earlier-versions-of-macos
- **No Apple event API** (supports AD-6):
  - `XPCRoute.containerEvent` exists in 1.7.1, but no public client method uses it. Polling is the only general mechanism.
  - `ClientProcess.wait()` from `bootstrap` gives immediate exit notice for fruitlocker-started containers. The poller can use it as a fast path; AD-6 currently only mentions polling.
- **ContainerAPIClient surface:**
  - Confirmed: create, bootstrap(start), stop, kill, delete, list/get, logs (fds), createProcess (exec) with resize/kill/wait, dial, copyIn/copyOut, stats, export; `NetworkClient` create/list/get/delete; `ClientVolume` create/delete/list/inspect; `ClientImage` list/get/pull/push/tag/delete/save/load.
  - Labels exist on containers, networks (validated: lowercase DNS-style keys, ≤128-char key) and volumes. `fl.docker.id` passes that validation.
  - Keeping Docker labels in the spec (AD-3) is the right call, because many Docker label keys would fail Apple's network-label regex.
  - Sources:
    - https://github.com/apple/container/blob/1.7.1/Sources/ContainerResource/Common/ResourceLabels.swift
    - https://github.com/apple/container/tree/1.7.1/Sources/Services/ContainerAPIService/Client
- **Apple container ID format** `fl-<12 hex>`: not checked against Apple's ID rules (I couldn't find the validator). Low risk, but worth a one-line test in the first create story.

## Stack row check

| Row | Spine | Primary source (2026-11-13) | Status |
|---|---|---|---|
| Swift / Xcode | 6.2 tools, built with 6.4.2 / Xcode 27.2 | tag `swift-6.4.2-RELEASE` exists; local `swift --version` 6.4.2, `xcodebuild` 27.2 (27B52) | OK |
| macOS target | 26.0 | container README: supported on macOS 26 (its Package.swift says `.macOS("15")`, but runtime support is 26) | OK |
| apple/container | 1.7.1 exact | latest release 1.7.1 (2026-11-06); swift-tools 6.2; `ContainerAPIClient` is a library product | OK |
| Containerization | 0.54.0 | container 1.7.1 `scVersion = "0.54.0"` (exact); latest tag 0.54.0 (GitHub *releases* page is stale at 0.33.3, so tags are canonical) | OK |
| Hummingbird | 2.28.1 | latest release 2.28.1 (2026-10-31); needs swift-nio ≥2.101.0 | OK |
| SwiftNIO | 2.105.0 | latest 2.105.0 (2026-11-03); container needs ≥2.80 | OK |
| GRDB | 7.12.0 `[ASSUMPTION]` | latest v7.12.0 (2026-11-01); `swiftLanguageModes: [.v6]`; 7.0 notes say "Swift 6 ready" with Sendable work | OK, so drop `[ASSUMPTION]` on the version (keep it on the choice if wanted) |
| swift-log | 1.17.0 | latest 1.17.0 (2026-11-04) | OK |
| swift-argument-parser | 1.8.2 | highest version 1.8.2 (1.7.2 was a later backport patch) | OK |
| Sparkle | 2.10.1 `[ASSUMPTION]` | latest 2.10.1 (2026-10-25) | Version OK; behavior with SMAppService not verified (F9) |
| docker CLI / Engine | 29.9.3 | latest stable 29.9.3 (2026-11-03); 29.10.0-rc.2 out 2026-11-12 | OK, moving soon |
| Compose | v5.7.1 | latest v5.7.1 (2026-11-11) | OK |

## Fit-claim check

| Claim | Result |
|---|---|
| Hummingbird 2 listens on a Unix socket | Confirmed (F4) |
| Raw NIO channel for `Upgrade: tcp` hijack | Feasible with a custom `ServerChildChannel`; the stock NIO upgrader rejects exec's body (F4) |
| SMAppService agent + daemon, Developer ID, macOS 26 | Confirmed by docs; update and re-approval behavior not verified (F9) |
| XPC fd pass from root daemon to user agent | Confirmed (`xpc_fd_create` dup semantics; apple/container does it); peer validation missing (F6) |
| GRDB 7 under Swift 6 strict concurrency | Confirmed |
| ContainerAPIClient covers create/start/stop/logs/exec/images/networks/volumes/labels | Confirmed; image path not covered by Apple's promise (F2); no per-request registry auth (F1); no update route (F3); no event API (F9) |
| Engine API max 1.51 / min 1.44 | Works with docker 29.9.3 and Compose v5.7.1 (F8) |
| Compose v5 networks at create | All networks in `EndpointsConfig` at create when API ≥1.44; `NetworkConnect` before start below 1.44; also stop→disconnect→connect on network recreate (F3) |
