#!/usr/bin/env python3
"""Build the visual walkthrough. Images embed as data URIs so the page is
self-contained; the base64 never passes through a chat context."""
import base64
import html
import pathlib

HERE = pathlib.Path(__file__).parent
S = HERE / "shots"


def img(name: str) -> str:
    data = (S / name).read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode()


def esc(s: str) -> str:
    return html.escape(s)


CSS = """
:root{
  --bg:#0E1114; --bg2:#12161A; --surf:#161B21; --raise:#1C222A; --inset:#0A0D10;
  --ink:#F2F0EC; --ink2:#C7CBD1; --dim:#98A1AB; --faint:#5C6670; --ghost:#333B44;
  --hair:rgba(242,240,236,.08); --hair2:rgba(242,240,236,.15);
  --lava:#FF3B20; --lava2:#FF7A45; --ie:#4ADE97; --warn:#F5A524; --sec:#5CA8E8;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --sans:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","Segoe UI",Roboto,sans-serif;
}
*{box-sizing:border-box;margin:0}
body{background:radial-gradient(1200px 520px at 78% -200px,rgba(255,59,32,.06),transparent 60%),var(--bg);
  color:var(--ink);font:16px/1.65 var(--sans);-webkit-font-smoothing:antialiased}
.wrap{max-width:940px;margin:0 auto;padding:56px 24px 120px}
.mono{font-family:var(--mono)}

.hero{border-bottom:1px solid var(--hair2);padding-bottom:34px;margin-bottom:10px}
.kick{display:flex;align-items:center;gap:10px;font:600 11px var(--mono);letter-spacing:.2em;
  text-transform:uppercase;color:var(--faint)}
.kick i{width:11px;height:11px;border-radius:3px;background:linear-gradient(135deg,var(--lava),var(--lava2));
  box-shadow:0 0 16px rgba(255,59,32,.5)}
h1{font-size:clamp(34px,5vw,52px);font-weight:800;letter-spacing:-.035em;line-height:1.05;margin:20px 0 14px}
h1 em{font-style:normal;background:linear-gradient(135deg,var(--lava),var(--lava2));
  -webkit-background-clip:text;background-clip:text;color:transparent}
.lede{font-size:18px;color:var(--dim);max-width:62ch}
.facts{display:flex;gap:26px;flex-wrap:wrap;margin-top:24px;font:500 12.5px var(--mono);color:var(--faint)}
.facts b{color:var(--ink2)}

.step{margin-top:58px}
.stephead{display:flex;align-items:flex-start;gap:18px}
.num{flex:none;width:44px;height:44px;border-radius:50%;border:1.5px solid var(--hair2);
  display:flex;align-items:center;justify-content:center;font:800 17px var(--mono);color:var(--lava2);
  background:var(--surf)}
.stephead h2{font-size:27px;font-weight:800;letter-spacing:-.025em;line-height:1.2;padding-top:7px}
.stephead .mins{margin-left:auto;flex:none;font:600 11px var(--mono);letter-spacing:.1em;
  text-transform:uppercase;color:var(--faint);padding-top:14px;white-space:nowrap}
.body{margin:16px 0 0 62px}
.body p{color:var(--ink2);margin-bottom:14px;max-width:66ch}
.body p.sub{color:var(--dim);font-size:15px}

.cmd{position:relative;margin:16px 0 20px;border:1px solid var(--hair2);border-radius:12px;
  background:var(--inset);overflow:hidden}
.cmd .bar{display:flex;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid var(--hair);
  background:rgba(242,240,236,.02)}
.cmd .bar span{font:600 10.5px var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}
.cmd button{margin-left:auto;font:700 11.5px var(--sans);color:var(--ink2);background:var(--raise);
  border:1px solid var(--hair2);border-radius:7px;padding:5px 13px;cursor:pointer}
.cmd button:hover{border-color:var(--dim);color:var(--ink)}
.cmd button.done{color:var(--ie);border-color:rgba(74,222,151,.5)}
.cmd pre{margin:0;padding:15px 16px;overflow-x:auto;font:13px/1.7 var(--mono);color:#9FD4F0;
  white-space:pre-wrap;word-break:break-all}

figure{margin:22px 0 8px}
figure img{width:100%;display:block;border:1px solid var(--hair2);border-radius:12px;
  box-shadow:0 18px 46px rgba(0,0,0,.5)}
figure.zoom img{border-radius:10px}
figcaption{margin-top:11px;font-size:13.5px;color:var(--faint);display:flex;gap:9px;align-items:flex-start}
figcaption b{color:var(--ink2);font-weight:600;flex:none}

.look{border:1px solid var(--hair2);border-left:3px solid var(--lava);border-radius:0 12px 12px 0;
  background:linear-gradient(135deg,rgba(255,59,32,.05),transparent 60%),var(--bg2);
  padding:16px 20px;margin:20px 0}
.look b{display:block;font-size:14.5px;margin-bottom:5px}
.look p{font-size:14.5px;color:var(--dim);margin:0}

.checklist{border:1px solid var(--hair);border-radius:12px;background:var(--bg2);overflow:hidden;margin:18px 0}
.checklist .row{display:grid;grid-template-columns:26px 1fr 128px;gap:12px;align-items:center;
  padding:11px 16px;border-bottom:1px solid var(--hair);font-size:14.5px}
.checklist .row:last-child{border-bottom:0}
.checklist .g{font:700 13px var(--mono)}
.g.bad{color:var(--warn)} .g.good{color:var(--ie)} .g.opt{color:var(--faint)}
.checklist .act{text-align:right;font:600 11.5px var(--mono)}
.act.btn{color:var(--warn)} .act.none{color:var(--ghost)}

.press{display:flex;gap:12px;align-items:center;padding:13px 16px;border:1px solid var(--hair2);
  border-radius:11px;background:var(--surf);margin:11px 0}
.press .b{flex:none;font:700 12px var(--sans);color:var(--warn);background:rgba(245,165,36,.1);
  border:1px solid rgba(245,165,36,.45);border-radius:7px;padding:7px 14px;white-space:nowrap}
.press .t{font-size:14.5px;color:var(--ink2)}
.press .t small{display:block;color:var(--faint);font-size:12.5px;margin-top:2px}

table{width:100%;border-collapse:collapse;font-size:14px;margin:16px 0}
th{text-align:left;font:600 10px var(--mono);letter-spacing:.14em;text-transform:uppercase;
  color:var(--faint);padding:0 12px 9px;border-bottom:1px solid var(--hair2)}
td{padding:10px 12px;border-bottom:1px solid var(--hair);color:var(--ink2)}
tr:last-child td{border-bottom:0}
td.t{font-family:var(--mono);color:var(--faint);white-space:nowrap}

.end{margin-top:64px;padding-top:28px;border-top:1px solid var(--hair2);color:var(--faint);font-size:14px}
@media (max-width:720px){.body{margin-left:0}.stephead .mins{display:none}}
"""

