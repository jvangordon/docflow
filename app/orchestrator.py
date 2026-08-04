"""DocFlow go-button orchestrator.

Everything the go button does, in order, idempotently, with a live log and
per-section timings. Adopt-by-name everywhere so a rerun never duplicates.
"""
from __future__ import annotations

import io
import json
import os
import re
import tempfile
import threading
import time
from typing import Any, Optional

import pipeline

# One assistant per document domain, each indexing only its own folder.
# A single assistant swallowing the whole inbox indexed 24 files to answer
# questions about 11, and took the longest possible time to become useful.
ASSISTANTS = [
    {"display": "docflow-ka-contracts", "folder": "ka_contracts",
     "types": ("supplier_contract",),
     "about": "contracts and policy wording",
     "instructions": "Answer questions about the supplied contracts and policy "
                     "documents. Quote the clause and cite the source document "
                     "and page."},
    {"display": "docflow-ka-claims", "folder": "ka_claims",
     "types": ("warranty_claim", "quality_inspection"),
     "about": "claims and inspection wording",
     "instructions": "Answer questions about the supplied claim and inspection "
                     "documents. Cite the source document and page."},
]
LEGACY_KA = "docflow-ka"
GENIE_TITLE = "DocFlow Genie"

GO = {
    "phase": "idle",          # idle | running | done | error
    "steps": [],              # {t, name, status: run|ok|warn|err, detail}
    "sections": {},           # name -> seconds
    "started": 0.0,
    "finished": 0.0,
    "error": "",
    "theme": {},              # research output
    "assets": {},             # created/adopted asset identifiers
}
_glock = threading.Lock()


def _log(name: str, status: str, detail: str = "") -> None:
    """A step that finishes updates its own line rather than adding a second
    one, so a completed run never leaves a stale in-progress marker behind."""
    with _glock:
        t = round(time.time() - GO["started"], 1) if GO["started"] else 0
        if status != "run":
            for step in reversed(GO["steps"]):
                if step["name"] == name and step["status"] == "run":
                    step.update({"status": status, "detail": detail[:300],
                                 "t": t, "started_at": step["t"]})
                    return
        GO["steps"].append({"t": t, "name": name, "status": status,
                            "detail": detail[:300]})
    if status != "run":
        _persist()


def _section(name: str, seconds: float) -> None:
    with _glock:
        GO["sections"][name] = round(seconds, 1)


# Run state used to live only in this process. A container restart mid-run —
# which Apps do under memory pressure, and generating the corpus is the
# heaviest moment — erased the whole run: the log froze on its last line and
# Go quietly re-enabled with no error anywhere. State is now mirrored to the
# volume beside the config, so a restart resumes the story instead of hiding it.
_STATE_PATH = None


def _state_path() -> str:
    return f"{pipeline.VOL_ROOT}/run_state.json"


def _persist() -> None:
    try:
        body = json.dumps(GO).encode()
        pipeline.wc().files.upload(_state_path(), io.BytesIO(body), overwrite=True)
    except Exception:
        pass                       # persistence is a courtesy, never a blocker


def _restore() -> None:
    """Reload a run that was in flight when this process last died."""
    if GO["steps"] or GO["phase"] != "idle":
        return
    try:
        raw = pipeline.wc().files.download(_state_path()).contents.read()
        prev = json.loads(raw)
    except Exception:
        return
    if not isinstance(prev, dict) or not prev.get("steps"):
        return
    with _glock:
        GO.update(prev)
        if GO.get("phase") == "running":
            # Nothing is running in this process, so the previous run died with
            # the container. Say so plainly rather than spinning forever.
            GO["phase"] = "error"
            GO["error"] = ("The app restarted while this run was working, so it "
                           "stopped. Press Try again — finished steps are reused.")
            GO["failed_step"] = next(
                (x["name"] for x in reversed(GO["steps"]) if x["status"] == "run"),
                "The run")
            for x in GO["steps"]:
                if x["status"] == "run":
                    x["status"] = "err"
                    x["detail"] = "interrupted by an app restart"


def snapshot() -> dict:
    with _glock:
        if GO["phase"] == "idle" and not GO["steps"]:
            pass
        return json.loads(json.dumps(GO))


def _w():
    return pipeline.wc()


# ---------------------------------------------------------------- steps
def ensure_infra(cfg: dict) -> None:
    """Warehouse, catalog, schema, volume, tables. All idempotent."""
    t0 = time.time()
    w = _w()
    # warehouse
    wh = None
    for x in w.warehouses.list():
        if getattr(x, "enable_serverless_compute", False):
            wh = x
            break
    if wh is None:
        from databricks.sdk.service.sql import CreateWarehouseRequestWarehouseType
        wh = w.warehouses.create(
            name="DocFlow Serverless", cluster_size="2X-Small", max_num_clusters=1,
            auto_stop_mins=10, enable_serverless_compute=True,
            warehouse_type=CreateWarehouseRequestWarehouseType.PRO).result()
        _log("Serverless warehouse", "ok", f"created {wh.id}")
    else:
        _log("Serverless warehouse", "ok", f"using {wh.name}")
    pipeline.WAREHOUSE_ID = wh.id
    GO["assets"]["warehouse_id"] = wh.id

    cat, sch = cfg["catalog"], cfg["schema"]
    # Existence-check BEFORE create: IF NOT EXISTS still demands the CREATE
    # privilege, so an app identity dies creating a catalog that already exists.
    def exists(stmt: str) -> bool:
        try:
            return bool(pipeline.sql(stmt))
        except Exception:
            return False
    if not exists(f"SHOW CATALOGS LIKE '{cat}'"):
        pipeline.sql(f"CREATE CATALOG IF NOT EXISTS {cat}")
        GO["assets"]["catalog_created_by_us"] = True
        _log("Catalog", "ok", f"created {cat}")
    schema_existed = exists(f"SHOW SCHEMAS IN {cat} LIKE '{sch}'")
    if not schema_existed:
        pipeline.sql(f"CREATE SCHEMA IF NOT EXISTS {cat}.{sch}")
        pipeline.claim_schema(cat, sch)
        GO["assets"]["schema_created_by_us"] = True
        _log("Schema", "ok", f"created {cat}.{sch} and marked it as this demo's")
    else:
        # A schema that already exists may be the customer's. Adopt it only when
        # this app made it, or when it is empty; otherwise stop before writing a
        # single table. Refusing a demo is always cheaper than touching
        # production data.
        marked = bool(pipeline.schema_marker(cat, sch))
        foreign = pipeline.schema_contents(cat, sch)
        n_foreign = len(foreign["tables"]) + len(foreign["volumes"])
        # A schema an earlier version of this app built carries no marker but is
        # unmistakably ours: it holds tables only this demo names. Same proof
        # standard the teardown uses — two distinctive names and no strays.
        distinctive = {"extract_warranty_claims", "extract_supplier_invoices",
                       "audit_findings"}
        strays = ([t for t in foreign["tables"] if t not in pipeline.OWNED_TABLES]
                  + [v for v in foreign["volumes"] if v not in pipeline.OWNED_VOLUMES])
        provable = (not strays
                    and len(distinctive & set(foreign["tables"])) >= 2)
        if marked or provable:
            if not marked:
                pipeline.claim_schema(cat, sch)
            GO["assets"]["schema_created_by_us"] = True
            _log("Schema", "ok",
                 f"reusing {cat}.{sch}" + ("" if marked else
                 ", which holds only this demo's tables — now marked"))
        elif n_foreign == 0:
            pipeline.claim_schema(cat, sch)
            GO["assets"]["schema_created_by_us"] = True
            _log("Schema", "ok",
                 f"adopted {cat}.{sch}, which held nothing at all, and marked it")
        else:
            names = ", ".join((foreign["tables"] + foreign["volumes"])[:4])
            # Named explicitly: a collision on 'docs' or 'documents' is the
            # dangerous case, not a harmless one.
            GO["assets"]["schema_created_by_us"] = False
            raise RuntimeError(
                f"{cat}.{sch} already holds {n_foreign} object(s) this demo did "
                f"not create ({names}...). Refusing to write into it. Pick a new "
                f"schema name under Advanced on the Start page — "
                f"{cat}.docflow_demo is a safe choice — and press go again. "
                f"Nothing has been changed.")
    if not exists(f"SHOW VOLUMES IN {cat}.{sch} LIKE 'docs'"):
        pipeline.sql(f"CREATE VOLUME IF NOT EXISTS {cat}.{sch}.docs")
    if not exists(f"SHOW VOLUMES IN {cat}.{sch} LIKE 'secure'"):
        pipeline.sql(f"CREATE VOLUME IF NOT EXISTS {cat}.{sch}.secure")
    for sub in ("inbox", "processed", "archive", "generated",
                "ka_contracts", "ka_claims", "ka_all"):
        try:
            w.files.create_directory(f"/Volumes/{cat}/{sch}/docs/{sub}")
        except Exception:
            pass
    pipeline.set_target(cat, sch, "docs")
    grant_browse_access(cat, sch, cfg)
    boot = pipeline.bootstrap()
    _log("Schema, volume, tables", "ok" if not boot.get("errors") else "warn",
         f"{cat}.{sch} · {boot['statements']} statements")
    _section("Prepare workspace", time.time() - t0)


