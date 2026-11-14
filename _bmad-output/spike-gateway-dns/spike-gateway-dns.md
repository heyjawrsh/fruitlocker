---
title: "Spike #5: per-gateway DNS bind from a privileged helper"
status: done
date: 2026-11-13
issue: heyjawrsh/fruitlocker#5
follows: _bmad-output/spike-compose-dns/spike-compose-dns.md (#4)
evidence: spikes/5-gateway-dns/
baseline: container 1.7.1, macOS 26, Apple silicon
---

# Spike #5: per-gateway DNS bind

## Question

In #4, the resolver logic got every Docker DNS rule right. The problem was how it received packets: it took over `*:53` and fought mDNSResponder for it. Can a privileged helper instead bind only `<gateway>:53` for fruitlocker's own networks, sharing the port with mDNSResponder, so that starting or stopping fruitlocker never breaks DNS for any network?

## Verdict

**Go.** In every tested state, every network kept working DNS: helper up, helper down, 10 up/down cycles while guests ran, two gateways at once, a guest restart, and every container stopped and then restarted. Apple's `default` network stayed on mDNSResponder throughout.

There are two conditions. Both are design rules for the daemon, covered below:
1. Bind only after mDNSResponder holds `udp4 *:53`, and release before that can change.
2. Work around apple/container#2051 (two networks sharing one bridge). It's separate from DNS, but it breaks networks outright.

## Setup

- `spikes/5-gateway-dns/gwbind.py` stands in for the privileged helper. It's run once with `sudo` and driven by a control file the user owns (`up <gateway>`, empty, `exit`).
- It answers the sentinel name `fl5-probe` with `10.55.55.55`, which shows who answered. It forwards everything else using the `scutil --dns` upstreams.
- **Guard:** an address is bound only while it exists on an interface *and* mDNSResponder holds `udp4 *:53`. The helper closes it as soon as either stops being true. The guard polls once a second.
- Harness: `spikes/5-gateway-dns/run5.sh`. Containers `fl5-a1` (on `fl5_a`), `fl5-b1` (on `fl5_b`) and `fl5-d1` (on `default`).

## Results (run 2, `evidence/run2-pass.log`)

| Phase | Result |
|---|---|
| Bind `192.168.64.1:53` next to mDNSResponder | Root plus `SO_REUSEADDR` works. A plain bind gets EADDRINUSE. `netstat` shows both sockets ✓ |
| Scoping | `fl5-a1 → fl5-probe` returns 10.55.55.55. `fl5-b1` and `fl5-d1` get NXDOMAIN from mDNSResponder ✓ |
| Forwarding through the helper | `example.com` resolves ✓. One upstream timeout, and the guest's retry succeeded |
| Release while the guest runs | `fl5-a1` falls straight back to mDNSResponder with no gap ✓ |
| 10 up/down cycles | 10/10 ✓ |
| Two gateways at once | `fl5_a` and `fl5_b` both reach the helper; `default` is untouched ✓ |
| Guest restart while the helper holds the gateway | Bridge gone, helper closes. Bridge back, helper rebinds. Probe and forwarding both work ✓ |
| All containers stopped, then restarted | mDNSResponder releases and rebinds `*:53`, the helper rebinds after it, and every network resolves ✓ |
| After the helper exits | Every guest resolves through mDNSResponder ✓ |

## The #402 window

apple/container#402: if anything holds `:53` on a specific address when mDNSResponder tries to bind `*:53`, mDNSResponder's bind fails and guest DNS breaks. That's the #4 failure from the other direction.

The guard keeps the helper out of that ordering, but not perfectly. In phase 7, `netstat` caught the moment when mDNSResponder had released `*:53` while the helper still held `192.168.64.1.53`, about a second before its poll noticed. No guest started in that window, so nothing broke. If one had started, mDNSResponder would likely have failed to bind. Deliberately triggering that would risk the #4 wedge, so it wasn't tested.

**Design rule:** the daemon knows when it's about to stop a network's last container, so it releases that gateway *first* and binds again only after the first container's bridge is up and mDNSResponder holds `udp4 *:53`. That's event-driven, not polled. In the helper, interface changes come from a route socket or SCDynamicStore, not `ifconfig` polling.

## apple/container#2051: shared bridges

Run 1 (`evidence/run1-bridge-collision.log`) failed before the helper did anything, and the failure reproduced with the helper idle:

| Step | `fl5-a1` (fl5_a) | `fl5-b1` (fl5_b) | `fl5-d1` (default) | Host |
|---|---|---|---|---|
| Start a1 | ok | | | bridge100 = 64.1 |
| Start b1 | ok | ok | | +bridge101 = 65.1 |
| Start d1 | **ping and DNS fail** | ok | ok | bridge100 = **66.1** |
| Stop all; start d1, then a1 | ok | | **ping and DNS fail** | bridge100 = **64.1** |

A network keeps the bridge unit it was given the first time it started. Here, `default` had taken bridge100 during the post-reboot check, and `fl5_a` was first started while that bridge was down, so it got bridge100 too. Whichever network starts last takes the bridge, and the other one loses its gateway. Upstream it's open, and a fix has been proposed: pin each network's bridge with an anchor interface.

This matters for fruitlocker because Compose creates a network per project. It's tracked separately as a fruitlocker issue.

## Recommendation

- **Approach 1 is the Compose DNS design.** Resolver logic from #4, delivered through a privileged helper (`SMAppService` daemon, one admin prompt) that binds `<gateway>:53` for fruitlocker networks only.
- Helper rules:
  - never bind the wildcard
  - bind with `SO_REUSEADDR`, only once mDNSResponder holds `udp4 *:53`
  - release before the last container on a network stops
  - handle bridges coming and going from events
- The helper's privileged surface stays small: bind, receive and send on gateway sockets. Resolution and forwarding can stay in the unprivileged daemon, with the helper passing it packets over XPC. Whether that hop costs too much latency is still to be measured.
- Approach 2 (Apple alias DNS) is no longer needed as the fallback, but it stays the answer if a user refuses the admin prompt. In that case Compose names would be global and there'd be no multi-A.

## Open items

- Guest start inside the #402 window: avoided by design, not tested.
- TCP DNS, a forwarding cache and forward retries (run 2 saw one 2s upstream timeout) are still untested or missing.
- Helper↔daemon XPC latency is unmeasured.
- Coexistence with other vmnet users (Orchard, Lima, Internet Sharing) is still untested.
- The firewall-prompt behavior is unknown; the helper ran from a terminal.
