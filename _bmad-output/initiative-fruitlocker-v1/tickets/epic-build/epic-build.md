---
id: 9
type: epic
title: "docker build and Compose build"
parent: initiative-fruitlocker-v1
covers: ["R2", "R8"]
sources: []
companions: []
after: []
refined: false
risk: high
---

# docker build and Compose build

## Description

Kept thin on purpose. Docker 29 and Compose v5 build through buildx and Bake (BuildKit `/session` and `/grpc`), and mapping that onto Apple's builder VM is unproven. #11 decides the path; this epic is written out only after it reports. Whatever path it proves, built images land in Apple's store and registry credentials follow AD-14.

## Outcome

A developer runs `docker build -t app .` and `docker compose build` on an existing project and gets an image in `docker images` (parent R8; R2 build part).

## Done when

- `docker build` and `docker compose build` produce a runnable image with BuildKit progress, on the path #11 proves (R8).
- Compatibility test for build passes on the local runner.
- Or: #11 fails, Josh amends the v1 gate, and this epic is dropped or rescoped with a `Dropped:` or `Decision:` line.
- Delivered: the change is in a signed build Josh runs on his Mac against Apple `container` 1.7.1, with core tests green in CI.

## Boundaries

- Owns: `/build` and whatever endpoints #11 names (`/session`, `/grpc`).
- Not here: image transfer and auth (epic-images); a second image store (forbidden by AD-5).

## References

- parent: _bmad-output/initiative-fruitlocker-v1/initiative-fruitlocker-v1.md, section Requirements (R2, R8)
- architecture: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md, AD-5 (one image store), AD-11, AD-14 (build credentials)

## Notes

- Waits on #11 (build via buildx and Bake spike) because: it decides whether and how v1 builds; its outcome may reshape or drop this epic and corrects the addendum's `/build` line.
- Waits on epic-images because: it needs the Apple image store adapter and registry auth.
- Waits on epic-containers because: Done when needs `docker run` to prove the built image runs.
- Assumption: [ASSUMPTION] No Requirements or story plan until #11 reports; refining this epic before then would re-decide what the spike settles.