def grant_browse_access(cat: str, sch: str, cfg: dict | None = None) -> dict:
    """Let humans open what the app's identity owns.

    The app SP owns the schema it creates, so without this nobody in the room
    can open a single document: 'User does not have USE SCHEMA privilege'.
    Group names differ per workspace, so every plausible principal is tried and
    the result names the one that worked. The secure volume is deliberately
    left out — opening it should fail, and that denial is the compliance beat.
    """
    if not GO["assets"].get("schema_created_by_us"):
        _log("Browse access", "warn",
             "skipped: this schema was not created by the demo, so its "
             "permissions are left exactly as they were")
        return {"granted": [], "errors": ["schema not owned by the demo"]}
    principals = ["account users", "users"]
    import appconfig
    owner = (cfg or {}).get("owner_email") or appconfig._installer()
    if owner:
        principals.insert(0, owner)          # the person who installed it
    granted, errs = [], []
    for who in principals:
        try:
            stmts = [f"GRANT USE SCHEMA ON SCHEMA {cat}.{sch} TO `{who}`",
                     f"GRANT SELECT ON SCHEMA {cat}.{sch} TO `{who}`",
                     f"GRANT READ VOLUME ON VOLUME {cat}.{sch}.docs TO `{who}`"]
            # USE CATALOG widens access to a container the customer may own, so
            # it is only granted on a catalog this demo created itself.
            if GO["assets"].get("catalog_created_by_us"):
                stmts.insert(0, f"GRANT USE CATALOG ON CATALOG {cat} TO `{who}`")
            for g in stmts:
                pipeline.sql(g)
            granted.append(who)
        except Exception as e:
            errs.append(f"{who}: {str(e)[:70]}")
    if granted:
        _log("Browse access", "ok",
             f"{', '.join(granted)} can open the schema, tables and documents · "
             f"the secure volume alone stays locked")
    else:
        # Never silent: the presenter needs the SQL before they are on stage.
        _log("Browse access", "warn",
             f"you cannot browse the documents yet. Run this as yourself: "
             f"GRANT USE SCHEMA, SELECT ON SCHEMA {cat}.{sch} TO `<you>`; "
             f"GRANT READ VOLUME ON VOLUME {cat}.{sch}.docs TO `<you>` "
             f"· {errs[0] if errs else ''}")
    return {"granted": granted, "errors": errs}


def resolve_model() -> None:
    """Find a model this workspace actually serves before spending any time.

    Free Edition workspaces do not serve the databricks-* endpoints that
    enterprise workspaces do, so the configured name is a guess until a
    one-token probe proves it answers. Failing here, in second ten, beats
    failing at minute six with documents already generated.
    """
    t0 = time.time()
    try:
        r = pipeline.resolve_chat_model()
        _log("Language model", "ok",
             r["note"] or f"{r['model']} answers ai_query on this warehouse")
    except Exception as e:
        _log("Language model", "err", str(e)[:220])
        raise
    _section("Resolve the language model", time.time() - t0)