JS = """
document.querySelectorAll('.cmd button').forEach(b=>{
  b.addEventListener('click',async()=>{
    const t=b.closest('.cmd').querySelector('pre').innerText;
    try{ await navigator.clipboard.writeText(t); }catch(e){
      const ta=document.createElement('textarea'); ta.value=t; document.body.appendChild(ta);
      ta.select(); document.execCommand('copy'); ta.remove();
    }
    const old=b.textContent; b.textContent='Copied'; b.classList.add('done');
    setTimeout(()=>{b.textContent=old; b.classList.remove('done');},1400);
  });
});
"""


def cmd(label, text):
    return (f'<div class="cmd"><div class="bar"><span>{esc(label)}</span>'
            f'<button>Copy</button></div><pre>{esc(text)}</pre></div>')


def step(n, title, mins, body):
    return (f'<section class="step"><div class="stephead"><div class="num">{n}</div>'
            f'<h2>{esc(title)}</h2><div class="mins">{esc(mins)}</div></div>'
            f'<div class="body">{body}</div></section>')


def figure(name, cap_b, cap_t, zoom=False):
    return (f'<figure class="{"zoom" if zoom else ""}"><img alt="{esc(cap_b)}" src="{img(name)}">'
            f'<figcaption><b>{esc(cap_b)}</b><span>{esc(cap_t)}</span></figcaption></figure>')


CHECKS = [
    ("good", "App identity resolves", "passing", "good"),
    ("bad", "Serverless SQL warehouse", "Create one", "btn"),
    ("bad", "Catalog workspace.docflow", "Create schema", "btn"),
    ("bad", "Document volume writable", "Create volume", "btn"),
    ("good", "Foundation models reachable", "passing", "good"),
    ("opt", "Knowledge Assistant", "Create now", "btn"),
    ("opt", "Information Extraction agent", "steps only", "none"),
    ("bad", "Document Intelligence functions", "waits for warehouse", "none"),
    ("opt", "Billed usage available", "informational", "none"),
]

