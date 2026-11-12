---
title: "Spike #4: Compose service discovery on Apple container"
status: done (recovery check pending reboot)
date: 2026-11-12
issue: heyjawrsh/fruitlocker#4
evidence: spikes/4-compose-dns/ (commit dab8b2a)
baseline: container 1.7.1, macOS 26, Apple silicon
---

# Spike #4: Compose service discovery

## Question

Can fruitlocker give Compose containers Docker's DNS behavior on top of Apple `container` 1.7.1? That means bare service names (`db`), names scoped to the networks a container is on, several A records for a scaled service, and names that follow a restart.

## Verdict

- **The DNS logic works.** A host-side resolver keyed on the guest's source IP got every Docker rule right.
- **The way the prototype got packets doesn't ship.** It only works by binding `*:53` before mDNSResponder does. Stopping it while guests were running broke container networking for the whole Mac. That's a no-go.
- **Next:** spike a privileged helper that binds `:53` on each vmnet gateway address only, rather than the wildcard. If that fails, fall back to Apple's alias DNS (approach 2) and accept the gaps.

## What Apple gives us

From the 1.7.1 source and docs (`docs/architecture/dns.md`, `Sources/DNSServer/AliasPolicy.swift`), plus rounds 1 and 3:

- Each network is a vmnet NAT with its gateway at `.1`. The guest's `resolv.conf` points at the gateway, and on the host mDNSResponder answers there as the Internet Sharing DNS proxy.
- `container-apiserver` serves container names on `127.0.0.1:2053`. To reach it, `container system dns create <domain>` (needs sudo) writes `/etc/resolver/containerization.<domain>`.
- Aliases must have at least 2 labels (`db` is rejected; `db.pa.fruitlocker.internal` works). They're fixed at create time and must be unique across **all** networks. Lookups go to every network, so names aren't scoped per network. TTL is 5s.
- Guests couldn't resolve FQDN aliases until the resolver file existed.
- Bare-name discovery isn't implemented yet (apple/container#1809, #856). There's no `network connect`/`disconnect`.
- Other facts we'll need: a container's IP changes on stop/start; a container on two networks gets `eth0`/`eth1`; published ports land on the first network.

## Approaches

| | Approach | Bare names | Per-network scope | Multi-A | Privilege | Verdict |
|---|---|---|---|---|---|---|
| A | Apple aliases + `/etc/resolver` file | No (FQDN only) | No | No (unique names) | sudo once | Supported, not faithful |
| B | DNS sidecar container per network | Yes | Yes | Yes | None | Costs a VM per network. Rejected |
| C | Write `/etc/hosts` into guests | Yes | Yes | No | None | Has to be rewritten in every guest whenever an IP changes. Rejected |
| 1 | Host resolver keyed by guest src/dst IP | Yes | Yes | Yes | See below | Logic proven; packet delivery blocked |
| 2 | Per-network search domain on Apple's DNS | Via search suffix | Partial (names stay global) | No | sudo once | Fallback |

## Prototype (approach 1)

`spikes/4-compose-dns/flresolver.py`, Python standard library only, run unprivileged.

- Binds `0.0.0.0:53/udp` with `IP_RECVDSTADDR`, so each query arrives with the guest IP as `src` and the gateway as `dst`.
- Polls `container ls --format json` every second. A container's names are its ID, its `com.docker.compose.service` label and its `fl.aliases` label. Its networks map each network to its IPv4 address.
- Answers with the matching containers on any network the querying container shares. Shuffles the list for round-robin.
- An unknown single-label name gets NXDOMAIN. Anything else is forwarded to the upstream from `scutil --dns`, matching the most specific domain first.
- AAAA for a known name returns NODATA. musl needs that.
- Drops queries from outside vmnet subnets.

Harness `spikes/4-compose-dns/run.sh`. Project `pa` has `pa_default` and `pa_back`; project `pb` has `pb_default`.

### Results (run 2, `evidence/prototype-run2.log`)