def research_company(cfg: dict) -> None:
    """One structured AI Gateway call: vocabulary + questions + use-case copy."""
    t0 = time.time()
    schema = json.dumps({
        "type": "json_schema",
        "json_schema": {"name": "theme", "schema": {
            "type": "object",
            "properties": {
                "tagline": {"type": "string"},
                "vocabulary": {"type": "array", "items": {"type": "string"}},
                "genie_questions": {"type": "array", "items": {"type": "string"}},
                "assistant_questions": {"type": "array", "items": {"type": "string"}},
                "claims_page_title": {"type": "string"},
                "suppliers_page_title": {"type": "string"},
                "world": {"type": "object", "properties": {
                    "site": {"type": "string"},
                    "vendors": {"type": "array", "items": {"type": "string"}},
                    "line_items": {"type": "array", "items": {"type": "string"}},
                    "carriers": {"type": "array", "items": {"type": "string"}},
                    "destinations": {"type": "array", "items": {"type": "string"}},
                    "type_labels": {"type": "object", "properties": {
                        t: {"type": "string"} for t in pipeline.DOC_TYPES},
                        "required": list(pipeline.DOC_TYPES)},
                    "contract": {"type": "object", "properties": {
                        "supplier": {"type": "string"},
                        "penalty_pct": {"type": "string"},
                        "cap_pct": {"type": "string"},
                        "warranty_months": {"type": "string"},
                        "filing_days": {"type": "string"}},
                        "required": ["supplier", "penalty_pct", "cap_pct",
                                     "warranty_months", "filing_days"]},
                    "generated": {"type": "object", "properties": {
                        "claims": {"type": "array", "items": {"type": "object",
                            "properties": {
                                "claim_id": {"type": "string"},
                                "unit_serial": {"type": "string"},
                                "component": {"type": "string"},
                                "purchase_date": {"type": "string"},
                                "warranty_term_months": {"type": "string"},
                                "failure_date": {"type": "string"},
                                "claim_amount": {"type": "string"},
                                "production_line": {"type": "string"},
                                "failure_note": {"type": "string"}},
                            "required": ["claim_id","unit_serial","component",
                                         "purchase_date","warranty_term_months",
                                         "failure_date","claim_amount",
                                         "production_line","failure_note"]}},
                        "invoices": {"type": "array", "items": {"type": "object",
                            "properties": {
                                "invoice_no": {"type": "string"},
                                "vendor": {"type": "string"}},
                            "required": ["invoice_no","vendor"]}}},
                        "required": ["claims", "invoices"]},
                    "narratives": {"type": "object", "properties": {
                        "component_names": {"type": "array", "items": {"type": "string"}},
                        "claim_failures": {"type": "array", "items": {"type": "string"}},
                        "claim_resolution": {"type": "string"},
                        "inspection_method": {"type": "string"},
                        "incident_areas": {"type": "array", "items": {"type": "string"}},
                        "incident_roles": {"type": "array", "items": {"type": "string"}},
                        "incident_narratives": {"type": "array", "items": {"type": "string"}},
                        "incident_actions": {"type": "array", "items": {"type": "string"}},
                        "hr_from_title": {"type": "string"},
                        "hr_to_title": {"type": "string"},
                        "hr_note": {"type": "string"},
                        "marketing_headline": {"type": "string"},
                        "marketing_body": {"type": "string"},
                        "marketing_bullets": {"type": "string"},
                        "contract_scope": {"type": "string"}},
                        "required": ["component_names", "claim_failures",
                                     "claim_resolution", "inspection_method",
                                     "incident_areas", "incident_roles",
                                     "incident_narratives", "incident_actions",
                                     "hr_from_title", "hr_to_title", "hr_note",
                                     "marketing_headline", "marketing_body",
                                     "marketing_bullets", "contract_scope"]},
                }, "required": ["site", "vendors", "line_items", "carriers",
                                "destinations", "type_labels", "contract",
                                "narratives", "generated"]},
                "story": {"type": "array", "items": {"type": "object",
                    "properties": {
                        "page": {"type": "string",
                                 "enum": ["documents", "flow", "ask",
                                          "claims", "suppliers"]},
                        "line": {"type": "string"},
                        "cue": {"type": "string"}},
                    "required": ["page", "line", "cue"]}},
            },
            "required": ["tagline", "vocabulary", "genie_questions",
                         "assistant_questions", "claims_page_title",
                         "suppliers_page_title", "world", "story"],
        }, "strict": True},
    })
    # The questions are shown as one-click suggestions, so they must be
    # answerable from the columns this run actually produces. Anything else
    # hands the presenter a dead end in front of the customer.
    schema_note = (
        "The ONLY data available is these columns. "
        "extract_warranty_claims(doc_id, unit_serial, purchase_date, failure_date, "
        "warranty_term_months, claim_amount, production_line, claim_status where "
        "claim_status is 'within warranty', 'outside window' or 'needs review'); "
        "extract_supplier_invoices(doc_id, vendor, invoice_no, total); "
        "audit_findings(doc_id, finding, severity, detail). "
        "Every table question you write MUST be answerable using only those "
        "columns. Do not mention any field that is not listed. Use the industry's "
        "own words for the concepts those columns represent, but never invent "
        "data that is not there."
    )
    prompt = (
        f"You are briefing a live software demo that will be shown to executives "
        f"at {cfg['company']}, a company in the {cfg['industry']} industry. "
        f"{cfg.get('notes','')}\n\n"

        "WHAT THE DEMO DOES. It generates a realistic back-office document pile "
        "for this company, then routes every document down one of five lanes on "
        "screen and answers questions about the results:\n"
        "  1. Extraction — documents whose recurring fields belong in a table "
        "(the claims and the invoices you author below).\n"
        "  2. Assistant — documents whose value is their prose, answered with "
        "page citations (contracts, policies).\n"
        "  3. Both — a document that is worth extracting AND worth asking about.\n"
        "  4. Secure filing only — sensitive material (an HR record) that no AI "
        "may read; it is masked and sealed. This lane exists to prove restraint.\n"
        "  5. No action — routine mail that is retained and ignored.\n"
        "Every lane must be convincing for THIS industry, so the words you choose "
        "have to be the words their people actually use.\n\n"

        "QUALITY BAR. Specific beats generic, always. Name real components, real "
        "roles, real sites, real failure modes for this industry. A reader who "
        "works there should recognise it and not spot a placeholder. Never write "
        "'Company A', 'Item 1', 'various', or a number ending in three zeros "
        "unless that is genuinely typical. Do not invent regulations or cite laws "
        "you are unsure of. Keep every sentence something a person would actually "
        "write on that form.\n\n"

        "WHAT TO PRODUCE.\n"
        "tagline: one line naming the business outcome, not the technology.\n"
        "vocabulary: 6 terms this industry uses daily, the ones an outsider "
        "would get wrong.\n"
        "type_labels: rename each document type into this industry's own name for "
        "it. These labels become the classification categories on screen, so they "
        "must be mutually distinct and unmistakable from a page of the document.\n"
        f"{schema_note}\n"

        "generated.claims: 5 coverage or warranty claims this company would really "
        "file. Each needs claim_id and unit_serial in their own numbering style, "
        "component naming what actually failed, purchase_date and failure_date as "
        "YYYY-MM-DD between 2023-01-01 and 2026-06-30, warranty_term_months, "
        "claim_amount in plain dollars, production_line naming the line, unit, "
        "ward or site, and failure_note of 20-40 words describing the failure the "
        "way a technician would report it. Vary amounts realistically across at "
        "least one order of magnitude. CRITICAL: exactly two claims must fall "
        "OUTSIDE coverage — failure_date later than purchase_date plus "
        "warranty_term_months — and the other three comfortably inside. That "
        "contrast is the demo's money moment, so get the arithmetic right.\n"
        "generated.invoices: 5 invoice_no and vendor pairs in this industry's "
        "numbering style, from suppliers this company would really buy from.\n"
        "narratives: the prose the documents print verbatim, in this industry's "
        "voice. component_names: 5 things they buy that can fail. claim_failures: "
        "5 failure descriptions of 20-40 words, matching those components in "
        "order. claim_resolution: one line. inspection_method: an "
        "industry-plausible QA or audit method, named precisely. "
        "incident_areas / incident_roles / incident_narratives / incident_actions: "
        "2 each, minor workplace safety events at this kind of site, 25-45 words "
        "per narrative, with a corrective action that follows from it. "
        "hr_from_title and hr_to_title: a real promotion between two real job "
        "titles here. hr_note: 15-25 words. marketing: a supplier's junk-mail "
        "headline, a 25-40 word body and 3 bullet lines separated by <br/>. "
        "contract_scope: one sentence naming what the supplier delivers.\n\n"

        "THE QUESTIONS ARE PART OF THE DEMO. They are shown as one-click "
        "suggestions and someone will press them in front of a customer, so every "
        "one must have a good answer.\n"
        "genie_questions: 3 questions about the TABLES. Each must be answerable "
        "using only the columns listed above, must return more than a single "
        "trivial row, and should build: one that counts or totals, one that "
        "compares or ranks, one that exposes the money left on the table. Use "
        "this industry's words for those columns, never the column names.\n"
        "assistant_questions: 3 questions about document WORDING, each answerable "
        "from the contract or a claim's own text — the penalty, the liability "
        "cap, the filing deadline, what a specific claim says failed. Ask them "
        "the way an operations lead would, and make each one quotable: the answer "
        "should be a clause or a sentence, not a number.\n"
        "claims_page_title and suppliers_page_title: name the work this industry "
        "actually does. Never 'Claims Operations' or 'Supplier Operations'. For "
        "insurance prefer something like 'Loss Run Review'; for healthcare "
        "'Prior Authorisation Desk'; for manufacturing 'Warranty Recovery Desk'.\n"
        "story: a 5-beat presenter script, one per page in order documents, flow, "
        "ask, claims, suppliers. Each line states the business value on screen in "
        "at most 20 words, spoken plainly. Each cue is the single next click, and "
        "the ask beat must name the exact question to click."
    )
    try:
        rows = pipeline.sql(
            f"SELECT ai_query('{pipeline.chat_model()}', :p, responseFormat => '{schema.replace(chr(39), chr(39)*2)}')",
            params={"p": prompt}, timeout="50s")
        theme = json.loads(rows[0][0])
        theme["source"] = "researched"
        with _glock:
            GO["theme"] = theme
        world = theme.get("world") or {}
        pipeline.set_labels(world.get("type_labels"))
        _log("Company research", "ok",
             (theme.get("tagline", "")[:90] + " · documents written in this "
              "industry's language"))
    except Exception as e:
        # The run continues, but the demo is no longer personalised. Say so
        # rather than letting generic pages pass as tailored ones.
        with _glock:
            GO["theme"] = {"tagline": f"Document intelligence for {cfg['company']}",
                           "source": "generic",
                           "why": f"Company research did not run: {str(e)[:120]}",
                           "story": [
                {"page": "documents", "line": "Every document here was just written, watermarked, and classified with a reason.", "cue": "Open Flow"},
                {"page": "flow", "line": "Each document takes the lane it needs — extraction, assistant, both, or sealed.", "cue": "Press Process documents, then open Ask"},
                {"page": "ask", "line": "Ask in plain language; answers arrive with SQL or a page citation.", "cue": "Click the first suggested question"},
                {"page": "claims", "line": "This is recovered money, computed from the documents you just watched.", "cue": "Open Suppliers"},
                {"page": "suppliers", "line": "Every supplier total traces back to a governed document.", "cue": "Open the secure volume — the denial is the governance story"}]}
        _log("Company research", "warn",
             f"using generic wording · research failed: {str(e)[:90]}")
    _section("Research the company", time.time() - t0)


