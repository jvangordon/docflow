"""DocFlow go-button orchestrator.

Everything the go button does, in order, idempotently, with a live log and
per-section timings. Adopt-by-name everywhere so a rerun never duplicates.
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import time
from typing import Any, Optional

import pipeline

KA_DISPLAY = "docflow-ka"
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


def _section(name: str, seconds: float) -> None:
    with _glock:
        GO["sections"][name] = round(seconds, 1)


def snapshot() -> dict:
    with _glock:
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
        _log("Catalog", "ok", f"created {cat}")
    if not exists(f"SHOW SCHEMAS IN {cat} LIKE '{sch}'"):
        pipeline.sql(f"CREATE SCHEMA IF NOT EXISTS {cat}.{sch}")
    if not exists(f"SHOW VOLUMES IN {cat}.{sch} LIKE 'docs'"):
        pipeline.sql(f"CREATE VOLUME IF NOT EXISTS {cat}.{sch}.docs")
    if not exists(f"SHOW VOLUMES IN {cat}.{sch} LIKE 'secure'"):
        pipeline.sql(f"CREATE VOLUME IF NOT EXISTS {cat}.{sch}.secure")
    for sub in ("inbox", "processed", "archive", "generated"):
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
    principals = ["account users", "users"]
    import appconfig
    owner = (cfg or {}).get("owner_email") or appconfig._installer()
    if owner:
        principals.insert(0, owner)          # the person who installed it
    granted, errs = [], []
    for who in principals:
        try:
            for g in (f"GRANT USE CATALOG ON CATALOG {cat} TO `{who}`",
                      f"GRANT USE SCHEMA ON SCHEMA {cat}.{sch} TO `{who}`",
                      f"GRANT SELECT ON SCHEMA {cat}.{sch} TO `{who}`",
                      f"GRANT READ VOLUME ON VOLUME {cat}.{sch}.docs TO `{who}`"):
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
                }, "required": ["site", "vendors", "line_items", "carriers",
                                "destinations", "type_labels", "contract"]},
            },
            "required": ["tagline", "vocabulary", "genie_questions",
                         "assistant_questions", "claims_page_title",
                         "suppliers_page_title", "world"],
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
        f"You are preparing a document-intelligence demo for {cfg['company']}, "
        f"a company in the {cfg['industry']} industry. {cfg.get('notes','')} "
        f"{schema_note} "
        "Produce: a one-line tagline for their demo, 6 industry vocabulary terms, "
        "3 questions an executive would ask about the TABLES above, "
        "3 questions they would ask about document WORDING, and a world object "
        "that the document generator renders directly. World rules: everything "
        "fictional but authentic to this industry. site: one facility name. "
        "vendors: 4 supplier company names. line_items: 8 short line-item "
        "descriptions in the industry's own language (these appear on invoices "
        "and purchase orders). carriers: 2 freight carriers. destinations: 2 "
        "delivery destinations. type_labels: a short display label in industry "
        "language for every document type key, keeping the meaning (the "
        "supplier_invoice label must still mean an invoice; warranty_claim can "
        "become e.g. a loss claim or off-spec batch claim if that is what the "
        "industry calls it). contract: supplier (one of your vendors), "
        "penalty_pct, cap_pct, warranty_months, filing_days as bare numbers in "
        "strings - these are printed verbatim inside a Master Supply Agreement "
        "CT-7701 and a Warranty Terms policy CT-7702, so at least one wording "
        "question MUST quote the exact number you chose (e.g. the late-delivery "
        "penalty or the claim filing deadline), giving it a citable answer. "
        "and titles for two operations screens. The titles must name the work this "
        "industry actually does, not generic labels: never return 'Claims "
        "Operations' or 'Supplier Operations'. For insurance prefer wording like "
        "'Loss Run Review'; for healthcare something like 'Prior Authorisation "
        "Desk'; for manufacturing something like 'Warranty Recovery Desk'."
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
                           "why": f"Company research did not run: {str(e)[:120]}"}
        _log("Company research", "warn",
             f"using generic wording · research failed: {str(e)[:90]}")
    _section("Research the company", time.time() - t0)


def build_corpus(cfg: dict) -> None:
    """Inventory customer volume, generate the standard pack into generated/."""
    t0 = time.time()
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
    with tempfile.TemporaryDirectory() as td:
        man = corpus.generate_corpus(cfg["company"], td, seed=38, world=world)
        for item in man["generated"]:
            with open(os.path.join(td, item["filename"]), "rb") as f:
                data = f.read()
            w.files.upload(f"{pipeline.VOL_ROOT}/generated/{item['filename']}",
                           io.BytesIO(data), overwrite=True)
            w.files.upload(f"{pipeline.VOL_ROOT}/inbox/{item['filename']}",
                           io.BytesIO(data), overwrite=True)
    GO["assets"]["documents"] = {"customer": customer_n, "generated": len(man["generated"]),
                                 "pack": "back office"}
    # Say what these documents are. They carry the customer's name but the
    # document types are the standard back-office pack, not industry specific.
    skin = "in this industry's own language" if world else "standard pack"
    _log("Generated documents", "ok",
         f"{len(man['generated'])} documents named for {cfg['company']}, {skin}, "
         f"watermarked, in their own volume folder")
    _section("Build the document set", time.time() - t0)


def ensure_ka() -> None:
    """Create or adopt the Knowledge Assistant; attach the volume source."""
    t0 = time.time()
    w = _w()
    ka = None
    try:
        # Inside the try: older SDK builds lack this module, and the assistant
        # is an enhancement, never a reason to stop the run.
        from databricks.sdk.service import knowledgeassistants as K
        for x in w.knowledge_assistants.list_knowledge_assistants():
            if (x.display_name or "") == KA_DISPLAY:
                ka = x
                break
        if ka is None:
            ka = w.knowledge_assistants.create_knowledge_assistant(K.KnowledgeAssistant(
                display_name=KA_DISPLAY,
                description="Answers questions about the demo document set with citations.",
                instructions="Answer questions about the supplied documents. "
                             "Cite the source document and page."))
            _log("Knowledge Assistant", "ok", f"created · endpoint {ka.endpoint_name}")
        else:
            _log("Knowledge Assistant", "ok", f"using existing · endpoint {ka.endpoint_name}")
        # The asset is recorded the moment it exists. A slow source attach
        # below must not cost the rest of the run its knowledge of the KA.
        GO["assets"]["ka"] = {"name": ka.name, "endpoint": ka.endpoint_name,
                              "display": KA_DISPLAY}
        have_source = False
        try:
            for src in w.knowledge_assistants.list_knowledge_sources(ka.name):
                path = ""
                try:
                    path = (src.files.path or "") if src.files else ""
                except Exception:
                    pass
                if path.startswith(pipeline.VOL_ROOT):
                    have_source = True
                elif path:
                    # A source pointing somewhere else means this assistant is
                    # left over from an earlier install. Say so and attach the
                    # current volume alongside rather than trusting stale files.
                    _log("Knowledge source", "warn",
                         f"existing source points at {path[:80]} · attaching the "
                         f"current volume as well")
        except Exception:
            pass
        if not have_source:
            # On a freshly created assistant this call can hang inside the
            # SDK's five-minute retry budget while the control plane finishes
            # provisioning. Indexing is background work by definition, so the
            # run caps its wait and moves on; a rerun adopts and re-attaches.
            outcome: list = []

            def _attach():
                try:
                    w.knowledge_assistants.create_knowledge_source(ka.name, K.KnowledgeSource(
                        display_name="demo-documents", description="Demo document volume",
                        source_type="files", files=K.FilesSpec(path=f"{pipeline.VOL_ROOT}/inbox")))
                    outcome.append("ok")
                except Exception as ex:
                    outcome.append(str(ex))
            th = threading.Thread(target=_attach, daemon=True)
            th.start()
            th.join(75)
            if th.is_alive() or (outcome and "timed out" in outcome[0].lower()):
                _log("Knowledge source", "ok",
                     "attaching in the background · the Ask page uses the "
                     "assistant the moment indexing finishes")
            elif outcome and outcome[0] == "ok":
                _log("Knowledge source", "ok", "volume attached · indexing in background")
            else:
                _log("Knowledge source", "warn",
                     f"not attached yet, a rerun retries it · {outcome[0][:120] if outcome else ''}")
    except Exception as e:
        _log("Knowledge Assistant", "warn", str(e)[:200])
    _section("Create the Knowledge Assistant", time.time() - t0)


def report_ka() -> None:
    """Close the run with the assistant's true state instead of a guess."""
    try:
        st = ka_state()
        if st.get("ready"):
            _log("Knowledge Assistant", "ok",
                 f"ready · {st.get('endpoint', '')} answers with citations")
        elif st.get("endpoint"):
            _log("Knowledge Assistant", "ok",
                 f"{st.get('endpoint')} still indexing · Ask falls back to "
                 f"governed SQL until it is ready, then switches on its own")
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
            research_company(cfg)
            build_corpus(cfg)
            ensure_ka()              # indexing continues in background
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
        with _glock:
            GO["phase"] = "error"
            GO["error"] = str(e)[:400]
            GO["finished"] = time.time()
        _log("Stopped", "err", str(e)[:200])


