import socket, struct, sys, time
IP_RECVDSTADDR = 7  # macOS
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.IPPROTO_IP, IP_RECVDSTADDR, 1)
s.bind(("0.0.0.0", 53)); s.settimeout(1.0)
print("BOUND 0.0.0.0:53", flush=True)
end = time.time() + 35
while time.time() < end:
    try: data, anc, _, src = s.recvmsg(512, 256)
    except socket.timeout: continue
    dst = next((socket.inet_ntoa(d[:4]) for l, t, d in anc if t == IP_RECVDSTADDR), "?")
    print(f"QUERY src={src[0]} dst={dst}", flush=True)
