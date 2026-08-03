#!/usr/bin/env python3
"""Build a self-contained review gallery with images embedded as data URIs.

Written as a generator so the base64 payload never passes through a chat context.
"""
import base64
import pathlib

ROOT = pathlib.Path(__file__).parent
G = ROOT / "gallery"

# (file, title, status, what to notice)
PLATES = [
    ("CORRECTION", "Read this before the plates. What runs here is not Agent Bricks.", [
        ("02-flow-live.jpg", "The gap between the label and the engine",
         "The lanes are named after Agent Bricks products. The work underneath is done by AI Functions: "
         "ai_parse_document, ai_extract, ai_mask, and ai_query. No Agent Bricks agent is called anywhere in "
         "this app. The Information Extraction lane does not use the Information Extraction agent. The "
         "Knowledge Assistant lane has no assistant behind it. The question box is hand written text to SQL, "
         "which duplicates what Genie already does as a product. Treat every plate below as a demo of the "
         "AI Functions substrate with Agent Bricks names on the lane headers."),
    ]),
    ("SHIPPED", "Deployed and running in your workspace. Paper Trail skin, live API data.", [
        ("02-flow-live.jpg", "Flow canvas, mid run",
         "Lane structure and chip design are right. The engine labels are wrong: these lanes run AI Functions, "
         "not Agent Bricks agents. Chips carry type, confidence, sensitivity and IE/KA marks. Money figures "
         "come from the API, never hardcoded."),
        ("03-flow-panel.jpg", "Routing decision record",
         "The answer to more than a label on each doc. One structured call returns type, confidence, "
         "sensitivity, retention class, both capability flags, and a why sentence. Routing becomes explainable."),
        ("04-flow-cold.jpg", "Cold open, before any run",
         "The opening demo beat. Lanes drawn and empty, no invented numbers, one clear next action."),
        ("05-chat-answer.jpg", "Ask your documents",
         "NOT AN AGENT BRICK. This is hand written text to SQL using ai_query. Genie Agents is the Databricks product that does this, and it should replace this box. The generated SQL being visible is still the right idea."),
        ("06-chat-guard.jpg", "The SQL guard holding",
         "Guard on the hand written SQL path. Real and tested, ten attacks blocked and six legitimate queries passed. If Genie replaces that path, this guard goes with it and Genie brings its own governance."),
        ("07-review.jpg", "Audit review queue",
         "Human in the loop. Deterministic window math as evidence, extracted fields against source text, "
         "and an honest note that decisions are not persisted yet."),
        ("08-settings.jpg", "Setup, pipeline running",
         "Bootstrap, generate corpus, run. Phase rail and streaming log from the real run API."),
        ("09-results.jpg", "Customer outcome page",
         "The WIIFM you asked for. Three governed tables, three named team actions, and the math with its "
         "assumption printed in visible text."),
        ("01-story.jpg", "Agentic education page, new",
         "Honest about the absence of a planner and retry loop, but it presented the hand written SQL box as an agentic pattern. That claim is withdrawn. The page needs a rewrite once real Agent Bricks endpoints are wired."),
    ]),
    ("DECIDE", "Two drawings of your lane architecture. This is the open call.", [
        ("10-v1.jpg", "V1, Swimlane Highway",
         "Four full width lanes, read like a schedule. Calmest of the two and the easier screen to talk over "
         "for ten minutes. Secure lane chips read NO AI in blue."),
        ("11-v2.jpg", "V2, The Junction",
         "Classifier as a switchyard. The both-engines path visibly splits into two engine strands and rejoins. "
         "My pick for the hero screen: it is the clearest picture of one document, two capabilities."),
    ]),
    ("ARCHIVE", "The bake-off. Four independent designs, judged on four lenses.", [
        ("13-cand-b.jpg", "B, Paper Trail, winner at 8.1",
         "Oat editorial, red used like an editor's pen. Won on brand, buyer language, and projector legibility. "
         "This is the skin the live app now wears."),
        ("12-cand-a.jpg", "A, Signal Tower, 7.1",
         "Airport departures board. Lost overall but donated the best object in the field: the split flap money "
         "board, plus the presenter key rail."),
        ("14-cand-c.jpg", "C, Document Theater, 5.9",
         "Cinematic single document. Too busy as a whole, but its parsed page set piece was grafted in as the "
         "one place ai_parse_document's work is visible."),
        ("15-cand-d.jpg", "D, Plant View, wildcard",
         "Bet the metaphor itself becomes the personalization: a manufacturer gets a plant schematic, an insurer "
         "would get something else. Lost, but the idea is worth keeping."),
        ("16-wiifm.jpg", "Original customer outcome page",
         "The first pass at what a customer does on Monday. Judges said keep it as its own closing page because "
         "its power is that it contains zero mechanism."),
    ]),
]