def start(cfg: dict, stage: str = "all") -> bool:
    with _glock:
        if GO["phase"] == "running":
            return False
        if stage == "process" and GO["phase"] not in ("prepared", "done", "error"):
            return False             # nothing staged yet: go prepares first
    threading.Thread(target=go, args=(cfg, stage), daemon=True).start()
    return True


# ---------------------------------------------------------------- ask
def ka_state() -> dict:
    w = _w()
    # An app identity may not see assistants it didn't create in list results,
    # A ka-* endpoint being Ready proves serving works, not that the assistant
    # can answer: an assistant with no attached source serves an endpoint that
    # errors with 'qgen requires at least one retrieval tool'. Ready therefore
    # requires a source whenever the assistant record is visible to us.
    ep = None
    try:
        for e in w.serving_endpoints.list():
            if e.name and e.name.startswith("ka-"):
                ep = e.name
                break
    except Exception:
        pass
    try:
        for x in w.knowledge_assistants.list_knowledge_assistants():
            if (x.display_name or "") == KA_DISPLAY:
                out = {"state": str(x.state).split(".")[-1] if x.state else "",
                       "endpoint": x.endpoint_name or ep, "name": x.name}
                try:
                    srcs = list(w.knowledge_assistants.list_knowledge_sources(x.name))
                    out["sources"] = [str(s.state).split(".")[-1] if s.state else ""
                                      for s in srcs]
                except Exception:
                    out["sources"] = []
                out["ready"] = bool(out.get("endpoint")) and bool(out["sources"])
                out["indexed"] = any(s in ("UPDATED", "READY", "ACTIVE", "ONLINE")
                                     for s in out["sources"])
                return out
    except Exception:
        pass
    if ep:
        # Endpoint visible but the assistant record is not (adopted from a
        # different owner). Optimistic, and ask() degrades honestly on error.
        return {"state": "ACTIVE", "endpoint": ep, "sources": [],
                "ready": True, "via": "endpoint"}
    return {"state": "absent", "ready": False}


