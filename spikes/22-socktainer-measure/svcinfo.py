#!/usr/bin/env python3
"""Summarize a `docker compose config --format json` document from stdin:
published ports, healthchecks, builds, network count. With --first-port,
print only the first published host port (used as the HTTP probe target)."""
import json
import sys

c = json.load(sys.stdin)
ports, out = [], []
for name, s in c["services"].items():
    for p in s.get("ports", []):
        if p.get("published"):
            ports.append(str(p["published"]))
            out.append(f"{name}:{p['published']}")
    if "healthcheck" in s:
        out.append(f"{name}:hc")
    if "build" in s:
        out.append(f"{name}:build")
if "--first-port" in sys.argv:
    print(ports[0] if ports else "")
else:
    print(" ".join(out), "| nets:", len(c.get("networks", {})))
