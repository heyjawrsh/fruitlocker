---
title: "Spike #11: build path through buildx and Bake"
status: done
date: 2026-11-14
issue: heyjawrsh/fruitlocker#11
evidence: spikes/11-build-path/
baseline: container 1.7.1, macOS 26.7.3, M2 Max; docker 29.9.3, buildx v0.38.1, Compose v5.7.0, BuildKit v0.35.0
---

# Spike #11: build path

## Question

Docker 29 and Compose v5 build through buildx and Bake, not legacy `/build`. Can fruitlocker make `docker build -t x .` and `docker compose build` work with no user setup, and land the image in Apple's image store (AD-5)?

## Verdict

**Go. `build` stays in the v1 gate.** The daemon serves buildx's default `docker` driver itself:

1. `/grpc` (h2c upgrade) is spliced, byte for byte, to a fruitlocker-owned BuildKit running in an Apple container.
2. `/session` (h2c upgrade) is bridged into BuildKit's `Control.Session` stream, with the `X-Docker-Expose-Session-*` headers passed as gRPC metadata.
3. The builder image carries one addition to stock BuildKit: a `moby` exporter. It runs the stock `image` exporter, writes an OCI archive of the result to a host-shared drop dir, and blocks until the daemon has loaded it with `ClientImage.load`.

With that, every client command tested worked unchanged, with no builder setup and no flags: `docker build`, `buildx build --load`, `--output type=oci`, `buildx bake`, and `compose build` with two services building in parallel. Harness: 13/13 from a clean state in 43s (`evidence/run.log`).

## Why the docker driver, and why `moby`

