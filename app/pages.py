"""SA-authored presentation pages, generated in-app through a prompt.

An SA mid-prep says "add a page on Lakebase for this audience" — this module
makes that a conversation instead of a code change. Each page is one JSON
record on the volume (so it survives restarts and leaves with the teardown),
holding the rendered HTML and the conversation that produced it, so the next
instruction refines rather than starts over.
"""
from __future__ import annotations

import io
import json
import re
import threading
import time

import pipeline

PAGES_DIR = None  # computed from the live volume root at call time


def _dir() -> str:
    return f"{pipeline.VOL_ROOT}/pages"


def _slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return s[:40] or f"page-{int(time.time())}"


# --------------------------------------------------------------- sanitising
# Generated HTML is injected into the SPA, so the obvious script vectors are
# stripped. The author is the presenter themselves, but a model can be talked
# into emitting anything, and a demo page must never carry live script.
_KILL = [
    (re.compile(r"<script\b.*?</script>", re.I | re.S), ""),
    (re.compile(r"<(iframe|object|embed|link|meta|form|base)\b[^>]*>", re.I), ""),
    (re.compile(r"</(iframe|object|embed|form)>", re.I), ""),
    (re.compile(r"\son\w+\s*=\s*\"[^\"]*\"", re.I), ""),
    (re.compile(r"\son\w+\s*=\s*'[^']*'", re.I), ""),
    (re.compile(r"\son\w+\s*=\s*[^\s>]+", re.I), ""),
    (re.compile(r"(href|src)\s*=\s*([\"'])\s*javascript:[^\"']*\2", re.I), r"\1=\2#\2"),
]


def sanitize(html: str) -> str:
    out = html or ""
    for pat, rep in _KILL:
        out = pat.sub(rep, out)
    return out[:200_000]


# ------------------------------------------------------------------ storage
def list_pages() -> list[dict]:
    out = []
    try:
        for f in pipeline.wc().files.list_directory_contents(_dir()):
            if not (f.name or "").endswith(".json"):
                continue
            try:
                raw = pipeline.wc().files.download(f"{_dir()}/{f.name}").contents.read()
                rec = json.loads(raw)
                out.append({"slug": rec.get("slug"), "title": rec.get("title"),
                            "updated": rec.get("updated")})
            except Exception:
                continue
    except Exception:
        pass
    with _JLOCK:
        have = {r["slug"] for r in out}
        for slug, j in _JOBS.items():
            if slug not in have and j["status"] == "working":
                out.append({"slug": slug, "title": j["stub"]["title"],
                            "updated": "", "working": True})
    return sorted(out, key=lambda r: r.get("updated") or "")


def get_page(slug: str) -> dict | None:
    try:
        raw = pipeline.wc().files.download(f"{_dir()}/{slug}.json").contents.read()
        return json.loads(raw)
    except Exception:
        return None


def _save(rec: dict) -> None:
    pipeline.wc().files.upload(
        f"{_dir()}/{rec['slug']}.json",
        io.BytesIO(json.dumps(rec).encode()), overwrite=True)


def delete_page(slug: str) -> bool:
    try:
        pipeline.wc().files.delete(f"{_dir()}/{slug}.json")
        return True
    except Exception:
        return False


# --------------------------------------------------------------- generation
_SYSTEM = (
    "You produce ONE presentation page for a dark-themed Databricks demo app, "
    "as a raw HTML fragment. Rules:\n"
    "- Return ONLY the HTML fragment. No markdown fences, no <html>/<head>/"
    "<body>, no explanations before or after.\n"
    "- Self-contained: no external images, fonts, scripts or stylesheets, and "
    "no <script> tags at all. Visuals are inline SVG.\n"
    "- Use the app's design tokens via CSS variables: background var(--bg2), "
    "panels var(--surf), hairlines var(--hair), body text var(--ink2), dim "
    "text var(--dim), accent gradient var(--lava) to var(--lava2), plus "
    "var(--ie) green, var(--ka) purple, var(--sec) blue. Font is inherited — "
    "do not set font-family. Monospace labels: font:600 10px var(--mono); "
    "letter-spacing:.16em; text-transform:uppercase; color:var(--faint).\n"
    "- Structure like the app: an overline label, one big headline (clamp "
    "24-34px, weight 800, tight letter-spacing), a short dek in var(--dim), "
    "then content sections in bordered panels (border:1px solid var(--hair); "
    "border-radius:14px; background:var(--bg2); padding:20-24px).\n"
    "- One strong inline-SVG visual where it helps the story. viewBox sized, "
    "width:100%, stroke/fill from the same CSS variables.\n"
    "- Presentation copy for a live audience: short, confident, concrete. "
    "No lorem ipsum, no placeholders, no TODO.\n"
)


