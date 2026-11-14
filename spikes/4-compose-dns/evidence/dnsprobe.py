"""Bind UDP 53 on a host address, log who asks, answer every A query with 10.9.9.9.

Proves (or disproves) that a host process can be the resolver for guests,
and that it sees each guest's real source IP (needed for per-network views).
"""
import socket, struct, sys, time

addr = sys.argv[1]
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind((addr, 53))
except OSError as e:
    print(f"BIND FAILED {addr}:53 -> {e}", flush=True)
    sys.exit(1)
print(f"BOUND {addr}:53", flush=True)
s.settimeout(1.0)
deadline = time.time() + float(sys.argv[2] if len(sys.argv) > 2 else 40)
while time.time() < deadline:
    try:
        data, src = s.recvfrom(512)
    except socket.timeout:
        continue
    tid, flags, qd = struct.unpack(">HHH", data[:6])
    i, labels = 12, []
    while data[i]:
        n = data[i]; labels.append(data[i + 1:i + 1 + n].decode()); i += n + 1
    qtype = struct.unpack(">H", data[i + 1:i + 3])[0]
    qname = ".".join(labels)
    print(f"QUERY from {src[0]}:{src[1]} name={qname} type={qtype}", flush=True)
    question = data[12:i + 5]
    if qtype == 1:
        hdr = struct.pack(">HHHHHH", tid, 0x8180, 1, 1, 0, 0)
        ans = b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 5, 4) + socket.inet_aton("10.9.9.9")
    else:
        hdr = struct.pack(">HHHHHH", tid, 0x8180, 1, 0, 0, 0)
        ans = b""
    s.sendto(hdr + question + ans, src)
print("probe done", flush=True)