def _call(fn, seconds: float, what: str):
    """Run a platform call with a real deadline.

    The SDK retries some failures for minutes before raising, which turns a
    permission problem into a step that just sits there. A bounded wait makes
    the same problem a sentence the presenter can act on.
    """
    box: dict = {}

    def _run():
        try:
            box["v"] = fn()
        except Exception as e:                       # noqa: BLE001
            box["e"] = e
    th = threading.Thread(target=_run, daemon=True)
    th.start()
    th.join(seconds)
    if th.is_alive():
        raise TimeoutError(
            f"{what} did not return within {int(seconds)}s. This is almost always "
            f"the app's identity lacking write access to the volume — the SDK "
            f"retries silently instead of failing. Grant the app WRITE VOLUME on "
            f"{pipeline.VOL_ROOT}, or point Advanced at a schema the app created "
            f"itself, then press Go again.")
    if "e" in box:
        raise box["e"]
    return box.get("v")


def preflight_volume() -> None:
    """Prove the volume is writable before generating anything into it."""
    probe = f"{pipeline.VOL_ROOT}/generated/.docflow-write-test"
    _call(lambda: pipeline.wc().files.upload(
        probe, io.BytesIO(b"docflow write probe"), overwrite=True),
        45, "writing a test file to the document volume")
    try:
        pipeline.wc().files.delete(probe)
    except Exception:
        pass


def build_corpus(cfg: dict) -> None:
    """Inventory customer volume, generate the standard pack into generated/."""
    t0 = time.time()
    _log("Generated documents", "run", "checking the volume is writable")
    preflight_volume()
    # A fresh corpus replaces the old one entirely. Leaving the previous run's
    # documents in the inbox meant a second company's run processed a mixed
    # pile — 36 documents, two industries, one confused demo. These folders are
    # the app's own staging areas, created by it, so clearing them is safe.
    cleared = 0
    for sub in ("inbox", "generated", "ka_contracts", "ka_claims", "ka_all"):
        try:
            for f in _w().files.list_directory_contents(f"{pipeline.VOL_ROOT}/{sub}"):
                if f.name and not f.is_directory:
                    try:
                        _w().files.delete(f"{pipeline.VOL_ROOT}/{sub}/{f.name}")
                        cleared += 1
                    except Exception:
                        pass
        except Exception:
            pass
    if cleared:
        _log("Generated documents", "run",
             f"cleared {cleared} files from the previous run first")
    _log("Generated documents", "run", "writing and uploading 24 PDFs")
    import corpus
    w = _w()
    customer_n = 0
    if cfg.get("customer_volume"):
        try:
            names = [f.name for f in w.files.list_directory_contents(cfg["customer_volume"])
                     if f.name and f.name.lower().endswith(".pdf")]
            customer_n = len(names)
            for n in names:
                # customer files are read in place at parse time via the inbox copy
                resp = w.files.download(f"{cfg['customer_volume']}/{n}")
                w.files.upload(f"{pipeline.VOL_ROOT}/inbox/{n}",
                               io.BytesIO(resp.contents.read()), overwrite=True)
            _log("Customer documents", "ok", f"{customer_n} PDFs copied to the inbox")
        except Exception as e:
            _log("Customer documents", "warn", str(e)[:160])
    world = (GO.get("theme") or {}).get("world")
    folder_of = {t: spec["folder"] for spec in ASSISTANTS for t in spec["types"]}
    with tempfile.TemporaryDirectory() as td:
        man = corpus.generate_corpus(cfg["company"], td, seed=38, world=world)
        scoped, failed = 0, []
        for i, item in enumerate(man["generated"], 1):
            path = os.path.join(td, item["filename"])
            fol = folder_of.get(item["type"])
            targets = [f"{pipeline.VOL_ROOT}/generated/{item['filename']}",
                       f"{pipeline.VOL_ROOT}/inbox/{item['filename']}"]
            if fol:
                # A copy in the owning assistant's folder, so each assistant
                # indexes only its own documents instead of the whole inbox,
                # plus a pooled copy for tiers that allow only one assistant.
                targets.append(f"{pipeline.VOL_ROOT}/{fol}/{item['filename']}")
                targets.append(f"{pipeline.VOL_ROOT}/ka_all/{item['filename']}")
            for dest in targets:
                # Re-read per upload and let each buffer go: holding every PDF
                # in memory at once is the heaviest moment of the whole run,
                # and an Apps container that runs out of memory restarts,
                # which used to erase the run silently.
                try:
                    with open(path, "rb") as f:
                        blob = f.read()
                    _call(lambda d=dest, b=blob: w.files.upload(
                        d, io.BytesIO(b), overwrite=True), 45, f"uploading {os.path.basename(dest)}")
                except Exception as e:
                    failed.append(f"{item['filename']}: {str(e)[:60]}")
                    break
            else:
                if fol:
                    scoped += 1
            if i % 8 == 0:
                _log("Generated documents", "run",
                     f"{i} of {len(man['generated'])} uploaded")
        if failed:
            raise RuntimeError(
                f"{len(failed)} of {len(man['generated'])} documents could not be "
                f"written to {pipeline.VOL_ROOT}. First: {failed[0]}")
    GO["assets"]["documents"] = {"customer": customer_n, "generated": len(man["generated"]),
                                 "pack": "back office"}
    # Say what these documents are. They carry the customer's name but the
    # document types are the standard back-office pack, not industry specific.
    skin = "in this industry's own language" if world else "standard pack"
    _log("Generated documents", "ok",
         f"{len(man['generated'])} documents named for {cfg['company']}, {skin}, "
         f"watermarked, in their own volume folder")
    _section("Build the document set", time.time() - t0)


