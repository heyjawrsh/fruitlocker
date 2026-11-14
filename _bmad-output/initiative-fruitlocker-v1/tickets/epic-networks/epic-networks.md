---
id: 4
type: epic
title: "User networks for Compose"
parent: initiative-fruitlocker-v1
covers: ["R2", "R9", "R10"]
sources: []
companions: []
after: []
refined: false
risk: medium
---

# User networks for Compose

## Description

`NetworkService` creates, lists, inspects, removes and prunes user-defined networks with labels and filters. `ContainerService` owns container to network rows; connect and disconnect on a stopped container edit the spec and set `needsRecreate`, and on a running one are rejected. `network rm` dematerializes stopped containers held only by a stale attachment, so Compose's stop, disconnect, rm, create, connect, start sequence works. Boot ensures the `bridge` network exists. Name resolution is not in this epic.

## Outcome

`docker compose up` creates its project network and attaches every service to it, and `docker compose down` removes it cleanly (parent R9, network part; R2 network part).

## Done when

- `docker network create`, `ls` with label filters, `inspect`, `rm`, `prune` work on 1.7.1 (R2, R9).
- A Compose project with two services comes up on its own network and `down` removes the network with no leftover Apple objects.
- `network connect` on a running container returns 400 naming the option; on a stopped one the next start recreates and returns a `Warnings` entry (AD-3, AD-11).
- `/events` shows network `create`, `destroy`, `prune` from `NetworkService` and `connect`/`disconnect` from `ContainerService` (R10, network part).
- Compatibility tests for network pass on the local runner.
- Delivered: the change is in a signed build Josh runs on his Mac against Apple `container` 1.7.1, with core tests green in CI.

## Boundaries

- Owns: `NetworkService`, network endpoints, boot step 7.
- Not here: `NetworkController`, the lifecycle hooks, the `:53` guard and DNS (epic-compose-dns).
- Handoff: epic-compose-dns, epic-volumes, epic-logs-exec, epic-restart-health and epic-app rely on the network endpoints and the project network.

## References

- parent: _bmad-output/initiative-fruitlocker-v1/initiative-fruitlocker-v1.md, section Requirements (R2, R9, R10)
- architecture: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md, AD-3 (network attachments, needsRecreate), AD-4 (network IDs), AD-6 (network emitters), AD-7 (attachment ownership, in-use, lock order), AD-11 (no connect on running), AD-16 (step 7), AD-19 (ports on first network)

## Notes

- Waits on epic-containers because: it needs `ContainerService`, materialization and the attachment extension point; this epic adds the container to network rows there.
- Bug #8 (bridge collision) may show up first here; detection and mitigation belong to `NetworkController` in epic-compose-dns (AD-10).