def _attach_source_async() -> None:
    """One quiet attempt to give the assistant its volume, off-thread."""
    def _run():
        try:
            from databricks.sdk.service import knowledgeassistants as K
            w = _w()
            for x in w.knowledge_assistants.list_knowledge_assistants():
                if (x.display_name or "") == KA_DISPLAY:
                    try:
                        if list(w.knowledge_assistants.list_knowledge_sources(x.name)):
                            return
                    except Exception:
                        pass
                    w.knowledge_assistants.create_knowledge_source(x.name, K.KnowledgeSource(
                        display_name="demo-documents", description="Demo document volume",
                        source_type="files", files=K.FilesSpec(path=f"{pipeline.VOL_ROOT}/inbox")))
                    return
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


def ask_assistant(question: str) -> dict:
    st = ka_state()
    if not st.get("ready"):
        if st.get("endpoint") and not st.get("sources"):
            _attach_source_async()   # self-heal: the attach never landed
            msg = ("The assistant exists but is not connected to the documents yet. "
                   "Connecting it now — ask this exact question again in a few minutes.")
        else:
            msg = ("The Knowledge Assistant for this run is still being prepared. "
                   "Ask this one again in a few minutes.")
        return {"engine": "assistant", "pending": True, "state": st.get("state"),
                "sources": st.get("sources", []), "text": msg}
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
        if not text:
            text = json.dumps(raw)[:500]
        return {"engine": "assistant", "seconds": round(time.time() - t0, 1),
                "text": text, "endpoint": st["endpoint"]}
    except Exception as e:
        msg = str(e)
        if "retrieval tool" in msg or "KBQA" in msg:
            # The endpoint serves but the assistant has no source: attach one
            # quietly and answer like the pending case instead of erroring.
            _attach_source_async()
            return {"engine": "assistant", "pending": True,
                    "text": "The assistant is not connected to its documents yet. "
                            "Connecting it now — ask this exact question again in a "
                            "few minutes."}
        return {"engine": "assistant", "error": msg[:250], "endpoint": st.get("endpoint")}


def ask(question: str) -> dict:
    route = route_question(question)
    out = ask_genie(question) if route == "tables" else ask_assistant(question)
    out["route"] = route
    return out