- **`docker build` always uses the context's own builder.** The CLI's build alias sets `BUILDX_BUILDER=<current context>` unless `--builder` or the env var is set ([docker/cli `cmd/docker/builder.go`](https://github.com/docker/cli/blob/v29.0.0/cmd/docker/builder.go), around line 140). `buildx use --default` doesn't change that. So for `docker build` to work with zero setup, the context's built-in `docker` driver has to work. A remote builder named like the context only worked when it was created before the context; buildx refuses to create it afterwards (`instance name "fl11" already exists as context builder`). Rejected as fragile.
- **The docker driver talks BuildKit over two hijacks.** buildx `driver/docker/driver.go` dials `/grpc` (h2c) for the control API and `/session` for each session ([buildx v0.38.1](https://github.com/docker/buildx/blob/v0.38.1/driver/docker/driver.go)). Feature detection is `ListWorkers`: a worker with the `org.mobyproject.buildkit.worker.snapshotter` label turns on OCI export, cache export, multi-platform and direct push. Stock BuildKit has that label.
- **The only dockerd-specific piece is the exporter.** For the docker driver, `--load` and `-t` become exporter `image`, then `moby` ([buildx `build/opt.go`](https://github.com/docker/buildx/blob/v0.38.1/build/opt.go), around lines 494–545). Stock BuildKit fails with `exporter "moby" could not be found`. Everything before export (context transfer, secrets, cache mounts, multi-stage) already worked through the splice and bridge.
- **Compose finds its builder by host, not name.** It runs Bake with `DOCKER_HOST` and `DOCKER_CONTEXT` set ([compose `pkg/compose/shellout.go`](https://github.com/docker/compose/blob/v5.7.0/pkg/compose/shellout.go)), so buildx sees the `default` context. Anything keyed on the fruitlocker context name misses there. The docker driver doesn't care, because it follows the endpoint.
- **A failed `/grpc` drifts to docker-container.** If the `/grpc` hijack fails, buildx falls back to creating a `docker-container` builder through the engine API ([buildx `builder/builder.go`](https://github.com/docker/buildx/blob/v0.38.1/builder/builder.go)). That's the `GET /containers/buildx_buildkit_fl11/json` seen in the spike.
- Non-docker drivers stream a tar to `POST /images/load?quiet=0` instead. That works too (Apple loads both docker and OCI archives), but needs builder setup and `--load`, so it's the escape hatch, not the default.

## Results

| Test | Result |
|---|---|
| Stock BuildKit in an Apple container, default caps | Fails at its first bind mount: `operation not permitted` |
| Same with `--cap-add ALL` | Works. The VM is the isolation boundary ✓ |
| buildx `remote` driver, `--output type=oci` → `container image load` → run | ✓ build args, cache mount, secret, multi-stage |
| `docker`-format tar into Apple's loader | ✓ (carries `index.json` and `oci-layout`) |
| `--load` on a remote builder | `POST /images/load?quiet=0`, docker tar, loaded ✓ |
| `docker build` with stock BuildKit behind `/grpc` + `/session` | Whole build runs; fails only at `moby` exporter |
| `docker build -t`, no flags, custom `moby` exporter | ✓ export plus hand-off 0.2–0.5s, image runs |
| `buildx build --load`, `buildx bake`, untagged build | ✓ |
| `--output type=oci,dest=` (client-side export) | ✓ stock exporter, unchanged |
| `compose build`, two services in parallel | ✓ two hand-offs in the same second, no collision |
| `--platform linux/amd64` with a `RUN` step | ✓ image is `amd64`, `RUN uname -m` gave `x86_64` |
| `buildx du`, `buildx history ls`, `builder prune` | ✓ through the plain `/grpc` splice |
| Snapshotter | Auto picks `native` when state is on the container rootfs. `overlayfs` works with `/var/lib/buildkit` on a named volume ✓ |

Engine calls around a build, besides the two hijacks: `/_ping` (HEAD), `/version`, `/info`, and from Compose after each build `GET /images/{name}/json?manifests=1`.

## Setup

- `spikes/11-build-path/flbuildkitd/`: BuildKit v0.35.0's `cmd/buildkitd` main package, vendored unchanged except one line in `main_oci_worker.go` that wraps the OCI worker. `moby.go` (about 200 lines) adds the `moby` exporter. Static `linux/arm64` build, layered on `moby/buildkit:v0.35.0`.
- `spikes/11-build-path/fakeengine.py`: stand-in daemon on a Unix socket. It logs every request; implements `_ping`, `version`, `info`, `images/load`, `images/{name}/json`; splices `/grpc`; bridges `/session` with grpcio; and watches the drop dir (load, then ack with `.done` or `.err`).
- `spikes/11-build-path/run11.sh`: harness. Builds the custom image using stock BuildKit, runs the test matrix, and removes everything it created.
- Transport in the spike is a loopback TCP port published from the builder container. See open items: production can't do that.

## Design rules for the daemon

1. **Serve the docker driver.** Answer `/_ping` with `Builder-Version: 2`. Splice `/grpc` to the builder untouched. Bridge `/session` into `Control.Session`. The daemon never parses BuildKit traffic.
2. **One builder, owned by the daemon.** A fruitlocker builder container, hidden like other internal objects (AD-4), started lazily on the first build hijack. Build state lives on a named Apple volume so the overlayfs snapshotter is used and the cache survives builder recreation. It runs with `--cap-add ALL`.
3. **The build returns only after the image is in Apple's store.** The `moby` exporter blocks on the daemon's ack. Compose creates containers right after `build`, so a load that finishes later is a bug.
4. **Image facts come from Apple after load** (AD-4, AD-5). The exporter's digest is reported to the client; `images/{name}/json` answers from Apple's store. An untagged build lands in Apple as `untagged@sha256:<digest>`; the daemon shows it as a dangling `<none>:<none>` image.
5. **Always accept the `/grpc` upgrade.** If the builder is down, start it, or fail inside the gRPC stream with a clear error. Refusing the upgrade sends buildx off to create a docker-container builder.
6. **Legacy `/build` gets a clear error.** The CLI still uses it with `DOCKER_BUILDKIT=0`, or when buildx is missing ([cli `cli/command/image/build.go`](https://github.com/docker/cli/blob/v29.9.3/cli/command/image/build.go)). Answer with a message that says to use buildx.
7. **Pin and ship the builder image.** fruitlocker publishes its builder image, pinned by digest and rebuilt for each BuildKit release it adopts. The daemon checks the builder's version at start, like the AD-12 apiserver gate.

## Open items

- **Transport (must change before v1).** The spike used a published loopback TCP port. That's reachable by any local process with no auth, against AD-17. The production path is the daemon dialing the builder over vsock (`ClientContainer.dial`). Stock buildkitd can't listen on vsock (unix, npipe, fd, tcp only). Our buildkitd can add a vsock listener, since we already own its main package. Apple's own CLI proves the dial side: it reaches its builder with `ContainerClient.dial(id: "buildkit", port: 8088)`. Not exercised here.
- **Hand-off channel.** The virtiofs drop dir was simple and fast, and `ClientImage.load` takes a file anyway. Keep it, under the store dir at 0700, or move to a vsock stream. Decide in the build epic.
- **Docker Desktop polls `/grpc`.** Its `desktop-build` agent dials `/grpc` on every context's socket in the background. Lazy builder start must not be triggered by those probes alone, or the builder VM never sleeps. Needs an idle-stop policy too.
- **Untested:** `--push` (the `moby` exporter's `push=true` path with session auth), multi-platform `--platform a,b` in one build, `--cache-to`/`--cache-from` against a registry, `compose up --build` end to end (needs real container endpoints), large builds and cache pressure.
- **amd64 emulation is Apple's.** amd64 `RUN` steps and amd64 containers ran even without `--rosetta`, and `binfmt_misc` isn't visible inside the container. BuildKit still advertises only `linux/arm64`, which may affect platform listings and multi-platform builds.
- **Maintenance cost.** fruitlocker carries a small Go component: a vendored BuildKit main package plus the exporter, rebuilt and re-published per BuildKit release. That's the price of zero setup.

## Rejected

- **Remote driver plus `default-load`.** Works for `buildx build` and Bake once configured, but `docker build` ignores it (see above), and registering it touches global buildx state. Kept as the documented escape hatch.
- **A same-named remote builder, written into buildx's store directly.** A stored instance named like the context shadows it for `docker build`, and a `defaults/<hash(host)>` file would catch Compose. That all leans on buildx internals (instance JSON, shadowing, host-hash keys). The buildx CLI already refuses that name, so this is unsupported territory.
- **Apple's builder.** `ghcr.io/apple/container-builder-shim/builder:0.13.3` (stock BuildKit v0.34.1, root, all caps) serves only Apple's own `com.apple.container.build.v1.Builder` gRPC on vsock 8088. It doesn't speak the BuildKit control API.
- **Rewriting the exporter inside `/grpc`.** It would mean terminating HTTP/2 and gRPC in the daemon and editing `SolveRequest`. And the docker driver never sets up a client-side export target, so `oci`/`docker` exporters would have nowhere to write. Brittle and incomplete.

## Spine and brief impact

- AD-5 holds: Apple's image store is the only image store.
- Proposed spine amendment (apply after PR #16 merges, via the architecture Update flow): a new AD for the build path. **Binds:** build, `/grpc`, `/session`, builder image. **Rule:** the daemon serves the docker driver by splicing `/grpc` and bridging `/session` to one daemon-owned builder; the builder's `moby` exporter hands images to the daemon, which loads them before the build returns; no client-side builder setup. AD-14's Binds add the builder image's registry pull.
- Brief addendum: `/build` with BuildKit progress becomes "build through buildx and Bake (BuildKit `/grpc` and `/session`); legacy `/build` is not served".