def _ka_hint(e: Exception) -> str:
    """Name the actual failure. Guessing 'the feature is off' when the human
    can see every tile in Agents reads as the app being wrong — because it is."""
    msg = str(e)
    low = msg.lower()
    if any(k in low for k in ("permission", "403", "forbidden", "access denied")):
        return ("the app's identity is not allowed to use the Agents API here — "
                "the feature itself is on if the Create Agent page works for "
                "you. Create a Knowledge Assistant named docflow-ka-contracts "
                "pointed at the /docs/ka_contracts folder and press Go again to "
                "adopt it. Everything else runs regardless.")
    if any(k in low for k in ("not enabled", "not available", "disabled")):
        return (f"the Agents API reports itself unavailable in this workspace "
                f"({msg[:80]}). Agent Bricks is GA, so this is usually region "
                f"or tier. Everything else runs without the assistant lane.")
    return msg[:180]


_KA_THREAD: dict = {"thread": None, "created": {}}


def _capacity_ok() -> bool:
    """Is there serverless headroom left for another endpoint?

    Free Edition shares one serverless quota between the SQL warehouse, the
    app, and every agent endpoint. Creating a second assistant when the
    warehouse is already starved does not just fail — it starves the pipeline
    that the whole demo depends on.
    """
    try:
        w = _w()
        for x in w.warehouses.list():
            if not getattr(x, "enable_serverless_compute", False):
                continue
            h = w.warehouses.get(x.id).health
            msg = str(getattr(h, "message", "") or "")
            if "RESOURCE_EXHAUSTED" in msg or "limit for s" in msg:
                return False
    except Exception:
        pass
    return True


def create_assistants_early() -> None:
    """Start assistant creation the moment prepare begins, off-thread.

    Endpoint provisioning is the slowest thing the platform does in this whole
    run (minutes on Free Edition), so it overlaps research and generation.
    Sources attach later, once the scoped folders exist.
    """
    def _run():
        try:
            from databricks.sdk.service import knowledgeassistants as K
            w = _w()
            existing = {}
            try:
                for x in w.knowledge_assistants.list_knowledge_assistants():
                    existing[x.display_name or ""] = x
            except Exception:
                pass
            made = 0
            _single_only = False
            for spec in ASSISTANTS:
                try:
                    ka = existing.get(spec["display"])
                    if ka is not None and pipeline.FINGERPRINT not in (ka.description or ""):
                        # No fingerprint — a hand-made assistant still counts as
                        # ours if its sources point into our volume, which is
                        # exactly what the permission-denied remedy tells the
                        # user to set up.
                        try:
                            srcs = w.knowledge_assistants.list_knowledge_sources(ka.name)
                            if any(str(getattr(getattr(x, "files", None), "path", ""))
                                   .startswith(pipeline.VOL_ROOT) for x in srcs):
                                _log(f"Assistant · {spec['about']}", "ok",
                                     f"adopting '{spec['display']}' — it reads this "
                                     f"demo's documents")
                                _KA_THREAD["created"][spec["display"]] = ka
                                made += 1
                                continue
                        except Exception:
                            pass
                    if ka is not None and pipeline.FINGERPRINT not in (ka.description or ""):
                        # Same name, not our object. Never mutate or later delete
                        # something the customer created.
                        _log(f"Assistant · {spec['about']}", "warn",
                             f"'{spec['display']}' already exists here and was not "
                             f"created by this demo — leaving it untouched. Rename "
                             f"it or remove it to let the demo build its own.")
                        continue
                    if ka is None and made and _single_only:
                        _log(f"Assistant · {spec['about']}", "ok",
                             "this tier allows one assistant, so the first one "
                             "indexes every document type instead")
                        continue
                    if ka is None and made and not _capacity_ok():
                        _log(f"Assistant · {spec['about']}", "warn",
                             "skipped: this workspace has no serverless capacity "
                             "left, and taking more would stall the SQL warehouse "
                             "the pipeline needs. The first assistant covers the "
                             "demo; delete it later to reclaim capacity.")
                        continue
                    if ka is None:
                        ka = w.knowledge_assistants.create_knowledge_assistant(
                            K.KnowledgeAssistant(
                                display_name=spec["display"],
                                description=f"{pipeline.FINGERPRINT} Answers questions "
                                            f"about {spec['about']} with citations.",
                                instructions=spec["instructions"]))
                        _log(f"Assistant · {spec['about']}", "ok",
                             f"created · endpoint {ka.endpoint_name} · provisioning "
                             f"continues while documents generate")
                    else:
                        _log(f"Assistant · {spec['about']}", "ok",
                             f"using existing · endpoint {ka.endpoint_name}")
                    _KA_THREAD["created"][spec["display"]] = ka
                    GO["assets"].setdefault("assistants", {})[spec["display"]] = {
                        "name": ka.name, "endpoint": ka.endpoint_name,
                        "about": spec["about"]}
                    made += 1
                except Exception as e:
                    if "limit of 1" in str(e).lower() or "reached your limit" in str(e).lower():
                        _single_only = True
                        _log(f"Assistant · {spec['about']}", "ok",
                             "this tier allows one assistant, so the first one "
                             "indexes every document type instead")
                    else:
                        _log(f"Assistant · {spec['about']}", "warn", _ka_hint(e))
        except Exception as e:
            _log("Assistants", "warn", _ka_hint(e))
    th = threading.Thread(target=_run, daemon=True)
    th.start()
    _KA_THREAD["thread"] = th


def attach_assistant_sources() -> None:
    """Point each assistant at its own folder — never the whole inbox."""
    t0 = time.time()
    th = _KA_THREAD.get("thread")
    if th:
        th.join(90)
    try:
        from databricks.sdk.service import knowledgeassistants as K
        w = _w()
        for spec in ASSISTANTS:
            ka = _KA_THREAD["created"].get(spec["display"])
            if ka is None:
                continue
            # When the tier allowed only one assistant, that one indexes the
            # whole inbox so contract AND claim questions still get answers.
            lone = len(_KA_THREAD["created"]) == 1 and len(ASSISTANTS) > 1
            # ka_all holds every assistant-lane document and nothing else — never
            # the inbox, which carries the HR file no assistant may ever read.
            folder = (f"{pipeline.VOL_ROOT}/ka_all" if lone
                      else f"{pipeline.VOL_ROOT}/{spec['folder']}")
            have = False
            try:
                for src in w.knowledge_assistants.list_knowledge_sources(ka.name):
                    path = (src.files.path or "") if src.files else ""
                    if path == folder:
                        have = True
                    elif path:
                        _log(f"Assistant · {spec['about']}", "warn",
                             f"existing source points at {path[:70]} · attaching "
                             f"{spec['folder']} as well")
            except Exception:
                pass
            if have:
                continue
            outcome: list = []

            def _attach(name=ka.name, fol=folder, disp=spec["display"]):
                try:
                    w.knowledge_assistants.create_knowledge_source(name, K.KnowledgeSource(
                        display_name=f"{disp}-docs",
                        description=f"Scoped demo documents: {fol}",
                        source_type="files", files=K.FilesSpec(path=fol)))
                    outcome.append("ok")
                except Exception as ex:
                    outcome.append(str(ex))
            t = threading.Thread(target=_attach, daemon=True)
            t.start()
            t.join(75)
            if t.is_alive() or (outcome and "timed out" in outcome[0].lower()):
                _log(f"Assistant · {spec['about']}", "ok",
                     f"source attaching in the background · indexes only "
                     f"{spec['folder']}, not the inbox")
            elif outcome and outcome[0] == "ok":
                _log(f"Assistant · {spec['about']}", "ok",
                     f"indexing {spec['folder']} only · a fraction of the corpus, "
                     f"so it is ready sooner")
            else:
                _log(f"Assistant · {spec['about']}", "warn",
                     f"source not attached yet, a rerun retries · "
                     f"{outcome[0][:100] if outcome else ''}")
    except Exception as e:
        _log("Assistants", "warn", str(e)[:180])
    _section("Attach assistant sources", time.time() - t0)


