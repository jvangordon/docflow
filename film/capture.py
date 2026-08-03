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


# ---------------------------------------------------------------- act 1
print("ACT 1 · deploy cards")
card.title("t010", "A portable Databricks App", "DocFlow", "Install it in any workspace, press go, and watch documents move through Agent Bricks.", ["Deploy and demo, end to end", "Recorded against a live Databricks workspace"], "1 / 5 · install")
rename(10, "t010.png")

deploy = (HERE / "logs" / "deploy.txt").read_text()
part1, _, part2 = deploy.partition("$ databricks apps get")
card.terminal("t020", "One command deploys it", "Sync the source, deploy the app",
              part1.strip().replace("$", "<u>$</u>", 2).replace("SUCCEEDED", "<b>SUCCEEDED</b>"),
              "1 / 5 · install")
rename(20, "t020.png")
card.terminal("t030", "The app is live", "Running, with its resources bound",
              ("$ databricks apps get" + part2).strip()
              .replace("$ databricks apps get docflow", "<u>$ databricks apps get docflow</u>")
              .replace("RUNNING", "<b>RUNNING</b>").replace("ACTIVE", "<b>ACTIVE</b>"),
              "1 / 5 · install")
rename(30, "t030.png")

card.title("t040", "Setup", "Four answers,<br>then <em>go</em>.",
           "Customer, industry, where it may write, and which documents to use. The app checks the workspace and fixes what it can.",
           None, "2 / 5 · setup")
rename(40, "t040.png")

# ---------------------------------------------------------------- act 2
print("ACT 2 · setup + live run")
shot(50, f"{BASE}/#start", 9000)

print("  triggering the run")
started = api("/api/go", "POST")
print("  ", started)
t0 = time.time()

n = 60
while time.time() - t0 < 200:
    g = api("/api/golog")
    phase = g.get("phase")
    shot(n, f"{BASE}/#start", 6000)
    n += 5
    if phase in ("done", "error"):
        print(f"  run {phase} at {round(time.time()-t0)}s")
        break
    time.sleep(4)

# a couple of frames of the flow board while data is fresh
card.title("t150", "The run", "Documents move<br>through the <em>bricks</em>",
           "Parsed, classified with a written reason, then routed to the capability each document actually needs.",
           None, "3 / 5 · the run")
rename(150, "t150.png")

print("ACT 3 · the screens")
shot(160, f"{BASE}/#flow", 12000)
shot(170, f"{BASE}/#docs", 12000)

card.title("t180", "The payoff", "Ask the documents",
           "Numbers go to Genie over the extracted tables. Wording goes to the Knowledge Assistant, which cites the page it read.",
           None, "4 / 5 · answers")
rename(180, "t180.png")

q1 = urllib.parse.quote("How many warranty claims are outside their coverage window and what is the total amount?")
q2 = urllib.parse.quote("According to the warranty claim for unit SN-44781, what failed and what was claimed?")
shot(190, f"{BASE}/?q={q1}#ask", 45000)
shot(200, f"{BASE}/?q={q2}#ask", 35000)

card.title("t210", "What the customer builds next", "Two operations screens,<br>on <em>governed</em> tables",
           "The same run's data, presented the way the claims desk and the supplier team would actually work it.",
           None, "5 / 5 · outcome")
rename(210, "t210.png")
shot(220, f"{BASE}/#claims", 14000)
shot(230, f"{BASE}/#suppliers", 14000)
shot(240, f"{BASE}/#built", 14000)

g = api("/api/golog")
sec = g.get("sections", {})
total = sec.get("Total, go to ready", "")
meta = [f"go to ready <b>{total}s</b>",
        f"documents <b>{len((g.get('pipeline') or {}).get('docs', {}))}</b>",
        f"caught <b>${int(((g.get('pipeline') or {}).get('money') or {}).get('caught_usd', 0)):,}</b>"]
card.title("t250", "End to end", "Fresh workspace to<br>answered questions",
           "Everything on screen was created by the app during this recording: the documents, the assistant, the tables, and the Genie space.",
           meta, "docflow")
rename(250, "t250.png")

print("\ncaptured:", len(list(F.glob("*.png"))), "frames")
