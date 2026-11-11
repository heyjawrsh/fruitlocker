"""fruitlocker spike #4: host-side embedded DNS for Apple container guests.

Throwaway prototype. Standard library only. Run unprivileged:

    python3 -I flresolver.py

Binds 0.0.0.0:53/udp. vmnet hands guest queries addressed to each network's
gateway to this socket, with the guest's source IP intact. From (src, dst) we
know which container is asking and on which network, so we can answer with
Docker's rules: names scoped to the querier's networks, every replica's IP for
a scaled service, NXDOMAIN for unknown single-label names, and everything else
forwarded upstream using macOS's own resolver config (scutil --dns), so split
DNS from /etc/resolver keeps working.

State comes from polling `container ls --format json` once a second.
Compose identity comes from labels:
  com.docker.compose.service   service name (resolvable on every attached network)
  fl.aliases                   extra names, comma separated (stand-in for
                               per-network Compose aliases)
"""

import ipaddress
import json
import random
import socket
import struct
import subprocess
import sys
import threading
import time

IP_RECVDSTADDR = 7  # macOS
TTL = 5
POLL_SECONDS = 1.0

state_lock = threading.Lock()
state = {"containers": [], "gateways": {}, "subnets": [], "upstreams": []}


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


# ---------- state ----------

def poll_containers():
    out = subprocess.run(["container", "ls", "--format", "json"], capture_output=True, text=True, timeout=10)
    if out.returncode != 0:
        return None
    containers, gateways, subnets = [], {}, set()
    for c in json.loads(out.stdout or "[]"):
        if c.get("status", {}).get("state") != "running":
            continue
        labels = c.get("configuration", {}).get("labels", {}) or {}
        names = {c["id"].lower()}
        if svc := labels.get("com.docker.compose.service"):
            names.add(svc.lower())
        for a in filter(None, (labels.get("fl.aliases") or "").split(",")):
            names.add(a.strip().lower())
        nets = {}
        for n in c.get("status", {}).get("networks", []):
            ip = n.get("ipv4Address", "").split("/")[0]
            if not ip:
                continue
            nets[n["network"]] = ip
            gateways[n["ipv4Gateway"]] = n["network"]
            subnets.add(str(ipaddress.ip_interface(n["ipv4Address"]).network))
        containers.append({"id": c["id"], "names": names, "nets": nets})
    return containers, gateways, [ipaddress.ip_network(s) for s in subnets]


def poll_upstreams():
    """Parse `scutil --dns` into [(domain or None, nameserver, port)], most specific first."""
    out = subprocess.run(["scutil", "--dns"], capture_output=True, text=True, timeout=10).stdout
    ups, cur = [], None
    section = out.split("DNS configuration (for scoped queries)")[0]
    for line in section.splitlines():
        line = line.strip()
        if line.startswith("resolver #"):
            if cur and cur.get("ns"):
                ups.append(cur)
            cur = {"domain": None, "ns": None, "port": 53}
        elif cur is not None and ":" in line:
            k, v = [x.strip() for x in line.split(":", 1)]
            if k == "domain":
                cur["domain"] = v.lower().rstrip(".")
            elif k.startswith("nameserver[0]"):
                cur["ns"] = v
            elif k == "port":
                cur["port"] = int(v)
    if cur and cur.get("ns"):
        ups.append(cur)
    ups = [u for u in ups if u["domain"] != "local"]  # mDNS, not unicast
    ups.sort(key=lambda u: -(len(u["domain"].split(".")) if u["domain"] else 0))
    return ups


def poller():
    last_up = 0
    while True:
        try:
            snap = poll_containers()
            with state_lock:
                if snap:
                    state["containers"], state["gateways"], state["subnets"] = snap
                if time.time() - last_up > 30:
                    state["upstreams"] = poll_upstreams()
                    last_up = time.time()
        except Exception as e:  # keep serving on poll errors
            log(f"poll error: {e}")
        time.sleep(POLL_SECONDS)


# ---------- DNS wire ----------

