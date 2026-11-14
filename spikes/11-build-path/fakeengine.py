#!/usr/bin/env python3
"""Spike #11 stand-in Engine API. Logs every request; implements just enough
for buildx/Compose build + load: _ping, version, info, images/load,
images/{name}/json, images/json. Everything else gets 501.

Usage: python3 -I fakeengine.py <socket> <log>
"""
import http.server
import json
import os
import re
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

SOCK, LOG = sys.argv[1], sys.argv[2]
BK = ("127.0.0.1", int(os.environ.get("FL11_BK_PORT", "12340")))
API = "1.51"


def enc_bytes(b):
    # moby.buildkit.v1.BytesMessage { bytes data = 1; }
    n, v = len(b), bytearray()
    while True:
        x = n & 0x7F
        n >>= 7
        v.append(x | (0x80 if n else 0))
        if not n:
            break
    return b"\x0a" + bytes(v) + b


def dec_bytes(m):
    if not m:
        return b""
    i, n, s = 1, 0, 0
    while True:
        c = m[i]
        n |= (c & 0x7F) << s
        i += 1
        s += 7
        if not c & 0x80:
            break
    return m[i:i + n]
VER = re.compile(r"^/v\d+\.\d+")


def log(line):
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {line}\n")


def apple_image(name):
    out = subprocess.run(["container", "image", "inspect", name],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return None
    try:
        data = json.loads(out.stdout)
        return data[0] if isinstance(data, list) else data
    except Exception:
        return {}


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def address_string(self):
        return "unix"

    def log_message(self, *a):
        pass

    def body(self):
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            while True:
                size = int(self.rfile.readline().split(b";")[0].strip(), 16)
                if size == 0:
                    self.rfile.readline()
                    return
                yield self.rfile.read(size)
                self.rfile.readline()
        n = int(self.headers.get("Content-Length") or 0)
        while n > 0:
            chunk = self.rfile.read(min(n, 1 << 20))
            if not chunk:
                return
            n -= len(chunk)
            yield chunk

    def send(self, code, obj=None, ctype="application/json", extra=None):
        data = b"" if obj is None else (
            obj if isinstance(obj, bytes) else json.dumps(obj).encode())
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Api-Version", API)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def route(self):
        raw = self.path
        path, _, query = raw.partition("?")
        path = VER.sub("", path)
        hdrs = {k: v for k, v in self.headers.items()
                if k.lower() in ("upgrade", "connection", "content-type",
                                 "x-registry-auth", "user-agent")
                or k.lower().startswith("x-docker")}
        if "X-Registry-Auth" in hdrs:
            hdrs["X-Registry-Auth"] = "<redacted>"
        log(f"{self.command} {raw} {hdrs}")

        if path == "/grpc" and self.headers.get("Upgrade", "").lower() == "h2c":
            return self.grpc_proxy()
        if path == "/session" and self.headers.get("Upgrade", "").lower() == "h2c":
            return self.session_bridge()
        if path == "/_ping":
            return self.send(200, b"OK", "text/plain",
                             {"OSType": "linux", "Builder-Version": os.environ.get("FL11_BUILDER_VERSION", "2"),
                              "Docker-Experimental": "false", "Cache-Control": "no-cache"})
        if path == "/version":
            return self.send(200, {"Version": "fl11-shim", "ApiVersion": API,
                                   "MinAPIVersion": "1.44", "Os": "linux",
                                   "Arch": "arm64", "KernelVersion": "spike",
                                   "Components": [{"Name": "Engine", "Version": "fl11-shim"}]})
        if path == "/info":
            return self.send(200, {"ID": "fl11", "Name": "fl11-shim", "OSType": "linux",
                                   "Architecture": "aarch64", "ServerVersion": "fl11-shim",
                                   "Driver": "apple", "NCPU": 4, "MemTotal": 8 << 30,
                                   "OperatingSystem": "fruitlocker spike", "DefaultRuntime": "apple",
                                   "Runtimes": {"apple": {}}, "SecurityOptions": [],
                                   "Containers": 0, "Images": 0})
        if path == "/images/load" and self.command == "POST":
            fd, tmp = tempfile.mkstemp(suffix=".tar")
            n = 0
            with os.fdopen(fd, "wb") as f:
                for c in self.body():
                    n += len(c)
                    f.write(c)
            out = subprocess.run(["container", "image", "load", "-i", tmp],
                                 capture_output=True, text=True)
            os.unlink(tmp)
            log(f"  load bytes={n} rc={out.returncode} out={out.stdout.strip()!r} err={out.stderr.strip()[-200:]!r}")
            if out.returncode != 0:
                return self.send(500, {"message": out.stderr.strip()})
            names = [l for l in out.stdout.splitlines() if l and not l.startswith("[")]
            msg = "".join(json.dumps({"stream": f"Loaded image: {n}\n"}) + "\n" for n in names)
            return self.send(200, msg.encode())
        m = re.match(r"^/images/(.+)/json$", path)
        if m and self.command == "GET":
            name = m.group(1)
            img = apple_image(name)
            log(f"  inspect {name} -> {'found' if img is not None else 'missing'}")
            if img is None:
                return self.send(404, {"message": f"No such image: {name}"})
            return self.send(200, {"Id": "sha256:" + "0" * 64, "RepoTags": [name],
                                   "Os": "linux", "Architecture": "arm64", "Config": {}})
        if path == "/images/json":
            return self.send(200, [])
        return self.send(501, {"message": f"fl11 shim: {self.command} {path} not implemented"})

    def upgrade(self):
        self.wfile.write(b"HTTP/1.1 101 UPGRADED\r\nContent-Type: application/vnd.docker.raw-stream\r\n"
                         b"Connection: Upgrade\r\nUpgrade: h2c\r\n\r\n")
        self.wfile.flush()
        self.close_connection = True

    def grpc_proxy(self):
        # /grpc carries BuildKit's control API as h2c: splice raw bytes.
        up = socket.create_connection(BK)
        self.upgrade()
        stats = {"c2s": 0, "s2c": 0}

        def c2s():
            try:
                while True:
                    b = self.rfile.read1(65536)
                    if not b:
                        break
                    stats["c2s"] += len(b)
                    up.sendall(b)
            except OSError:
                pass
            try:
                up.shutdown(socket.SHUT_WR)
            except OSError:
                pass

        t = threading.Thread(target=c2s, daemon=True)
        t.start()
        try:
            while True:
                b = up.recv(65536)
                if not b:
                    break
                stats["s2c"] += len(b)
                self.connection.sendall(b)
        except OSError:
            pass
        t.join(timeout=5)
        up.close()
        log(f"  /grpc closed {stats}")

    def session_bridge(self):
        # /session: the CLI is a gRPC *server* on this conn. Stock buildkitd
        # takes sessions as a Control.Session bidi stream of BytesMessage that
        # tunnels those same h2 bytes, with the session headers as metadata.
        import grpc
        import queue
        md = [(k.lower(), v) for k, v in self.headers.items()
              if k.lower().startswith("x-docker-expose-session")]
        log(f"  /session md keys={sorted(set(k for k, _ in md))}")
        ch = grpc.insecure_channel(f"{BK[0]}:{BK[1]}")
        call = ch.stream_stream("/moby.buildkit.v1.Control/Session",
                                request_serializer=enc_bytes,
                                response_deserializer=dec_bytes)
        self.upgrade()
        q = queue.Queue()
        stats = {"c2s": 0, "s2c": 0}

        def reqs():
            while True:
                b = q.get()
                if b is None:
                    return
                yield b

        def c2s():
            try:
                while True:
                    b = self.rfile.read1(65536)
                    if not b:
                        break
                    stats["c2s"] += len(b)
                    q.put(b)
            except OSError:
                pass
            q.put(None)

        t = threading.Thread(target=c2s, daemon=True)
        t.start()
        try:
            for b in call(reqs(), metadata=md):
                stats["s2c"] += len(b)
                self.connection.sendall(b)
        except Exception as e:  # noqa: BLE001
            log(f"  /session stream end: {type(e).__name__}: {str(e)[:200]}")
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        t.join(timeout=5)
        ch.close()
        log(f"  /session closed {stats}")

    def do_GET(self): self.route()
    def do_HEAD(self): self.route()
    def do_POST(self): self.route()
    def do_DELETE(self): self.route()
    def do_PUT(self): self.route()


class S(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def export_watcher(d):
    # Host half of the moby-exporter handoff: load each finished archive into
    # Apple's image store, then ack so the exporter (and the build) completes.
    while True:
        for name in sorted(os.listdir(d)):
            if not name.endswith(".ready"):
                continue
            eid = name[:-6]
            tar = os.path.join(d, eid + ".tar")
            t0 = time.time()
            out = subprocess.run(["container", "image", "load", "-i", tar],
                                 capture_output=True, text=True)
            loaded = [l for l in out.stdout.splitlines() if l and not l.startswith("[")]
            log(f"  handoff {eid} bytes={os.path.getsize(tar)} rc={out.returncode} "
                f"loaded={loaded} {time.time() - t0:.2f}s err={out.stderr.strip()[-200:]!r}")
            for f in (tar, os.path.join(d, name)):
                os.unlink(f)
            ack = ".done" if out.returncode == 0 else ".err"
            with open(os.path.join(d, eid + ack), "w") as f:
                f.write(out.stderr.strip() or "ok")
        for name in os.listdir(d):
            p = os.path.join(d, name)
            if name.endswith((".done", ".err")) and time.time() - os.path.getmtime(p) > 30:
                os.unlink(p)
        time.sleep(0.1)


if os.environ.get("FL11_EXPORT_DIR"):
    threading.Thread(target=export_watcher, args=(os.environ["FL11_EXPORT_DIR"],),
                     daemon=True).start()

if os.path.exists(SOCK):
    os.unlink(SOCK)
log("start")
S(SOCK, H).serve_forever()
