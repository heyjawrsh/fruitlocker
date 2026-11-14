---
type: review
lens: reconcile-technical
target: _bmad-output/architecture-fruitlocker/architecture-fruitlocker.md (commit 90cbae9)
inputs:
  - _bmad-output/research-apple-container/research-apple-container.md
  - _bmad-output/spike-compose-dns/spike-compose-dns.md (#4)
  - _bmad-output/spike-gateway-dns/spike-gateway-dns.md (#5)
  - spikes/4-compose-dns/flresolver.py
  - spikes/5-gateway-dns/gwbind.py
date: 2026-11-13
---

# Reconcile review: spine vs. research and DNS spikes

## Verdict

The big decisions landed: approach 1 delivered by a gateway-only root helper, no wildcard bind, `SO_REUSEADDR`, release before the last container stops, bridges tracked by event, #2051 owned by AD-10, no CLI scraping, the 1.x XPC version gate, controllers for restart/health/events. The gaps are in the detail the spikes paid for. The #5 guard is only partly carried, and the fd-handover choice quietly moves it from root to the daemon. The #4 resolver rules are incomplete. Most of the spikes' open items aren't mentioned anywhere. Fix before `FLDNS` or `NetworkController` stories get written; nothing here forces a restart of the spine.

## Findings

Severity: **H** breaks DNS or recreates the #4 wedge if missed. **M** wrong behavior or an undecided item someone will trip on. **L** wording or completeness.

### F1 (H): The #5 guard lost its backstop: AD-9, AD-10

#5's guard had three close conditions (gwbind.py `reconcile`): not requested, **interface gone**, **mDNSResponder released `udp4 *:53`**. It checked them continuously. AD-10 carries only the planned path: bind after bridge up and `*:53` held, release before the daemon stops the last container.

That misses every stop the daemon doesn't cause: a container crashing or OOMing, a stop through Apple's CLI, a VM dying. In those cases the bridge goes, mDNSResponder can drop `*:53`, and fruitlocker still holds `<gateway>:53`. Then the restart controller (AD-8) brings the container back, which is the exact #402 ordering #5 said to avoid. (A socket bound to an address stays bound after the address leaves the interface; that's why gwbind closed on "interface gone".)

Fix: add to AD-10 that the guard is continuous, not just ordered. On bridge-down or on losing mDNSResponder's `udp4 *:53`, release at once. Before any start on a network whose gateway is held but whose bridge is down, release first. The restart controller has to go through `NetworkController` for this.

### F2 (H): fd handover moves the guard out of root, and the spine doesn't say so: AD-9, Deferred

#5 recommended the helper keep the sockets and relay packets to the daemon over XPC. The spine instead passes the bound fd to `fruitlockerd`. That's a reasonable change: root never touches a packet, and it removes the "XPC latency per packet" open item. But it changes who can release:

- Once the daemon holds a dup of the fd, the helper closing "its copy" doesn't unbind anything. Release means the daemon closes its fd. AD-9 only describes the helper's close.
- If both keep copies, release takes two closes. That widens the #402 window instead of shrinking it.
- The helper can no longer enforce the guard after handover. The daemon has to (see F1), and the daemon is unprivileged. #5 ran its `*:53` check (`netstat -anv -p udp`) as root. Nobody has shown it works unprivileged.

Fix: in AD-9, record the deviation from #5 and why. Say the helper closes its copy immediately after a successful handover (or say why it keeps one). Say the daemon's close is the release. Name the mechanism and the process for the "mDNSResponder holds `udp4 *:53`" check. Add to the fd-handover spike in Deferred: release works with one close, the `*:53` check works unprivileged, and which binary the application firewall prompts for (see F6).

### F3 (M): The helper's input validation from #5 isn't carried: AD-9

gwbind accepted only IPv4 `192.168.0.0/16` addresses ending `.1`, from a control file owned by the invoking user that nobody else can write. It bound only while the address was on an interface. AD-9 says "gateways the daemon names", with no limits. A root process that binds `:53` on any address it's told is a DNS-hijack primitive for the LAN or for another tool's vmnet network.

Fix: in AD-9, have the helper (a) verify the XPC peer's code signature (same team ID, the daemon's identifier), (b) bind only an address currently on a `bridge*` interface that the daemon says belongs to a fruitlocker-owned network, never loopback, never a non-bridge interface, (c) refuse the wildcard (already there).

### F4 (M): The #4 resolver rules in AD-9 are incomplete and one is ambiguous: AD-9

AD-9 lists source-IP keying, per-network scope, multi-A, AAAA NODATA and `scutil` forwarding. Missing from flresolver.py:

| Rule | Prototype | Spine |
|---|---|---|
| Unknown single-label name → NXDOMAIN, never forwarded | yes | **missing** |
| Drop sources outside fruitlocker vmnet subnets | yes | **missing** (fd sockets make this less likely, not impossible) |
| TTL | 5s (matches Apple's alias DNS) | **missing**. Matters because IPs change on stop/start |
| Forward order: most specific `scutil` domain first, skip `local`, refresh on change | sorted, 30s refresh | "through `scutil --dns`" only |
| Round-robin (shuffle per answer) | yes | missing |
| AAAA for an unknown name → NXDOMAIN, not NODATA | yes | not said |
| Name set: container ID, service name, aliases | yes | not said. Docker also resolves container name and short ID |
| Forward failure → SERVFAIL (flresolver) vs. silent drop (gwbind) | differs | not decided |

Scope ambiguity: "keyed by source IP, scoped per network" could be read as scoped to the network of the socket that received the query. That's wrong for multi-network containers. A container on `pa_default` and `pa_back` sends every query to one gateway (its first network's), and #4 passed because flresolver answered from the **union** of the querier's networks, returning the IP on the shared network. Fix: in AD-9, write "identify the querier by source IP, answer from every network it's attached to, with each IP taken from the shared network", and add the rows above as a rule list or a pointer to a resolver test table.

### F5 (M): Spike open items with no decision, deferral or flag: Deferred

None of these appear in the spine:

- **TCP DNS / truncation.** The helper binds UDP only. A scaled service with many replicas or a big forwarded answer goes over 512 bytes, the guest retries over TCP to `<gateway>:53`, and mDNSResponder answers that without Compose names. Decide: UDP-only with EDNS0 and a capped answer count, or also bind TCP.
- **Forward cache and retries.** #5 saw a 2s upstream timeout. The prototypes only use `nameserver[0]` per resolver. Decide on retrying across nameservers; defer the cache explicitly.
- **Split-DNS forwarding never exercised by a query** (#4). Add it to the compat matrix.
- **Coexistence with other vmnet users** (Orchard, Lima, Internet Sharing). Untested in both spikes, and it interacts with #2051 bridge stealing. Flag it as a v1 risk owned by AD-10/#8.
- **Firewall prompt.** Unknown in both spikes. See F6.
- **Guest start inside the #402 window.** "Avoided by design, not tested". With F1 fixed, record it as accepted residual risk.
- **Cold start (inferred, not tested).** #4 says mDNSResponder binds `*:53` on demand once guests do DNS. The guard won't bind until it does. So when a fruitlocker network is the only vmnet user on the Mac, the first container's first queries probably reach mDNSResponder and get NXDOMAIN for service names. Apps that resolve `db` once at boot will fail. Measure it in the fd-handover spike. AD-10 already "orders first starts", so it's a natural place for a mitigation.

Fix: add a "DNS open items" block to Deferred that decides or defers each one, with an owner (fd-handover spike, #8, or the compat matrix).

### F6 (M): Helper refusal and the firewall aren't covered: AD-1, AD-9, Deployment

#5: approach 2 (Apple alias DNS) "stays the answer if a user refuses the admin prompt". The spine has no path for an unapproved or disabled helper. Decide: degraded mode (approach 2: global names, no multi-A, FQDN aliases of two or more labels that are unique across networks and fixed at create), or refuse Compose networking with an AD-11-style error. Either way, surface helper state through `/fruitlocker/v1` (AD-13 already lists "helper state"). The firewall prompt is still unknown. With fd handover, the prompt (if any) may land on `fruitlockerd`, not the helper. Check it with the signed, notarized build, not a terminal.

### F7 (M): Multi-network order, published ports, IP changes: AD-3, AD-9

From #4's "other facts": a container's IP changes on stop/start; a container on two networks gets `eth0`/`eth1`; published ports land on the first network.

- **IP change.** AD-3 reads runtime state live, so it's covered in spirit. But DNS staleness after an external exit is bounded by the poll interval (Deferred) plus TTL (F4). State the bound.
- **Attachment order.** AD-3 stores attachments but doesn't say order is kept and maps to `eth0`, `eth1`, ... Compose's `priority` and the default network have to drive that order.
- **Published ports.** No mention. Say ports publish on the first attachment, and that this follows from the order above.

Fix: one bullet each in AD-3 (ordered attachments, first = `eth0` = published ports) and AD-9 (freshness bound).

### F8 (M): Starting Apple's services contradicts AD-2: AD-2, Deployment

The research proof started services with `container system start --enable-kernel-install`. AD-2 says nothing shells out to the `container` CLI. The apiserver isn't reachable over XPC until it's started, so `ContainerAPIClient` can't do the first start. The spine has no bootstrap path. Fix: either carve out a narrow, documented CLI exception (`system start` / `system status`, exit code only, no output parsing, consistent with "CLI JSON broke at 1.0" and "CLI is only generally compatible"), or make it a guided user step in the app's first run. Don't copy Apple's launchd registration; that touches private install layout with no compatibility promise.

### F9 (L): Undocumented host behavior isn't version-gated: AD-12, Deployment CI

The research says private helpers carry no promise. The DNS design rests on undocumented mDNSResponder and InternetSharing behavior (`*:53` on demand, #402 ordering, `SO_REUSEADDR` coexistence) and on vmnet bridge naming. AD-12 gates only the apiserver XPC version. Fix: add the #5 phase table (bind beside mDNSResponder, 10 up/down cycles, guest restart, all-stop/restart, helper exit) to the compat matrix and run it per macOS point release and Apple container release. Have the app detect the wedge state (vmnet helpers hang) and say "reboot to recover" instead of retrying.

### F10 (L): Research items not placed: AD-11, Deferred

- Concurrent read-only named volumes (apple/container#889): common in Compose, not mentioned. Fail loudly per AD-11 or defer with a note.
- `--privileged` / `cap_add`: the research says these "only affect the guest VM". AD-11 fails "host-level privileged mode", which isn't a Docker option. Say whether `privileged: true` and `cap_add` map to the guest or fail.
- Sandbox: `ContainerAPIClient` works only unsandboxed. Say `fruitlockerd` is unsandboxed and Developer ID only (no App Store). If the app is sandboxed, it can't reach `~/.fruitlocker/run/docker.sock` without an entitlement or a group container.
- `scutil --dns`: AD-9 implies shelling out. Prefer `dns_configuration_copy` / SCDynamicStore change notifications so VPN changes get picked up without polling.

## What landed (no action)

| Input | Where in spine |
|---|---|
| Never bind the wildcard; `SO_REUSEADDR`; root only for bind | AD-9 |
| Bind only after bridge up and mDNSResponder holds `udp4 *:53` | AD-10 |
| Release before the last container stops | AD-10 |
| Bridges by event, not polling | AD-10 |
| fruitlocker networks only; Apple `default` untouched | AD-10 (`bridge` → fruitlocker-owned network), Conventions (Apple-native containers get no DNS) |
| #2051 shared bridges as a separate issue | AD-10 + Deferred (#8) |
| Resolver in the unprivileged daemon | AD-9 |
| No `network connect`/`disconnect` on running containers | AD-11 (fail), AD-3 (spec-only before start) |
| No CLI JSON scraping | AD-2 |
| XPC compat within a major only | AD-12 |
| No events (#484), restart (#2142), health (#1918) | AD-6 poller, AD-8 controllers |
| host net, `container:` mode, shared PID/IPC, DinD unsupported; DooD later | AD-11, Deferred |
| Event-driven DNS instead of 1s polling | AD-6 + AD-9 |