def b64(name: str) -> str:
    data = (G / name).read_bytes()
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


CSS = """
:root{
  --ground:#0F1920; --panel:#16242D; --ink:#EEEDE9;
  --ink-dim:rgba(238,237,233,.64); --ink-faint:rgba(238,237,233,.38);
  --line:rgba(238,237,233,.13); --line-2:rgba(238,237,233,.22);
  --accent:#FF3621; --shipped:#4CC38A; --decide:#FFB224; --archive:#8B98A5;
  --frame:rgba(0,0,0,.5);
}
@media (prefers-color-scheme: light){
  :root{
    --ground:#EEEDE9; --panel:#FFFFFF; --ink:#1B3139;
    --ink-dim:rgba(27,49,57,.70); --ink-faint:rgba(27,49,57,.45);
    --line:rgba(27,49,57,.14); --line-2:rgba(27,49,57,.24);
    --frame:rgba(27,49,57,.10);
  }
}
:root[data-theme="dark"]{
  --ground:#0F1920; --panel:#16242D; --ink:#EEEDE9;
  --ink-dim:rgba(238,237,233,.64); --ink-faint:rgba(238,237,233,.38);
  --line:rgba(238,237,233,.13); --line-2:rgba(238,237,233,.22); --frame:rgba(0,0,0,.5);
}
:root[data-theme="light"]{
  --ground:#EEEDE9; --panel:#FFFFFF; --ink:#1B3139;
  --ink-dim:rgba(27,49,57,.70); --ink-faint:rgba(27,49,57,.45);
  --line:rgba(27,49,57,.14); --line-2:rgba(27,49,57,.24); --frame:rgba(27,49,57,.10);
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
  font:15px/1.6 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased}
.mono{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
.wrap{max-width:1180px;margin:0 auto;padding:44px 28px 80px}

header{display:flex;flex-direction:column;gap:14px;padding-bottom:26px;border-bottom:1px solid var(--line-2)}
h1{margin:0;font-size:clamp(28px,4vw,42px);font-weight:800;letter-spacing:-.025em;
   text-wrap:balance;line-height:1.08}
.dek{margin:0;color:var(--ink-dim);max-width:66ch;font-size:15.5px}
.counts{display:flex;gap:22px;flex-wrap:wrap;font-size:11px;letter-spacing:.11em;
        text-transform:uppercase;color:var(--ink-faint)}
.counts b{color:var(--ink);font-variant-numeric:tabular-nums}

section{margin-top:52px}
.sec-head{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;
          padding-bottom:12px;border-bottom:1px solid var(--line)}
.sec-head h2{margin:0;font-size:13px;letter-spacing:.14em;text-transform:uppercase;font-weight:800}
.sec-head p{margin:0;color:var(--ink-dim);font-size:14px}

.chip{display:inline-block;font-size:10px;font-weight:800;letter-spacing:.1em;
      padding:3px 9px;border:1px solid;border-radius:2px;white-space:nowrap}
.chip.SHIPPED{color:var(--shipped);border-color:var(--shipped)}
.chip.DECIDE{color:var(--decide);border-color:var(--decide)}
.chip.ARCHIVE{color:var(--archive);border-color:var(--archive)}

.plate{margin-top:34px;display:flex;flex-direction:column;gap:12px}
.plate .cap{display:flex;flex-direction:column;gap:6px}
.plate h3{margin:0;font-size:19px;font-weight:800;letter-spacing:-.012em;text-wrap:balance}
.plate .note{margin:0;color:var(--ink-dim);max-width:78ch;font-size:14.5px}
.shot{display:block;width:100%;border:1px solid var(--line-2);background:var(--panel);
      box-shadow:0 10px 34px var(--frame);cursor:zoom-in;transition:border-color .15s ease}
.shot:hover,.shot:focus-visible{border-color:var(--accent);outline:none}
.shot img{display:block;width:100%;height:auto}

#lb{position:fixed;inset:0;background:rgba(8,13,17,.94);display:none;align-items:center;
    justify-content:center;padding:24px;z-index:50;cursor:zoom-out}
#lb.on{display:flex}
#lb img{max-width:100%;max-height:100%;box-shadow:0 20px 60px rgba(0,0,0,.6)}
#lb .hint{position:fixed;bottom:18px;left:0;right:0;text-align:center;color:rgba(238,237,233,.5);
          font-size:11px;letter-spacing:.1em;text-transform:uppercase}
footer{margin-top:64px;padding-top:22px;border-top:1px solid var(--line);
       color:var(--ink-faint);font-size:13px;max-width:80ch}
@media (prefers-reduced-motion: reduce){*{transition:none!important}}
"""