def sync_assistant_sources() -> None:
    """Tell each assistant its documents changed, over the sync API.

    This is the continuous-documents story in one call: a fresh corpus lands,
    POST {assistant}/knowledge-sources:sync, and the index catches up without
    deleting or re-attaching anything.
    """
    try:
        w = _w()
        for spec in ASSISTANTS:
            ka = _KA_THREAD["created"].get(spec["display"])
            if ka is None:
                continue
            try:
                w.knowledge_assistants.sync_knowledge_sources(ka.name)
                _log(f"Assistant · {spec['about']}", "run",
                     "re-indexing the fresh documents (sync API)")
            except Exception:
                pass                     # brand-new sources are already indexing
    except Exception:
        pass


def seed_assistant_examples() -> None:
    """Write the wording questions onto the assistants as platform examples.

    Questions belong on the Databricks objects, not in the app: an assistant
    opened in the workspace should show its own example questions. The app's
    Ask page then surfaces what the platform holds rather than owning a copy.
    """
    theme = GO.get("theme") or {}
    qs = [q for q in (theme.get("assistant_questions") or []) if q]
    if not qs:
        return
    contract_kw = ("contract", "agreement", "clause", "penalt", "policy",
                   "terms", "deadline", "notice", "filing")
    split = {"docflow-ka-contracts": [], "docflow-ka-claims": []}
    for q in qs:
        key = ("docflow-ka-contracts" if any(k in q.lower() for k in contract_kw)
               else "docflow-ka-claims")
        split[key].append(q)
    # neither assistant should sit empty when questions exist
    for k in split:
        if not split[k]:
            split[k] = qs[:1]
    try:
        from databricks.sdk.service import knowledgeassistants as K
        w = _w()
        for spec in ASSISTANTS:
            ka = _KA_THREAD["created"].get(spec["display"])
            if ka is None:
                continue
            try:
                have = list(w.knowledge_assistants.list_examples(ka.name))
            except Exception:
                have = []
            if have:
                continue
            n = 0
            for q in split.get(spec["display"], [])[:3]:
                try:
                    w.knowledge_assistants.create_example(
                        ka.name, K.Example(question=q))
                    n += 1
                except Exception:
                    break
            if n:
                _log(f"Assistant · {spec['about']}", "ok",
                     f"{n} example question{'s' if n > 1 else ''} written onto "
                     f"the assistant · visible when it is opened in Databricks")
    except Exception:
        pass


def platform_questions() -> dict:
    """Questions as Databricks holds them; the app is a mirror, not the owner."""
    out = {"assistant": [], "genie": [], "source": "app"}
    w = _w()
    try:
        for spec in ASSISTANTS:
            st = ka_state(spec["display"])
            if st.get("name"):
                for ex in w.knowledge_assistants.list_examples(st["name"]):
                    if ex.question:
                        out["assistant"].append(ex.question)
    except Exception:
        pass
    try:
        sid = GO["assets"].get("genie_space_id")
        if sid:
            sp = w.genie.get_space(sid)
            raw = getattr(sp, "serialized_space", "") or ""
            found = re.findall(r'"question"\s*:\s*"([^"]{8,160})"', raw)
            out["genie"].extend(found[:4])
    except Exception:
        pass
    theme = GO.get("theme") or {}
    if out["assistant"] or out["genie"]:
        out["source"] = "databricks"
    if not out["assistant"]:
        out["assistant"] = list(theme.get("assistant_questions") or [])[:3]
    if not out["genie"]:
        out["genie"] = list(theme.get("genie_questions") or [])[:3]
    return out


def watch_stalls() -> None:
    """Say something when a step has been running an unreasonably long time."""
    def _run():
        warned = set()
        while GO.get("phase") == "running":
            now = time.time() - (GO.get("started") or now_fallback())
            with _glock:
                live = [(x["name"], x["t"]) for x in GO["steps"] if x["status"] == "run"]
            for name, started_at in live:
                if name in warned or name.startswith("Assistant"):
                    continue          # assistants report their own progress
                if now - started_at > 100:
                    warned.add(name)
                    _log(name, "run",
                         f"still working after {int(now - started_at)}s — if this "
                         f"does not move, the app's identity probably cannot write "
                         f"to {pipeline.VOL_ROOT}")
            time.sleep(10)
    def now_fallback():
        return time.time()
    threading.Thread(target=_run, daemon=True).start()


def watch_assistants() -> None:
    """Keep the log honest about assistant progress until they can answer.

    Assistants are the slowest thing in the run — minutes of endpoint
    provisioning, then background indexing — so their rows stay live and
    self-updating rather than going quiet after 'created'. Everything else
    proceeds in parallel; nothing waits on this.
    """
    about = {spec["display"]: spec["about"] for spec in ASSISTANTS}

    def _run():
        deadline = time.time() + 1800          # 30 min ceiling, then stop asking
        pending = set(about)
        last = {}
        while pending and time.time() < deadline:
            for disp in sorted(pending):
                try:
                    st = ka_state(disp)
                except Exception:
                    continue
                name = f"Assistant · {about[disp]}"
                if st.get("ready") and st.get("indexed"):
                    _log(name, "ok", "ready · answering with page citations")
                    pending.discard(disp)
                    continue
                if st.get("endpoint") and st.get("sources"):
                    msg = "endpoint live · indexing its documents"
                elif st.get("endpoint"):
                    msg = "endpoint live · waiting for documents to attach"
                else:
                    msg = "provisioning its endpoint, this is the slow part"
                if last.get(disp) != msg:
                    _log(name, "run", msg)
                    last[disp] = msg
            time.sleep(12)
        for disp in pending:
            _log(f"Assistant · {about[disp]}", "warn",
                 "still indexing in the background · Ask falls back to governed "
                 "SQL until it is ready, then switches on its own")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    _KA_THREAD["watch"] = t


def report_ka() -> None:
    """Close the run with each assistant's true state instead of a guess."""
    for spec in ASSISTANTS:
        try:
            st = ka_state(spec["display"])
            if st.get("ready") and st.get("indexed"):
                _log(f"Assistant · {spec['about']}", "ok",
                     f"ready · {st.get('endpoint', '')} answers with citations")
            elif st.get("endpoint"):
                _log(f"Assistant · {spec['about']}", "ok",
                     f"still indexing its own folder · Ask answers from the "
                     f"extracted tables until it is ready, then switches on its own")
        except Exception:
            pass