def parse_question(data):
    tid, flags, qd = struct.unpack(">HHH", data[:6])
    i, labels = 12, []
    while data[i]:
        n = data[i]
        labels.append(data[i + 1:i + 1 + n].decode("ascii", "replace"))
        i += n + 1
    qtype, qclass = struct.unpack(">HH", data[i + 1:i + 5])
    return tid, flags, ".".join(labels).lower(), qtype, data[12:i + 5]


def reply(tid, qflags, question, rcode=0, ips=()):
    flags = 0x8000 | (qflags & 0x0100) | 0x0400 | 0x0080 | rcode  # QR, RD copy, AA, RA
    hdr = struct.pack(">HHHHHH", tid, flags, 1, len(ips), 0, 0)
    ans = b"".join(b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, TTL, 4) + socket.inet_aton(ip) for ip in ips)
    return hdr + question + ans


def forward(data, qname, upstreams):
    for u in upstreams:
        d = u["domain"]
        if d is None or qname == d or qname.endswith("." + d):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as f:
                    f.settimeout(2.0)
                    f.sendto(data, (u["ns"], u["port"]))
                    resp, _ = f.recvfrom(4096)
                    return resp, u
            except OSError:
                continue
    return None, None


# ---------- resolution ----------

def resolve(src, dst, qname):
    """Return (handled, ips). handled=False means forward upstream."""
    with state_lock:
        containers, gateways = state["containers"], state["gateways"]
    querier = next((c for c in containers if src in c["nets"].values()), None)
    if querier is None:
        return False, []
    ips = []
    for net in querier["nets"]:
        for c in containers:
            if net in c["nets"] and qname in c["names"]:
                ips.append(c["nets"][net])
    ips = sorted(set(ips))
    random.shuffle(ips)  # round-robin-ish, like Docker
    if ips:
        return True, ips
    if "." not in qname:
        return True, []  # unknown single-label: NXDOMAIN, never leak upstream
    return False, []


def main():
    threading.Thread(target=poller, daemon=True).start()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.IPPROTO_IP, IP_RECVDSTADDR, 1)
    s.bind(("0.0.0.0", 53))
    log("listening on 0.0.0.0:53/udp")
    time.sleep(1.5)
    with state_lock:
        log(f"upstreams: {[(u['domain'], u['ns'], u['port']) for u in state['upstreams']]}")
    while True:
        data, anc, _, (src, sport) = s.recvmsg(4096, 256)
        dst = next((socket.inet_ntoa(d[:4]) for _, t, d in anc if t == IP_RECVDSTADDR), "?")
        with state_lock:
            subnets, upstreams = state["subnets"], state["upstreams"]
        if not any(ipaddress.ip_address(src) in n for n in subnets):
            log(f"DROP non-vmnet src={src} dst={dst}")
            continue
        try:
            tid, qflags, qname, qtype, question = parse_question(data)
        except Exception:
            continue
        t0 = time.perf_counter()
        handled, ips = resolve(src, dst, qname)
        if handled:
            exists = bool(ips)
            if qtype == 1:
                resp = reply(tid, qflags, question, 0 if exists else 3, ips)
            else:  # AAAA etc: NODATA if the name exists (musl needs this), else NXDOMAIN
                resp = reply(tid, qflags, question, 0 if exists else 3)
            how = f"local {ips or 'NXDOMAIN'}"
        else:
            resp, u = forward(data, qname, upstreams)
            if resp is None:
                resp = reply(tid, qflags, question, 2)  # SERVFAIL
                how = "forward FAILED"
            else:
                how = f"forward -> {u['domain'] or 'default'} {u['ns']}:{u['port']}"
        s.sendto(resp, (src, sport))
        ms = (time.perf_counter() - t0) * 1000
        log(f"{src} via {dst} {qname} type={qtype} {how} {ms:.1f}ms")


if __name__ == "__main__":
    try:
        main()
    except PermissionError as e:
        sys.exit(f"bind failed: {e}")