JS = """
const lb=document.getElementById('lb'),lbi=lb.querySelector('img');
document.querySelectorAll('.shot').forEach(b=>{
  b.addEventListener('click',()=>{lbi.src=b.querySelector('img').src;lb.classList.add('on');});
});
lb.addEventListener('click',()=>lb.classList.remove('on'));
document.addEventListener('keydown',e=>{if(e.key==='Escape')lb.classList.remove('on');});
"""


def build() -> str:
    total = sum(len(items) for _, _, items in PLATES)
    out = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>DocFlow build gallery</title>",
        f"<style>{CSS}</style></head><body>",
        '<div class="wrap"><header>',
        "<h1>DocFlow: everything built, and what still needs your call</h1>",
        '<p class="dek">A Databricks App demoing Agent Bricks document capabilities, built and '
        'certified against a live workspace in one evening. Click any plate to view it full size.</p>',
        f'<div class="counts mono"><span><b>{total}</b> plates</span>'
        '<span><b>9</b> shipped screens</span><span><b>2</b> awaiting your decision</span>'
        '<span><b>4</b> design candidates judged</span></div>',
        "</header>",
    ]
    for status, blurb, items in PLATES:
        out.append(
            f'<section><div class="sec-head"><span class="chip {status}">{status}</span>'
            f"<h2>{esc(blurb.split('.')[0])}</h2><p>{esc(blurb)}</p></div>"
        )
        for fn, title, note in items:
            out.append(
                '<div class="plate"><div class="cap">'
                f"<h3>{esc(title)}</h3><p class='note'>{esc(note)}</p></div>"
                f'<button class="shot" aria-label="Expand {esc(title)}">'
                f'<img loading="lazy" alt="{esc(title)}" src="{b64(fn)}"></button></div>'
            )
        out.append("</section>")
    out.append(
        "<footer>Every screen above renders real API data or a contract-faithful mock. "
        "No figure is hardcoded. Documents in the demo are synthetic and watermarked, vendors and "
        "people are fictional. The app and its warehouse are currently stopped so nothing bills."
        "</footer></div>"
        '<div id="lb"><img alt=""><div class="hint mono">Click anywhere or press Escape to close</div></div>'
        f"<script>{JS}</script></body></html>"
    )
    return "".join(out)


if __name__ == "__main__":
    html = build()
    dest = ROOT / "gallery.html"
    dest.write_text(html)
    print(f"wrote {dest} ({len(html)/1_000_000:.2f} MB)")
