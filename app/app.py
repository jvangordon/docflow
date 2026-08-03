"""DocFlow - Agent Bricks Document Intelligence demo app (Databricks App).

FastAPI backend. Every API is backed by real platform calls (see pipeline.py).
Frontend: static/index.html (flow canvas) + static/chat.html, served from /.
"""
from __future__ import annotations

import os
from typing import Optional
import tempfile
import threading

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import appconfig
import orchestrator
import pipeline

app = FastAPI(title="DocFlow")
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")

FALLBACK = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>DocFlow</title>
<style>body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
flex-direction:column;gap:14px;background:#0B141B;color:#EEEDE9;
font:15px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.dot{width:16px;height:16px;border-radius:4px;background:linear-gradient(135deg,#FF3621,#FF8A00);
box-shadow:0 0 24px rgba(255,54,33,.6);animation:p 1.4s infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.3}}b{font-size:22px;font-weight:800}
span{color:rgba(238,237,233,.5);font-size:13px}</style></head><body>
<div class="dot"></div><b>DocFlow</b><span>backend live · canvas arriving in the next deploy</span>
</body></html>"""


class Ask(BaseModel):
    question: str


class Seed(BaseModel):
    company: str = "Acme Manufacturing"
    seed: int = 38


PAGES = ("flow", "chat", "review", "results", "settings", "config", "metrics", "usecase")


def _page(name: str):
    p = os.path.join(STATIC, f"{name}.html")
    return FileResponse(p) if os.path.exists(p) else None


@app.get("/", response_class=HTMLResponse)
def index():
    for candidate in ("index", "flow", "settings"):
        resp = _page(candidate)
        if resp:
            return resp
    return HTMLResponse(FALLBACK)


@app.get("/{page}.html", response_class=HTMLResponse)
def page(page: str):
    if page not in PAGES:
        return HTMLResponse(FALLBACK, status_code=404)
    return _page(page) or HTMLResponse(FALLBACK, status_code=404)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "phase": pipeline.STATE.phase}


@app.post("/api/bootstrap")
def api_bootstrap():
    return pipeline.bootstrap()


@app.get("/api/capabilities")
def api_capabilities():
    return pipeline.probe()


@app.post("/api/seed")
def api_seed(body: Seed):
    """Generate the synthetic corpus and upload it to the volume inbox."""
    import corpus  # local module; reportlab-based, deterministic

    with tempfile.TemporaryDirectory() as td:
        manifest = corpus.generate_corpus(body.company, td, seed=body.seed)
        n = 0
        for item in manifest["generated"]:
            path = os.path.join(td, item["filename"])
            with open(path, "rb") as f:
                pipeline.wc().files.upload(
                    f"{pipeline.VOL_ROOT}/inbox/{item['filename']}", f, overwrite=True
                )
            n += 1
    return {"uploaded": n, "company": body.company,
            "watermark": "every page carries SYNTHETIC DEMO DATA",
            "types": {t: sum(1 for i in manifest["generated"] if i["type"] == t)
                      for t in {i["type"] for i in manifest["generated"]}}}


@app.post("/api/run")
def api_run():
    if not pipeline.try_start():
        return JSONResponse({"error": f"run already active: {pipeline.STATE.phase}"}, status_code=409)
    threading.Thread(target=pipeline.run_pipeline, daemon=True).start()
    return {"started": True}


@app.get("/api/state")
def api_state():
    return pipeline.STATE.snapshot()


@app.get("/api/tables/{name}")
def api_table(name: str):
    allowed = {"extract_warranty_claims", "extract_supplier_invoices", "audit_findings"}
    if name not in allowed:
        return JSONResponse({"error": "unknown table"}, status_code=404)
    rows = pipeline.sql(f"SELECT * FROM {pipeline.FQ}.{name} LIMIT 100")
    return {"table": name, "rows": rows}


@app.post("/api/ask")
def api_ask(body: Ask):
    try:
        return orchestrator.ask(body.question)
    except Exception as e:
        import logging, uuid
        ref = uuid.uuid4().hex[:8]
        logging.getLogger("docflow").exception("ask failed ref=%s", ref)
        return JSONResponse({"error": f"the question could not be answered (ref {ref})"},
                            status_code=500)


class ConfigPatch(BaseModel):
    company: Optional[str] = None
    industry: Optional[str] = None
    notes: Optional[str] = None
    accent_hex: Optional[str] = None
    doc_plan: Optional[dict] = None
    # Declared explicitly: pydantic drops undeclared fields, which silently
    # discarded the catalog, schema, volume and model the setup form sends.
    catalog: Optional[str] = None
    schema_: Optional[str] = Field(default=None, alias="schema")
    customer_volume: Optional[str] = None
    chat_endpoint: Optional[str] = None

    model_config = {"populate_by_name": True}

    def patch(self) -> dict:
        d = self.model_dump(exclude_none=True, by_alias=True)
        return d


@app.get("/api/config")
def api_config_get():
    cfg = appconfig.load_config()
    return {**cfg, "lane_coverage": appconfig.lane_coverage(cfg.get("doc_plan"))}


@app.post("/api/config")
def api_config_set(body: ConfigPatch):
    try:
        cfg = appconfig.save_config(body.patch())
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {**cfg, "lane_coverage": appconfig.lane_coverage(cfg.get("doc_plan"))}


@app.get("/theme.css")
def api_theme():
    cfg = appconfig.load_config()
    return Response(content=appconfig.theme_css(cfg.get("accent_hex")),
                    media_type="text/css",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/readiness")
def api_readiness(deep: bool = False):
    try:
        return appconfig.readiness(deep=deep)
    except Exception as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=500)


def _fix(fn, fallback: str):
    """Fixes always answer with something actionable, never a bare 500.

    The actionable sentence leads; the platform's own wording is kept but
    stripped of host names, account ids and request ids.
    """
    try:
        out = fn()
        return out if isinstance(out, dict) else {"ok": True}
    except Exception as e:
        msg = appconfig._clean(str(e))
        if "not authorized" in msg.lower() or "permission" in msg.lower():
            fallback = ("This app's identity is not allowed to do that in this "
                        "workspace. " + fallback)
        return JSONResponse({"ok": False, "human_action": fallback, "error": msg},
                            status_code=200)


@app.post("/api/fix/warehouse")
def api_fix_warehouse():
    return _fix(appconfig.create_serverless_warehouse,
                "Ask a workspace admin to give this app's service principal the "
                "'Allow cluster creation' entitlement, or to create a serverless "
                "warehouse and grant the app CAN USE on it.")


@app.post("/api/fix/catalog")
def api_fix_catalog():
    return _fix(appconfig.fix_catalog,
                "Ask a metastore admin to create the catalog, or point the app at an existing one.")


@app.post("/api/fix/assistant")
def api_fix_assistant():
    return _fix(appconfig.fix_assistant,
                "The assistant is also created automatically when you press go.")


@app.post("/api/fix/billing")
def api_fix_billing():
    return _fix(appconfig.fix_billing,
                "Enable the billing system schema from the account console.")


@app.post("/api/fix/probe")
def api_fix_probe():
    return _fix(appconfig.fix_probe,
                "Start a serverless warehouse, then re-check.")


@app.post("/api/fix/grants")
def api_fix_grants():
    return _fix(appconfig.fix_grants,
                "Grant yourself USE SCHEMA and SELECT on the schema in a SQL editor.")


@app.post("/api/fix/models")
def api_fix_models():
    return _fix(appconfig.fix_models,
                "No model answered. Add one in AI Gateway, or set a model this "
                "workspace serves under Advanced.")


@app.post("/api/fix/all")
def api_fix_all():
    """Run every available repair in dependency order, once."""
    return appconfig.fix_everything()


@app.get("/api/metrics")
def api_metrics():
    try:
        return appconfig.metrics()
    except Exception as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=500)


@app.get("/api/scan")
def api_scan():
    """Workspace inventory that feeds the setup pickers."""
    w = pipeline.wc()
    out = {"catalogs": [], "volumes": [], "warehouses": [], "endpoints": 0}
    try:
        for c in w.catalogs.list():
            if c.name in ("system",):
                continue
            entry = {"name": c.name, "schemas": []}
            try:
                for s in list(w.schemas.list(catalog_name=c.name))[:20]:
                    if s.name == "information_schema":
                        continue
                    entry["schemas"].append(s.name)
            except Exception:
                pass
            out["catalogs"].append(entry)
    except Exception as e:
        out["catalogs_error"] = str(e)[:150]
    try:
        for c in out["catalogs"]:
            for s in c["schemas"][:10]:
                try:
                    for v in w.volumes.list(catalog_name=c["name"], schema_name=s):
                        out["volumes"].append(f"/Volumes/{c['name']}/{s}/{v.name}")
                except Exception:
                    pass
    except Exception:
        pass
    try:
        out["warehouses"] = [
            {"id": x.id, "name": x.name,
             "state": str(getattr(x.state, "value", x.state)),
             "serverless": bool(getattr(x, "enable_serverless_compute", False))}
            for x in w.warehouses.list()]
    except Exception:
        pass
    try:
        out["endpoints"] = sum(1 for e in w.serving_endpoints.list()
                               if e.name.startswith("databricks-"))
    except Exception:
        pass
    try:
        out["models"] = pipeline.models_available()
        out["model_resolved"] = pipeline._MODEL["name"]
    except Exception:
        pass
    return out


class GoBody(BaseModel):
    # prepare: stage everything, stop before documents move (the default —
    # a presenter starts the flow on their own cue)
    # process: run the staged documents through the lanes
    # all: both at once, for tests and headless runs
    stage: str = "prepare"


@app.post("/api/go")
def api_go(body: GoBody | None = None):
    stage = (body.stage if body else "prepare")
    if stage not in ("prepare", "process", "all"):
        return JSONResponse({"error": f"unknown stage '{stage}'"}, status_code=400)
    cfg = appconfig.load_config()
    missing = [k for k in ("company", "industry", "catalog", "schema") if not cfg.get(k)]
    if missing:
        return JSONResponse({"error": f"complete the setup first: {', '.join(missing)}"},
                            status_code=400)
    # The same gate the page shows, enforced where it counts. A stale browser
    # tab must not be able to start a run the workspace cannot finish.
    try:
        rd = appconfig.readiness()
        if rd.get("blockers"):
            return JSONResponse(
                {"error": "workspace not ready: " + ", ".join(rd["blockers"])
                          + ". Press Set up this workspace first.",
                 "blockers": rd["blockers"]}, status_code=409)
    except Exception:
        pass                       # readiness itself failing must not strand go
    if not orchestrator.start(cfg, stage):
        return JSONResponse(
            {"error": "a run is already in progress" if orchestrator.GO["phase"] == "running"
             else "nothing is staged yet: press go first"}, status_code=409)
    return {"started": True, "stage": stage}


@app.get("/api/golog")
def api_golog():
    out = orchestrator.snapshot()
    out["pipeline"] = pipeline.STATE.snapshot()
    return out


@app.get("/api/ka")
def api_ka():
    return orchestrator.ka_state()


@app.get("/api/uc/claims")
def api_uc_claims():
    try:
        claims = pipeline.sql(
            f"SELECT doc_id, unit_serial, purchase_date, failure_date, "
            f"warranty_term_months, claim_amount, production_line, claim_status "
            f"FROM {pipeline.FQ}.extract_warranty_claims ORDER BY claim_status, claim_amount DESC")
        findings = pipeline.sql(
            f"SELECT doc_id, finding, severity, detail FROM {pipeline.FQ}.audit_findings")
        return {"claims": claims, "findings": findings}
    except Exception as e:
        return JSONResponse({"error": str(e)[:250]}, status_code=500)


@app.get("/api/uc/suppliers")
def api_uc_suppliers():
    try:
        # Vendors normalize on the name before any appended address fragment,
        # so extraction variants group as one supplier.
        spend = pipeline.sql(
            f"SELECT trim(split(vendor, ' - ')[0]) AS vendor, "
            f"count(*) AS invoices, coalesce(sum(total),0) AS total "
            f"FROM {pipeline.FQ}.extract_supplier_invoices "
            f"GROUP BY trim(split(vendor, ' - ')[0]) ORDER BY total DESC")
        flagged = pipeline.sql(
            f"SELECT f.doc_id, f.finding, f.severity, c.claim_amount, c.production_line "
            f"FROM {pipeline.FQ}.audit_findings f "
            f"LEFT JOIN {pipeline.FQ}.extract_warranty_claims c USING (doc_id)")
        return {"spend": spend, "flagged": flagged}
    except Exception as e:
        return JSONResponse({"error": str(e)[:250]}, status_code=500)


@app.get("/api/assets")
def api_assets():
    snap = orchestrator.snapshot()
    out = {"assets": snap.get("assets", {}), "sections": snap.get("sections", {}),
           "phase": snap.get("phase"), "theme": snap.get("theme", {})}
    out["ka"] = orchestrator.ka_state()
    cfg = appconfig.load_config()
    out["target"] = {"catalog": cfg.get("catalog"), "schema": cfg.get("schema")}
    try:
        counts = pipeline.sql(
            f"SELECT 'claims', count(*) FROM {pipeline.FQ}.extract_warranty_claims "
            f"UNION ALL SELECT 'invoices', count(*) FROM {pipeline.FQ}.extract_supplier_invoices "
            f"UNION ALL SELECT 'findings', count(*) FROM {pipeline.FQ}.audit_findings")
        out["tables"] = {r[0]: int(r[1]) for r in counts}
    except Exception:
        pass
    return out


if os.path.isdir(STATIC):
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
