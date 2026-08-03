#!/usr/bin/env python3
"""Render title/terminal cards for the walkthrough film in the app's design system."""
import html
import pathlib
import subprocess
import sys

OUT = pathlib.Path(__file__).parent / "frames"
OUT.mkdir(parents=True, exist_ok=True)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

BASE = """<!doctype html><meta charset="utf-8"><style>
:root{--bg:#0E1114;--ink:#F2F0EC;--dim:#9BA3AD;--faint:#5C6670;--ghost:#343B44;
 --lava:#FF3B20;--lava2:#FF7A45;--ie:#4ADE97;--ka:#B49BF6;--sec:#5CA8E8;--warn:#F5A524;
 --mono:ui-monospace,"SF Mono",Menlo,monospace;
 --sans:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI",Roboto,sans-serif;}
*{margin:0;box-sizing:border-box}
body{width:1440px;height:900px;background:
  radial-gradient(1100px 460px at 78% -140px,rgba(255,59,32,.06),transparent 60%),var(--bg);
  color:var(--ink);font-family:var(--sans);-webkit-font-smoothing:antialiased;
  display:flex;flex-direction:column;justify-content:center;padding:0 110px}
.kick{font:600 12px var(--mono);letter-spacing:.22em;text-transform:uppercase;color:var(--faint);
  display:flex;align-items:center;gap:14px}
.kick i{width:11px;height:11px;border-radius:2.5px;background:linear-gradient(135deg,var(--lava),var(--lava2));
  box-shadow:0 0 18px rgba(255,59,32,.5);display:inline-block}
h1{font-size:64px;font-weight:800;letter-spacing:-.035em;line-height:1.03;margin:26px 0 0;max-width:22ch}
h1 em{font-style:normal;background:linear-gradient(135deg,var(--lava),var(--lava2));
  -webkit-background-clip:text;background-clip:text;color:transparent}
p.sub{margin:22px 0 0;font-size:21px;color:var(--dim);max-width:60ch;line-height:1.5}
.meta{margin-top:40px;display:flex;gap:34px;font:500 13px var(--mono);color:var(--faint);flex-wrap:wrap}
.meta b{color:var(--ink)}
pre{font:14.5px/1.75 var(--mono);color:var(--dim);background:#0B0E11;border:1px solid rgba(242,240,236,.1);
  border-radius:14px;padding:26px 30px;margin-top:30px;white-space:pre-wrap;max-height:520px;overflow:hidden}
pre b{color:var(--ie);font-weight:600}
pre u{color:var(--ink);text-decoration:none}
pre i{color:var(--faint);font-style:normal}
.step{position:absolute;left:110px;bottom:64px;font:600 12px var(--mono);letter-spacing:.18em;
  text-transform:uppercase;color:var(--ghost)}
</style><body>__BODY__<div class="step">__STEP__</div></body>"""


def render(name: str, body: str, step: str = "") -> None:
    p = OUT / f"{name}.html"
    p.write_text(BASE.replace("__BODY__", body).replace("__STEP__", html.escape(step)))
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--window-size=1440,900", f"--screenshot={OUT/(name+'.png')}",
                    f"file://{p}"], capture_output=True)
    p.unlink()
    print("frame:", name)


def title(name, kick, head, sub="", meta=None, step=""):
    m = ("<div class='meta'>" + "".join(f"<span>{x}</span>" for x in (meta or [])) + "</div>") if meta else ""
    render(name, f"<div class='kick'><i></i>{kick}</div><h1>{head}</h1>"
                 f"{f'<p class=sub>{sub}</p>' if sub else ''}{m}", step)


def terminal(name, kick, head, text, step=""):
    render(name, f"<div class='kick'><i></i>{kick}</div><h1 style='font-size:44px'>{head}</h1>"
                 f"<pre>{text}</pre>", step)


if __name__ == "__main__":
    print("import and call title()/terminal()")