_JOBS: dict[str, dict] = {}     # slug -> {"status", "error", "stub"}
_JLOCK = threading.Lock()


def job_state(slug: str) -> dict | None:
    with _JLOCK:
        j = _JOBS.get(slug)
        return dict(j) if j else None


def view(slug: str) -> dict | None:
    """The page as the builder sees it: saved record merged with job state."""
    rec = get_page(slug)
    j = job_state(slug)
    if rec is None and j is None:
        return None
    if rec is None:                       # first build still in flight
        rec = {"slug": slug, "title": j["stub"]["title"], "html": "",
               "chat": j["stub"]["chat"], "created": ""}
    out = dict(rec)
    if j:
        out["job"] = {"status": j["status"], "error": j.get("error", "")}
    return out


def start(instruction: str, slug: str = "", title: str = "",
          model: str = "") -> dict:
    """Kick off one generation in the background and return at once."""
    instruction = (instruction or "").strip()
    if not instruction:
        raise ValueError("say what the page should show")
    rec = get_page(slug) if slug else None
    if rec is None:
        title = (title or instruction.split(".")[0])[:60]
        rec = {"slug": _slugify(title), "title": title, "html": "",
               "chat": [], "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    use_model = (model or "").strip() or pipeline.chat_model()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", use_model):
        raise ValueError("that model name is not valid")
    with _JLOCK:
        j = _JOBS.get(rec["slug"])
        if j and j["status"] == "working":
            raise RuntimeError("still writing this page — give it a moment")
        _JOBS[rec["slug"]] = {"status": "working", "error": "", "stub": {
            "title": rec["title"],
            "chat": rec["chat"] + [{"role": "instruction", "content": instruction}]}}

    def _run():
        try:
            generate(rec, instruction, use_model)
            with _JLOCK:
                _JOBS[rec["slug"]]["status"] = "done"
        except Exception as e:
            with _JLOCK:
                _JOBS[rec["slug"]].update(status="error", error=str(e)[:300])

    threading.Thread(target=_run, daemon=True).start()
    return {"slug": rec["slug"], "title": rec["title"], "status": "working"}


def generate(rec: dict, instruction: str, use_model: str) -> dict:
    """Create or refine a page from one instruction, keeping the conversation."""
    convo = ""
    for turn in rec["chat"][-6:]:
        convo += f"\n[{turn['role']}]\n{turn['content'][:4000]}\n"
    prompt = (
        f"{_SYSTEM}\n"
        f"Page title: {rec['title']}\n"
        + (f"Conversation so far (latest HTML included):{convo}\n" if convo else "")
        + f"\n[instruction]\n{instruction}\n\n"
        + ("Revise the latest HTML per the instruction and return the FULL "
           "updated fragment." if rec["html"] else
           "Write the page now.")
    )
    rows = pipeline.sql(f"SELECT ai_query('{use_model}', :p)",
                        params={"p": prompt}, timeout="50s", deadline_s=240)
    raw = (rows[0][0] if rows and rows[0] else "") or ""
    # models love fencing things they were told not to fence
    raw = re.sub(r"^\s*```(?:html)?\s*", "", raw)
    raw = re.sub(r"\s*```\s*$", "", raw)
    html = sanitize(raw)
    if len(html) < 80:
        raise RuntimeError("the model returned no usable page — try rewording")
    rec["html"] = html
    rec["chat"].append({"role": "instruction", "content": instruction})
    rec["chat"].append({"role": "page", "content": html[:8000]})
    rec["chat"] = rec["chat"][-12:]
    rec["model"] = use_model
    rec["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _save(rec)
    return rec
