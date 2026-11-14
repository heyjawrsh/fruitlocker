---
id: 6
type: epic
title: "Named volumes persist across containers"
parent: initiative-fruitlocker-v1
covers: ["R2", "R9", "R10"]
sources: []
companions: []
after: []
refined: false
risk: medium
---

# Named volumes persist across containers

## Description

`VolumeService` creates, lists, inspects, removes and prunes named and anonymous volumes on Apple's volume store, keeping only spec metadata. Mounts are container to volume reference rows checked in one transaction with the referencing write. Whether two running VMs can mount one volume is decided by #13; if not, the second mount fails loudly under AD-11.

## Outcome

A Compose project's Postgres keeps its data across `down` and `up`, and `docker volume rm` refuses a volume still in use (parent R9, volume part; R2 volume part).

## Done when

- `docker volume create`, `ls` with label filters, `inspect`, `rm`, `prune` work on 1.7.1 (R2, R9).
- `docker run -v name:/data` persists data across container removal; anonymous volumes get 64-hex names (AD-4).
- `volume rm` on an in-use volume returns Docker's error (AD-7).
- A second concurrent mount of one volume either works or returns 400 naming the limit, per #13 (AD-11).
- `/events` shows volume `create`, `destroy`, `prune` from `VolumeService` and `mount`/`unmount` from `ContainerService` (R10, volume part).
- Compatibility tests for volume pass on the local runner.
- Delivered: the change is in a signed build Josh runs on his Mac against Apple `container` 1.7.1, with core tests green in CI.

## Boundaries

- Owns: `VolumeService`, volume endpoints, container to volume reference rows in `ContainerService` (plugged into epic-containers' extension points).
- Handoff: epic-app relies on the volume endpoints for its views.
- Not here: bind mounts of host paths beyond what container create already supports (epic-containers).

## References

- parent: _bmad-output/initiative-fruitlocker-v1/initiative-fruitlocker-v1.md, section Requirements (R2, R9, R10)
- architecture: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md, AD-3 (mounts set needsRecreate and feed specHash), AD-4 (volume names and Apple IDs), AD-5, AD-6 (volume emitters), AD-7 (volume references, in-use, lock order), AD-11

## Notes

- Waits on #13 (shared named volumes spike) because: it decides whether shared mounts are supported or rejected (apple/container#889).
- Waits on epic-containers because: mounts are part of container create and materialization.
- Waits on epic-networks because: both change the canonical `ContainerConfiguration` and `specHash`, and AD-7 locks networks before volumes; building them in parallel would collide in that code.
