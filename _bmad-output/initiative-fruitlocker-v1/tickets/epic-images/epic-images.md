---
id: 2
type: epic
title: "Images move through Apple's store"
parent: initiative-fruitlocker-v1
covers: ["R2", "R7", "R10"]
sources: []
companions: []
after: []
refined: false
risk: medium
---

# Images move through Apple's store

## Description

Gives fruitlocker its first Docker objects. `ImageService` and `FLRegistry` pull and push with each request's `X-Registry-Auth`, landing images in Apple's store via `ClientImage.load` and reading them via `ClientImage.save`. `docker images`, `tag`, `rmi`, `load`, `save` and `login` (`/auth` validates only) work; image IDs are Apple's `descriptor.digest`. The `Resolver` and per-object locks first land here. Image-helper calls run only on allow-listed Apple versions; otherwise endpoints serve with a warning.

## Outcome

A developer runs `docker pull` and `docker push` against their usual registries with their usual `docker login`, and sees the result in `docker images` (parent R7; R2 pull, push, images part).

## Done when

- `docker pull alpine`, `docker images`, `docker tag`, `docker rmi` work against Apple's store on 1.7.1 (R2, R7).
- `docker login` to a private registry, then `docker push` of a tagged image succeeds; no credential appears in the store, keychain or logs (AD-14).
- `docker save` then `docker load` round-trips an image (R7).
- `/events` shows image `pull`, `push`, `tag`, `untag`, `delete`, `load`, `save` from `ImageService` only (R10, image part).
- Compatibility tests for pull, push and images pass on the local runner.
- Delivered: the change is in a signed build Josh runs on his Mac against Apple `container` 1.7.1, with core tests green in CI.

## Boundaries

- Owns: `ImageService`, `FLRegistry`, image endpoints, `/auth`, the `Resolver`, the per-object lock primitive.
- Not here: the container to image reference rule that blocks deletion (epic-containers owns the reference row; this epic honors it once it exists), `/build` (epic-build).
- Touch point: container registries over HTTPS; owner: this epic.

## References

- parent: _bmad-output/initiative-fruitlocker-v1/initiative-fruitlocker-v1.md, section Requirements (R2, R7, R10)
- architecture: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md, AD-4 (image IDs, Resolver), AD-5, AD-6 (image emitters), AD-7, AD-11, AD-12 (image-helper allow-list), AD-14

## Notes

- Assumption: [CONFIRMED by Josh 2026-11-14] The `Resolver` and per-object FIFO lock land in this epic because it is the first with Docker objects; later epics reuse them.