def ensure_genie() -> None:
    """Create or adopt the Genie space over the extracted tables."""
    t0 = time.time()
    w = _w()
    tables = sorted([f"{pipeline.FQ}.extract_warranty_claims",
                     f"{pipeline.FQ}.extract_supplier_invoices",
                     f"{pipeline.FQ}.audit_findings"])
    ser = json.dumps({"version": 2,
                      "data_sources": {"tables": [{"identifier": t} for t in tables]}})
    try:
        sid = None
        for sp in w.genie.list_spaces().spaces or []:
            if (sp.title or "") == GENIE_TITLE:
                # Only adopt a space this demo made; a customer space that
                # happens to share the title is left exactly as it is.
                desc = getattr(sp, "description", "") or ""
                if desc and pipeline.FINGERPRINT not in desc:
                    _log("Genie space", "warn",
                         f"a space titled '{GENIE_TITLE}' exists here and was not "
                         f"created by this demo — leaving it untouched")
                    sid = None
                    break
                sid = sp.space_id
                break
        if sid:
            w.genie.update_space(sid, serialized_space=ser,
                                 warehouse_id=pipeline.warehouse_id())
            _log("Genie space", "ok", "updated with the extracted tables")
        else:
            sp = w.genie.create_space(warehouse_id=pipeline.warehouse_id(),
                                      serialized_space=ser, title=GENIE_TITLE)
            sid = sp.space_id
            _log("Genie space", "ok", "created over the extracted tables")
        GO["assets"]["genie_space_id"] = sid
    except Exception as e:
        _log("Genie space", "warn", str(e)[:200])
    _section("Create the Genie space", time.time() - t0)


def run_documents() -> None:
    t0 = time.time()
    _log("Process documents", "run", "parse, classify, route, extract, audit, secure")
    pipeline.run_pipeline()          # synchronous; stage timings land in STATE
    snap = pipeline.STATE.snapshot()
    if snap["phase"] == "error":
        _log("Process documents", "err", snap.get("error", "")[:200])
        raise RuntimeError(snap.get("error") or "pipeline error")
    _log("Process documents", "ok",
         f"{len(snap['docs'])} documents · caught ${snap['money'].get('caught_usd', 0):,.0f}")
    for k, v in pipeline.STATE.stage_timings():
        pass
    for st in pipeline.STATE.stage_timings():
        _section(f"stage:{st['name']}", st["seconds"])
    _section("Process the documents", time.time() - t0)


def go(cfg: dict, stage: str = "all") -> None:
    """Two stages so a presenter controls the moment documents start moving.

    prepare: workspace, model, research, documents, agents. Ends 'prepared'
             with everything staged and nothing processed.
    process: the documents flow through the lanes. Pressed from the Flow page
             so the room watches it live, and re-pressable to run it again.
    all:     both, for tests and headless runs.
    """
    with _glock:
        if GO["phase"] == "running":
            return
        if stage == "process":
            # Keep the prepare log, theme and assets: this is act two of the
            # same run, not a new one.
            GO.update({"phase": "running", "error": ""})
        else:
            GO.update({"phase": "running", "steps": [], "sections": {},
                       "started": time.time(), "finished": 0.0, "error": "",
                       "theme": {}, "assets": {}})
    # Clear the previous run's board immediately. Otherwise the first seconds
    # of a new run show the last run's finished results under a "live" header.
    with pipeline._lock:
        pipeline.STATE.docs = {}
        pipeline.STATE.phase = "staged" if stage == "prepare" else "starting"
        pipeline.STATE.money = {"caught_usd": 0.0, "cost_usd": 0.0}
    try:
        if stage in ("all", "prepare"):
            ensure_infra(cfg)
            resolve_model()          # fail in second ten, not minute six
            create_assistants_early()   # endpoint provisioning is the slow
                                        # part; overlap it with everything else
            watch_assistants()          # and report its progress live
            watch_stalls()              # and never let a step sit silent
            research_company(cfg)
            build_corpus(cfg)
            attach_assistant_sources()  # scoped folders now exist
            sync_assistant_sources()    # fresh corpus -> re-index on demand
            seed_assistant_examples()   # questions live on the platform objects
        if stage == "prepare":
            docs = GO["assets"].get("documents", {})
            n = int(docs.get("generated", 0)) + int(docs.get("customer", 0))
            with _glock:
                GO["phase"] = "prepared"
            _log("Staged", "ok",
                 f"{n} documents waiting in the inbox · agents deployed · "
                 f"press Process documents on the Flow page and watch")
            return
        run_documents()
        ensure_genie()               # after tables exist
        report_ka()                  # honest status, never a wait
        with _glock:
            GO["phase"] = "done"
            GO["finished"] = time.time()
            GO["finished_at"] = time.strftime("%H:%M", time.localtime())
            GO["assets"]["run_label"] = (
                f"run {pipeline.STATE.run_id} at {GO['finished_at']}")
        _log("Ready", "ok", "ask a question on the Ask page")
        _section("Total, go to ready", GO["finished"] - GO["started"])
    except Exception as e:
        # Name the step that was in flight, so "it stopped" is never the whole
        # story the presenter gets.
        import traceback
        tb = traceback.format_exc()
        with _glock:
            GO["traceback"] = tb[-1200:]
            inflight = next((x["name"] for x in reversed(GO["steps"])
                             if x["status"] == "run"), "")
            GO["phase"] = "error"
            GO["error"] = str(e)[:400]
            GO["failed_step"] = inflight
            GO["finished"] = time.time()
        _log(inflight or "Stopped", "err",
             f"{str(e)[:220]} · press Go to retry — completed steps are reused")
        _persist()


def start(cfg: dict, stage: str = "all") -> bool:
    with _glock:
        if GO["phase"] == "running":
            return False
        if stage == "process" and GO["phase"] not in ("prepared", "done", "error"):
            return False             # nothing staged yet: go prepares first
    threading.Thread(target=go, args=(cfg, stage), daemon=True).start()
    return True


# ---------------------------------------------------------------- ask
def ka_state(display: str | None = None) -> dict:
    """True state of one assistant (by display name) or the first usable one.

    An endpoint being Ready proves serving works, not that the assistant can
    answer: with no attached source it errors 'qgen requires at least one
    retrieval tool'. Ready therefore requires a source whenever the assistant
    record is visible.
    """
    w = _w()
    wanted = [display] if display else [a["display"] for a in ASSISTANTS] + [LEGACY_KA]
    eps = []
    try:
        eps = [e.name for e in w.serving_endpoints.list()
               if e.name and e.name.startswith("ka-")]
    except Exception:
        pass
    try:
        for x in w.knowledge_assistants.list_knowledge_assistants():
            if (x.display_name or "") in wanted:
                out = {"display": x.display_name,
                       "state": str(x.state).split(".")[-1] if x.state else "",
                       "endpoint": x.endpoint_name, "name": x.name}
                try:
                    srcs = list(w.knowledge_assistants.list_knowledge_sources(x.name))
                    out["sources"] = [str(sc.state).split(".")[-1] if sc.state else ""
                                      for sc in srcs]
                except Exception:
                    out["sources"] = []
                out["ready"] = bool(out.get("endpoint")) and bool(out["sources"])
                out["indexed"] = any(v in ("UPDATED", "READY", "ACTIVE", "ONLINE")
                                     for v in out["sources"])
                if display or (out["ready"] and out["indexed"]):
                    return out
    except Exception:
        pass
    if not display and eps:
        return {"state": "ACTIVE", "endpoint": eps[0], "sources": [],
                "ready": True, "via": "endpoint"}
    return {"state": "absent", "ready": False, "display": display}


