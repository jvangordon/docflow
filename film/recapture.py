#!/usr/bin/env python3
"""Capture the DocFlow walkthrough as a numbered frame sequence.

Frames come from the real app against the real workspace: a live go-run is
triggered and the Start page is sampled while it works.
"""
import pathlib
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).parent
F = HERE / "frames"
F.mkdir(parents=True, exist_ok=True)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = "http://localhost:8899"

sys.path.insert(0, str(HERE))
import card  # noqa: E402


def shot(n: int, url: str, budget: int = 9000) -> None:
    out = F / f"{n:03d}.png"
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--window-size=1440,900", f"--virtual-time-budget={budget}",
                    f"--screenshot={out}", url], capture_output=True)
    print(f"  frame {n:03d}  {url.split('localhost:8899')[-1][:52]}")


def api(path: str, method: str = "GET"):
    req = urllib.request.Request(BASE + path, method=method,
                                 headers={"Content-Type": "application/json"},
                                 data=b"{}" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            import json
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)[:120]}


def rename(n: int, src: str) -> None:
    (F / src).rename(F / f"{n:03d}.png")



print("re-shooting the run sequence")
shot(50, f"{BASE}/#start", 9000)
print("  triggering the run"); print("  ", api("/api/go","POST"))
import time as _t
t0=_t.time(); n=60
while _t.time()-t0 < 200:
    g=api("/api/golog"); shot(n, f"{BASE}/#start", 6000); n+=5
    if g.get("phase") in ("done","error"):
        print("  run", g.get("phase"), "at", round(_t.time()-t0), "s"); break
    _t.sleep(4)
print("done")