| Check | Result |
|---|---|
| `pa-web-1 → db`, `postgres` | 192.168.65.2 (pa's db) ✓ |
| `pb-tools-1 → db` | 192.168.67.2 (pb's db, not pa's) ✓ |
| `pa-web-1 → tools`, `pb-db-1` | NXDOMAIN (other network / other project) ✓ |
| `pa-tools-1` (`pa_back` only) `→ db` | NXDOMAIN ✓ |
| `pa-multi-1` (both nets) | Sees `db`, `tools` and `web`; each answer is the IP on the querier's network ✓ |
| `ping db` from both projects | Reaches the right container ✓ |
| Scaled `web` ×10 lookups | 6 × .3, 4 × .4 ✓ |
| Stop/start `pa-db-1` | NXDOMAIN while stopped, then the new IP (.2 → .6) within the 1s poll ✓ |
| Forwarding | `apk add` ok; MX and TXT ok ✓ |
| Split DNS upstreams | Parsed from `scutil --dns` (two domains → 10.8.2.1). **Not exercised by a query** |
| Query from LAN IP | Dropped (timeout) ✓ |
| Latency | Local 0.1–0.9 ms in the resolver, 4 ms round trip from the guest. Forwarded 9–20 ms (no cache) |

### The failure

1. **Run 1.** The resolver couldn't start (`Errno 48 Address already in use`). mDNSResponder binds `*:53` on demand once guests are doing DNS, and whoever binds first gets the port.
2. **Run 2.** The resolver went first and won. At step 12 it stopped while guests were up. mDNSResponder only got `udp6 *.53` back, so guests got `connection refused`.
3. **Recovery didn't work.** After that, every `container-network-vmnet` helper hung on start, and so did `container system stop` and `container system start`. `killall -HUP mDNSResponder` did nothing. `killall mDNSResponder` brought back its sockets but not vmnet. InternetSharing ignored SIGTERM. Only a reboot fixes it.

The trick depends on undocumented mDNSResponder and InternetSharing behavior, and when it fails it takes the whole machine's container networking with it. A user quitting fruitlocker at the wrong moment would hit exactly that.

## Port 53 facts (`evidence/probe-*.log`)

- Unprivileged: binding `0.0.0.0:53` works. Binding `127.0.0.1:53` or a gateway address (`192.168.64.1:53`) fails with EACCES.
- `bridge100+` only exists while a VM is running, so gateway addresses come and go.
- Whether the macOS application firewall showed a prompt is unknown. It's on, and nobody was watching the screen.

## Recommendation

1. **Keep approach 1's resolver logic.** It becomes a component of the daemon: keyed by source IP, scoped per network, multi-A, NODATA for AAAA, forwarding via `scutil`. In Swift it can subscribe to apiserver events instead of polling.
2. **Spike a gateway-specific bind from a privileged helper** (an `SMAppService` daemon, one admin prompt, the same cost as approach A's resolver file):
   - Bind `<gateway>:53` for each fruitlocker network as soon as its bridge appears. BSD delivers to the most specific address, so this may coexist with mDNSResponder's `*:53` with no race at all.
   - Test: bind while mDNSResponder already holds `*:53`; stop and start the helper while guests run; make sure non-fruitlocker networks (Apple's `default`, other tools) still get mDNSResponder.
   - Pass condition: no state where stopping fruitlocker breaks DNS for any network.
3. **If that fails, fall back to approach 2.** Use Apple's alias DNS with a per-project search domain. Document the gaps: names are global, there's no multi-A, and aliases are fixed at create time.

## Open items

- TCP DNS (answers over 512 bytes, truncation) is untested.
- There's no cache for forwarded queries.
- Split-DNS forwarding was parsed but no query exercised it.
- Coexistence with other vmnet users (Orchard, Lima, Internet Sharing) is untested.
- The firewall-prompt behavior is unknown.
- After the reboot: confirm `container system start` works and a fresh container resolves `example.com`, then remove the spike containers and networks.