def assistants_state() -> list[dict]:
    return [dict(ka_state(a["display"]), about=a["about"]) for a in ASSISTANTS]


def _attach_source_async() -> None:
    """One quiet attempt to give every source-less assistant its folder."""
    def _run():
        try:
            from databricks.sdk.service import knowledgeassistants as K
            w = _w()
            by_display = {}
            for x in w.knowledge_assistants.list_knowledge_assistants():
                by_display[x.display_name or ""] = x
            made = 0
            _single_only = False
            for spec in ASSISTANTS:
                ka = by_display.get(spec["display"])
                if ka is None:
                    continue
                try:
                    if list(w.knowledge_assistants.list_knowledge_sources(ka.name)):
                        continue
                except Exception:
                    pass
                w.knowledge_assistants.create_knowledge_source(ka.name, K.KnowledgeSource(
                    display_name=f"{spec['display']}-docs",
                    description="Scoped demo documents",
                    source_type="files",
                    files=K.FilesSpec(path=f"{pipeline.VOL_ROOT}/{spec['folder']}")))
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


def route_question(question: str) -> str:
    """tables | documents, via one small structured call. Falls back to keywords."""
    schema = json.dumps({"type": "json_schema", "json_schema": {
        "name": "route", "schema": {
            "type": "object",
            "properties": {"route": {"type": "string", "enum": ["tables", "documents"]}},
            "required": ["route"]}, "strict": True}})
    try:
        rows = pipeline.sql(
            f"SELECT ai_query('{pipeline.chat_model()}', :p, responseFormat => '{schema.replace(chr(39), chr(39)*2)}')",
            params={"p": "Route this question. 'tables' when it asks about counts, sums, "
                         "amounts, dates or comparisons over extracted fields. 'documents' "
                         "when it asks what a document says, requires, or allows. "
                         f"Question: {question}"}, timeout="50s")
        return json.loads(rows[0][0])["route"]
    except Exception:
        docish = any(k in question.lower() for k in
                     ("say", "says", "state", "require", "clause", "contract",
                      "policy", "manual", "allow", "wording", "according"))
        return "documents" if docish else "tables"


def ask_genie(question: str) -> dict:
    w = _w()
    sid = GO["assets"].get("genie_space_id")
    if not sid:
        try:
            for sp in w.genie.list_spaces().spaces or []:
                if (sp.title or "") == GENIE_TITLE:
                    sid = sp.space_id
                    GO["assets"]["genie_space_id"] = sid
                    break
        except Exception:
            sid = None
    if not sid:
        # No Genie space visible to this identity: answer through governed SQL
        # so the question still gets a real, sourced answer.
        t0 = time.time()
        out = pipeline.ask_structured(question)
        out["engine"] = "sql"
        out["seconds"] = round(time.time() - t0, 1)
        if not out.get("error"):
            out["text"] = "Answer from the extracted tables."
        return out
    t0 = time.time()
    msg = w.genie.start_conversation_and_wait(sid, question)
    out = {"engine": "genie", "seconds": round(time.time() - t0, 1),
           "space_id": sid, "text": "", "sql": "", "rows": []}
    for a in (msg.attachments or []):
        if a.text and a.text.content:
            out["text"] = a.text.content
        if a.query and a.query.query:
            out["sql"] = a.query.query
            try:
                res = w.genie.get_message_query_result_by_attachment(
                    sid, msg.conversation_id, msg.id, a.attachment_id)
                sr = res.statement_response
                if sr and sr.result and sr.result.data_array:
                    out["rows"] = sr.result.data_array[:20]
                if sr and sr.manifest and sr.manifest.schema and sr.manifest.schema.columns:
                    out["columns"] = [c.name for c in sr.manifest.schema.columns]
            except Exception:
                pass
    return out


def _sql_fallback(question: str, why: str) -> dict:
    """Answer from the governed tables when the assistant cannot yet.

    Whoever is presenting must never be shown a platform error. The tables
    exist, so the question still gets a real, sourced answer with an honest
    note about which engine produced it.
    """
    t0 = time.time()
    out = pipeline.ask_structured(question)
    out["engine"] = "sql"
    out["seconds"] = round(time.time() - t0, 1)
    out["note"] = why
    if not out.get("error") and not out.get("text"):
        out["text"] = "Answered from the extracted tables."
    return out


def ask_assistant(question: str) -> dict:
    """Send a wording question to the assistant that owns that domain."""
    ql = question.lower()
    contractish = any(k in ql for k in
                      ("contract", "agreement", "clause", "penalt", "policy",
                       "terms", "deadline", "notice", "termination", "goodwill",
                       "filing"))
    order = list(ASSISTANTS) if contractish else list(reversed(ASSISTANTS))
    states = [(spec, ka_state(spec["display"])) for spec in order]
    pick = next(((sp, st) for sp, st in states
                 if st.get("ready") and st.get("indexed")), None) \
        or next(((sp, st) for sp, st in states if st.get("ready")), None)
    if not pick:
        if any(st.get("endpoint") and not st.get("sources") for _, st in states):
            _attach_source_async()
        waiting = ", ".join(sp["about"] for sp, st in states if st.get("endpoint"))
        return _sql_fallback(
            question,
            f"The assistants ({waiting or 'both'}) are still reading their "
            f"documents, so this came from the governed tables. Ask again "
            f"shortly for a cited answer.")
    spec, st = pick
    w = _w()
    t0 = time.time()
    try:
        # Knowledge Assistant endpoints speak the Responses API: input, not messages.
        raw = w.api_client.do(
            "POST", f"/serving-endpoints/{st['endpoint']}/invocations",
            body={"input": [{"role": "user", "content": question}]})
        text = ""
        for item in (raw.get("output") or []):
            for c in (item.get("content") or []):
                if isinstance(c, dict) and c.get("text"):
                    text += c["text"]
        low = (text or "").strip().lower().rstrip(".")
        if not text or low in ("internal error", "error"):
            return _sql_fallback(
                question,
                "The assistant could not answer that yet, so this came from the "
                "governed tables.")
        return {"engine": "assistant", "seconds": round(time.time() - t0, 1),
                "text": text, "endpoint": st["endpoint"], "assistant": spec["about"]}
    except Exception as e:
        msg = str(e)
        if "retrieval tool" in msg or "KBQA" in msg:
            _attach_source_async()
            return {"engine": "assistant", "pending": True,
                    "text": "That assistant is not connected to its documents yet. "
                            "Connecting it now — ask this exact question again in a "
                            "few minutes."}
        return _sql_fallback(
            question,
            f"The assistant is unavailable right now, so this came from the "
            f"governed tables. ({msg[:80]})")


def ask(question: str, obo_token: str = "") -> dict:
    route = route_question(question)
    if route == "tables" and obo_token:
        # Structured answers run as the person asking, under their own
        # permissions — the app's identity never touches their data path.
        try:
            t0 = time.time()
            out = pipeline.ask_structured(question, obo_token=obo_token)
            out["engine"] = "sql"
            out["seconds"] = round(time.time() - t0, 1)
            out["as_user"] = True
            if not out.get("error") and not out.get("text"):
                out["text"] = "Answered from the extracted tables, as you."
            if not out.get("error"):
                out["route"] = route
                return out
        except Exception:
            pass                        # fall through to the app-identity path
    out = ask_genie(question) if route == "tables" else ask_assistant(question)
    out["route"] = route
    return out