rows = "".join(
    f'<div class="row"><span class="g {g}">{"✓" if g=="good" else ("!" if g=="bad" else "○")}</span>'
    f'<span>{esc(label)}</span><span class="act {cls}">{esc(act)}</span></div>'
    for g, label, act, cls in CHECKS)

html_out = f"""<div class="wrap">
<div class="hero">
  <div class="kick"><i></i>DocFlow · visual walkthrough</div>
  <h1>Cold workspace to<br>documents <em>processing</em>.</h1>
  <p class="lede">Your workspace is empty right now: no app, no warehouse, no schema, no agents.
  Follow these eight steps and you will be watching documents move through Agent Bricks in
  about fifteen minutes.</p>
  <div class="facts">
    <span><b>8</b> steps</span><span><b>3</b> commands to copy</span>
    <span><b>4</b> buttons to press</span><span>run takes <b>~2 min</b></span>
  </div>
</div>

{step("1", "Create the app", "3 to 5 min", '''
<p>This makes the app and its own identity in Databricks. It takes a few minutes because
Databricks provisions compute for it.</p>''' + cmd("paste into terminal",
"cd ~/projects/agentbricks-doc-demo && databricks apps create docflow") + '''
<p class="sub">When it finishes it prints a URL ending in databricksapps.com. That is your app.</p>''')}

{step("2", "Upload the code and start it", "1 to 2 min", '''
<p>One line: it syncs the source into your workspace and deploys it.</p>''' + cmd("paste into terminal",
"cd ~/projects/agentbricks-doc-demo && databricks sync app /Workspace/Users/jvangordon@gmail.com/docflow-app --full && databricks apps deploy docflow --source-code-path /Workspace/Users/jvangordon@gmail.com/docflow-app") + '''
<p class="sub">Wait for <span class="mono">state: SUCCEEDED</span>.</p>''')}

{step("3", "Give the app permission to fix things", "30 sec", '''
<p>A brand new app has an identity with rights to nothing. Two grants let it repair the
workspace by itself instead of sending you to the console.</p>''' + cmd("paste into terminal",
"cd ~/projects/agentbricks-doc-demo && ./.venv/bin/python docs/grant_app.py") + '''
<div class="look"><b>What this actually does</b><p>Gives the app the "Allow cluster creation"
entitlement so the warehouse button works, and USE CATALOG plus CREATE SCHEMA so the catalog
button works. It prints exactly what it granted. Skip it and the app still runs and still
tells the truth, it just cannot self repair.</p></div>''')}

{step("4", "Open the app and read the panel", "1 min", '''
<p>Open your app URL. You land on <b>Start</b>. The left side is the setup form, the right
side is the readiness panel, and it should be unhappy. That is the point.</p>'''
+ figure("cold-start.png", "The whole Start page, cold.",
         "Form empty on the left, four checks failing on the right, Go greyed out at the bottom.")
+ f'<div class="checklist">{rows}</div>' + '''
<div class="look"><b>Two things worth noticing before you touch anything</b>
<p>Go is disabled and the sentence beside it tells you why. And the Document Intelligence
check offers no button at all, just a greyed note saying it comes after the warehouse,
because there is no compute to test on yet. The app will not hand you a control that
cannot work.</p></div>''')}

{step("5", "Press the fixes, top down", "2 min", '''
<p>Order matters and the panel enforces it. Each button reports what happened underneath itself.</p>'''
+ figure("checks-closeup.png", "Close up of the failing checks.",
         "Each red check carries an amber button on the right. Numbered steps appear when there is no API to do it for you.", zoom=True)
+ '''
<div class="press"><span class="b">Create one</span><span class="t">Serverless SQL warehouse
<small>Creates a 2X-Small that stops itself after 10 idle minutes. About a minute.</small></span></div>
<div class="press"><span class="b">Create schema</span><span class="t">Catalog workspace.docflow
<small>Creates the schema the run writes into.</small></span></div>
<div class="press"><span class="b">Create volume</span><span class="t">Document volume
<small>Creates the volume and its inbox, processed, secure, archive and generated folders.</small></span></div>
<div class="press"><span class="b">Create now</span><span class="t">Knowledge Assistant, optional
<small>You can skip this. Go creates it anyway. Pressing it early just starts the document index sooner.</small></span></div>
<div class="look"><b>Watch this happen</b><p>When the warehouse turns green, the Document
Intelligence check below it stops waiting and validates itself, because there is finally
something to test on. You did not press anything for that one.</p></div>
<p>Press <b>Re-check</b> when you are done. You want <b>6 of 6 required</b>.</p>''')}

{step("6", "Fill in the four answers", "1 min", '''
<p>Left side. These drive everything the run generates.</p>'''
+ figure("form-closeup.png", "The setup form.",
         "Customer name and industry are the two that change the demo most.", zoom=True)
+ '''
<table>
<tr><th>Field</th><th>What it changes</th></tr>
<tr><td><b>Customer name</b></td><td>Appears on every page and inside every generated document</td></tr>
<tr><td><b>Industry</b></td><td>The vocabulary, the suggested questions, and the titles of both operations pages</td></tr>
<tr><td><b>Catalog and schema</b></td><td>Where the tables, Genie space and run state live</td></tr>
<tr><td><b>Documents</b></td><td>Leave as generate everything, or point at a volume of the customer's own PDFs</td></tr>
</table>
<div class="look"><b>Try something other than Manufacturing</b><p>Insurance gives you
"Loss Run Review" and vocabulary like subrogation and loss run. Logistics gives you
"Freight Claims Recovery Desk". It is the most convincing thirty seconds of the demo and
it costs nothing to try.</p></div>
<p>Press <b>Save</b>. It flashes Saved. <b>Go is now enabled.</b></p>'''
+ figure("gobar-closeup.png", "The Go bar before you are ready.",
         "While anything is missing, Go stays grey and the sentence beside it names what is blocking.", zoom=True))}

{step("7", "Press Go and watch it work", "~2 min", '''
<p>The run log takes over the right side and streams with real timings.</p>'''
+ figure("runlog.png", "The run log, live.",
         "Every step reports its own elapsed time. This is the part to narrate.")
+ '''
<table>
<tr><th>At</th><th>What happens</th></tr>
<tr><td class="t">~8s</td><td>Schema, volume and tables confirmed</td></tr>
<tr><td class="t">~16s</td><td>Company research, using a model on the AI Gateway</td></tr>
<tr><td class="t">~34s</td><td>Documents generated, watermarked, into their own folder</td></tr>
<tr><td class="t">~35s</td><td>Knowledge Assistant created, indexing starts in the background</td></tr>
<tr><td class="t">~36 to 120s</td><td>Documents processed: parse, classify, route, extract, audit, secure</td></tr>
<tr><td class="t">~120s</td><td>Genie space created over the extracted tables, then Ready</td></tr>
</table>
<p>Switch to <b>Flow</b> while it runs. This is the screen to show a customer.</p>'''
+ figure("flow.png", "Documents moving through the bricks.",
         "Click any document to see its routing record, including the sentence explaining why it went where it did."))}

{step("8", "The payoff", "3 min", '''
<p>Three screens carry the story once the run is done.</p>'''
+ figure("ask.png", "Ask, with the work shown.",
         "Numbers go to Genie and come back with the SQL it ran. Wording goes to the Knowledge Assistant and comes back citing a document and page.")
+ '''
<p><b>Ask</b> — the suggestions under the box are written for your industry and are
guaranteed answerable from the data this run produced.</p>'''
+ figure("claims.png", "An operations screen built on the results.",
         "Titled for the industry you chose, running on the governed tables the run created.")
+ '''
<p><b>Claims</b> and <b>Suppliers</b> are the two operations screens. <b>Built</b> lists
everything the run created with per section timings.</p>''')}

<section class="step"><div class="stephead"><div class="num">✓</div>
<h2>Stand it down</h2><div class="mins">10 sec</div></div>
<div class="body">
<p>Nothing bills while idle. The warehouse stops itself after 10 minutes and Databricks stops
the app 24 hours after deploy. To stop both immediately:</p>
""" + cmd("paste into terminal", "databricks apps stop docflow") + """
<div class="look"><b>If a fix button fails</b><p>The message leads with what to do about it,
and Databricks' own wording sits behind a "what Databricks reported" disclosure. Usually it
means step 3 was skipped or did not finish.</p></div>
</div></section>

<div class="end">Every screenshot on this page is a real capture of the app running against a
Databricks workspace. Nothing is mocked up.</div>
</div>
<style>%s</style>
<script>%s</script>""" % (CSS, JS)

out = HERE / "walkthrough.html"
out.write_text(html_out)
print(f"wrote {out} ({len(html_out)/1_000_000:.2f} MB)")
