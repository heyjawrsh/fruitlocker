---
id: 5
type: epic
title: "Compose services resolve each other by name"
parent: initiative-fruitlocker-v1
covers: ["R12"]
sources: []
companions: []
after: []
refined: false
risk: high
---

# Compose services resolve each other by name

## Description

The biggest technical unknown in the brief, already shaped by #4 and #5. `fruitlocker-helper`, a root LaunchDaemon registered from the same bundle, binds only `<gateway>:53` UDP with `SO_REUSEADDR` and hands the fd to the daemon over `FLHelperProtocol` after mutual code-signing checks. `NetworkController` implements the `NetworkLifecycle` hooks every start and stop path awaits, and binds or releases under the AD-10 guard and backstop. `DNSViewController` projects one immutable `DNSView` per user network, which `FLDNS` answers from and which also fills `DNSNames` in `inspect`. Refusing the helper degrades loudly.

## Outcome

In a Compose project, `web` reaches `db` by service name and alias, and `:53` is never left bound after the last container stops (parent R12).

## Done when

- Two Compose services on one network resolve each other by service name and alias; a service on two networks sees the union (R12, AD-21).
- Stopping the last container on a network releases its `:53` before `willStop` returns; a bridge-down or mDNSResponder losing `udp4 *:53` releases at once (AD-10).
- Containers on `bridge` are not served and resolve through mDNSResponder (AD-10).
- With the helper refused, a `/fruitlocker/v1` warning and a `Type=daemon` `fl.dns.unavailable` event say Compose names are off (AD-9).
- A helper with a mismatched protocol version is refused and re-registered (AD-1).
- Compatibility test: a pinned two-service Compose sample resolves by name on the local runner.
- Delivered: the change is in a signed build Josh runs on his Mac against Apple `container` 1.7.1, with core tests green in CI.

## Boundaries

- Owns: `fruitlocker-helper`, `FLHelperProtocol`, `FLDNS`, `HostNetObserver`, `NetworkController`, `DNSViewController`, boot step 8, #8 detection and mitigation.
- Owns the DNS items deferred from #4 and #5: TCP DNS, forwarding cache and retries, the firewall prompt, coexistence with other vmnet users, the first start of a network.
- Not here: Apple alias DNS (out of v1, AD-9).
- Touch point: mDNSResponder `udp4 *:53` and vmnet bridges, observed only; owner: this epic.

## References

- parent: _bmad-output/initiative-fruitlocker-v1/initiative-fruitlocker-v1.md, section Requirements (R12)
- architecture: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md, AD-1 (helper LaunchDaemon, versioned handshake), AD-6 (HostNetObserver), AD-8 (NetworkLifecycle hook, withdraw call), AD-9, AD-10, AD-17 (helper peer checks), AD-21

## Notes

- Waits on #14 (fd handover spike) because: it proves the `SO_REUSEADDR` handover and unprivileged `udp4 *:53` visibility `FLDNS` is built on; if it fails, the helper gets one read-only query (spine Deferred).
- Waits on #8 (bridge collision bug) because: AD-10 makes `NetworkController` own its detection and mitigation; any Apple network-helper restart needs its own AD-2 exception decided in #8.
- Waits on epic-networks because: it needs user-defined networks and attachments to project names over.
- Waits on epic-engine-foundation because: the helper LaunchDaemon is registered from the signed bundle.
- Known hazard: taking over guest DNS on `:53` can wedge vmnet until reboot; stories that touch the guard test on a machine Josh can reboot.
