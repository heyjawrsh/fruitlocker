"""fruitlocker spike #5: privileged per-gateway DNS bind.

Stand-in for a privileged helper. Never binds the wildcard: it binds
<gateway>:53 for each address the control file asks for, alongside
mDNSResponder's *:53, so the kernel hands it only queries sent to that
gateway. Run as root from a terminal (sudo needs a TTY):

    sudo /usr/bin/python3 -I gwbind.py <ctl-file> <log-file>

The control file is owned by the invoking user and drives the helper:
    up 192.168.65.1     bind this gateway (one line per address)
    exit                close everything and quit
    (empty)             hold nothing

Guard (the #4 lesson): an address is bound only while it exists on an
interface AND mDNSResponder already holds udp4 *:53, and it's closed as soon as
the interface goes away. So we never hold :53 when mDNSResponder needs to bind.

Answers `fl5-probe` with A 10.55.55.55 (TTL 0) so the harness can tell who
answered. Everything else is forwarded to the scutil --dns upstreams.
"""

import errno
import ipaddress
import os
import select
import signal
import socket
import struct
import subprocess
import sys
import time

PROBE = "fl5-probe"
PROBE_IP = "10.55.55.55"
TICK = 0.25

socks = {}        # addr -> socket
last_note = {}    # addr -> last logged reason, to avoid log spam
LOG = None


def log(msg):
    LOG.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    LOG.flush()


def read_ctl(path, uid):
    st = os.stat(path)
    if st.st_uid != uid or st.st_mode & 0o022:
        raise SystemExit("ctl file must be owned by the invoking user and not group/world writable")
    want, quit_ = set(), False
    with open(path) as f:
        for line in f:
            parts = line.split()
            if parts == ["exit"]:
                quit_ = True
            elif len(parts) == 2 and parts[0] == "up":
                ip = ipaddress.ip_address(parts[1])
                if ip.version == 4 and ip in ipaddress.ip_network("192.168.0.0/16") and parts[1].endswith(".1"):
                    want.add(parts[1])
    return want, quit_


def local_addrs():
    out = subprocess.run(["ifconfig", "-a", "inet"], capture_output=True, text=True).stdout
    return {l.split()[1] for l in out.splitlines() if l.strip().startswith("inet ")}


def mdns_holds_udp4():
    out = subprocess.run(["netstat", "-anv", "-p", "udp"], capture_output=True, text=True).stdout
    return any(l.startswith("udp4") and l.split()[3] == "*.53" for l in out.splitlines())


def note(addr, msg):
    if last_note.get(addr) != msg:
        last_note[addr] = msg
        log(f"{addr}: {msg}")


def try_bind(addr):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind((addr, 53))
        how = "plain"
    except OSError as e:
        if e.errno != errno.EADDRINUSE:
            s.close()
            raise
        s.close()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((addr, 53))
        how = "SO_REUSEADDR (plain bind got EADDRINUSE)"
    s.setblocking(False)
    socks[addr] = s
    note(addr, f"BOUND {how}")


def close(addr, why):
    socks.pop(addr).close()
    note(addr, f"CLOSED ({why})")


def reconcile(want, guard_state):
    present, mdns = guard_state
    for addr in list(socks):
        if addr not in want:
            close(addr, "not requested")
        elif addr not in present:
            close(addr, "interface gone")
        elif not mdns:
            close(addr, "mDNSResponder released udp4 *:53")
    for addr in want - set(socks):
        if addr not in present:
            note(addr, "waiting: address not on any interface")
        elif not mdns:
            note(addr, "waiting: mDNSResponder doesn't hold udp4 *:53 yet")
        else:
            try:
                try_bind(addr)
            except OSError as e:
                note(addr, f"bind failed: {e}")


def parse_upstreams():
    out = subprocess.run(["scutil", "--dns"], capture_output=True, text=True).stdout
    ups, cur = [], None
    for line in out.split("DNS configuration (for scoped queries)")[0].splitlines():
        line = line.strip()
        if line.startswith("resolver #"):
            if cur and cur["ns"]:
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
    if cur and cur["ns"]:
        ups.append(cur)
    ups = [u for u in ups if u["domain"] != "local"]
    ups.sort(key=lambda u: -(len(u["domain"].split(".")) if u["domain"] else 0))
    return ups


def parse_question(data):
    tid, flags = struct.unpack(">HH", data[:4])
    i, labels = 12, []
    while data[i]:
        n = data[i]
        labels.append(data[i + 1:i + 1 + n].decode("ascii", "replace"))
        i += n + 1
    qtype = struct.unpack(">H", data[i + 1:i + 3])[0]
    return tid, flags, ".".join(labels).lower(), qtype, data[12:i + 5]


def reply(tid, qflags, question, ips=()):
    flags = 0x8000 | (qflags & 0x0100) | 0x0400 | 0x0080
    hdr = struct.pack(">HHHHHH", tid, flags, 1, len(ips), 0, 0)
    ans = b"".join(b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 0, 4) + socket.inet_aton(ip) for ip in ips)
    return hdr + question + ans


def forward(data, qname, ups):
    for u in ups:
        d = u["domain"]
        if d is None or qname == d or qname.endswith("." + d):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as f:
                    f.settimeout(2.0)
                    f.sendto(data, (u["ns"], u["port"]))
                    return f.recvfrom(4096)[0], u
            except OSError:
                continue
    return None, None


def serve(addr, s, ups):
    try:
        data, (src, sport) = s.recvfrom(4096)
        tid, qflags, qname, qtype, question = parse_question(data)
    except (OSError, IndexError, struct.error):
        return
    if qname == PROBE:
        resp = reply(tid, qflags, question, [PROBE_IP] if qtype == 1 else [])
        how = "probe"
    else:
        resp, u = forward(data, qname, ups)
        if resp is None:
            log(f"{src} -> {addr} {qname} type={qtype} forward FAILED")
            return
        how = f"forward {u['ns']}"
    s.sendto(resp, (src, sport))
    log(f"{src} -> {addr} {qname} type={qtype} {how}")


def main():
    global LOG
    if os.geteuid() != 0:
        sys.exit("run with sudo")
    ctl, logpath = sys.argv[1], sys.argv[2]
    uid = int(os.environ.get("SUDO_UID", "0"))
    LOG = open(logpath, "a")
    os.chmod(logpath, 0o644)
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    signal.signal(signal.SIGINT, lambda *_: stop.append(1))
    ups, ups_at, guard_at, guard = parse_upstreams(), time.time(), 0, (set(), False)
    log(f"ready pid={os.getpid()} upstreams={[(u['domain'], u['ns']) for u in ups]}")
    print(f"gwbind running (pid {os.getpid()}), logging to {logpath}. Ctrl-C to stop.", flush=True)
    try:
        while not stop:
            want, quit_ = read_ctl(ctl, uid)
            if quit_:
                break
            if time.time() - guard_at >= 1:
                guard, guard_at = (local_addrs(), mdns_holds_udp4()), time.time()
            reconcile(want, guard)
            if time.time() - ups_at > 30:
                ups, ups_at = parse_upstreams(), time.time()
            ready = select.select(list(socks.values()), [], [], TICK)[0] if socks else (time.sleep(TICK) or [])
            for s in ready:
                addr = next(a for a, x in socks.items() if x is s)
                serve(addr, s, ups)
    finally:
        for addr in list(socks):
            close(addr, "helper exiting")
        log("exit")


if __name__ == "__main__":
    main()
