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
        foreign = pipeline.schema_foreign_objects(cat, sch)
        n_foreign = len(foreign["tables"]) + len(foreign["volumes"])
        if marked:
            GO["assets"]["schema_created_by_us"] = True
            _log("Schema", "ok", f"reusing {cat}.{sch}, created by this demo earlier")
        elif n_foreign == 0:
            pipeline.claim_schema(cat, sch)
            GO["assets"]["schema_created_by_us"] = True
            _log("Schema", "ok", f"adopted empty schema {cat}.{sch} and marked it")
        else:
            names = ", ".join((foreign["tables"] + foreign["volumes"])[:4])
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
                "ka_contracts", "ka_claims"):
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
                                "narratives"]},
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
        "narratives: prose the documents print verbatim, all in this industry's "
        "voice. component_names: 5 things this company buys or services that "
        "could fail. claim_failures: 5 failure descriptions, 20-40 words each, "
        "matching those components in order. claim_resolution: one line. "
        "inspection_method: one line naming an industry-plausible QA method. "
        "incident_areas/roles/narratives/actions: 2 each, minor workplace safety "
        "events at the site, 25-45 words per narrative. hr_from_title/to_title: "
        "a promotion between two real job titles here. hr_note: 15-25 words. "
        "marketing: a vendor's junk-mail headline, 25-40 word body, and 3 "
        "bullet lines separated by <br/>. contract_scope: one sentence of what "
        "the supplier delivers. "
        "story: a 5-beat presenter script, one beat per page in order "
        "documents, flow, ask, claims, suppliers. Each line is the business "
        "value on screen in at most 20 words, spoken language. Each cue is the "
        "single click to make next (name the exact question to click on the "
        "ask beat). The arc: documents exist, they route themselves, answers "
        "cite sources, money is recovered, suppliers are accountable. "
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
    folder_of = {t: spec["folder"] for spec in ASSISTANTS for t in spec["types"]}
    with tempfile.TemporaryDirectory() as td:
        man = corpus.generate_corpus(cfg["company"], td, seed=38, world=world)
        scoped = 0
        for item in man["generated"]:
            with open(os.path.join(td, item["filename"]), "rb") as f:
                data = f.read()
            w.files.upload(f"{pipeline.VOL_ROOT}/generated/{item['filename']}",
                           io.BytesIO(data), overwrite=True)
            w.files.upload(f"{pipeline.VOL_ROOT}/inbox/{item['filename']}",
                           io.BytesIO(data), overwrite=True)
            # A copy into the owning assistant's folder, so each assistant
            # indexes only its own documents instead of the whole inbox.
            fol = folder_of.get(item["type"])
            if fol:
                w.files.upload(f"{pipeline.VOL_ROOT}/{fol}/{item['filename']}",
                               io.BytesIO(data), overwrite=True)
                scoped += 1
    GO["assets"]["documents"] = {"customer": customer_n, "generated": len(man["generated"]),
                                 "pack": "back office"}
    # Say what these documents are. They carry the customer's name but the
    # document types are the standard back-office pack, not industry specific.
    skin = "in this industry's own language" if world else "standard pack"
    _log("Generated documents", "ok",
         f"{len(man['generated'])} documents named for {cfg['company']}, {skin}, "
         f"watermarked, in their own volume folder")
    _section("Build the document set", time.time() - t0)


_KA_THREAD: dict = {"thread": None, "created": {}}


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
            for spec in ASSISTANTS:
                try:
                    ka = existing.get(spec["display"])
                    if ka is None:
                        ka = w.knowledge_assistants.create_knowledge_assistant(
                            K.KnowledgeAssistant(
                                display_name=spec["display"],
                                description=f"Answers questions about {spec['about']} "
                                            f"with citations.",
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
                except Exception as e:
                    _log(f"Assistant · {spec['about']}", "warn", str(e)[:160])
        except Exception as e:
            _log("Assistants", "warn", str(e)[:160])
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
            folder = f"{pipeline.VOL_ROOT}/{spec['folder']}"
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
            research_company(cfg)
            build_corpus(cfg)
            attach_assistant_sources()  # scoped folders now exist
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
        return {"engine": "assistant", "pending": True,
                "states": [st for _, st in states],
                "text": (f"The assistants ({waiting or 'both'}) are still indexing "
                         f"their document folders. Ask this again in a few minutes "
                         f"— table questions answer right now.")}
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
        if not text:
            text = json.dumps(raw)[:500]
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
        return {"engine": "assistant", "error": msg[:250], "endpoint": st.get("endpoint")}


def ask(question: str) -> dict:
    route = route_question(question)
    out = ask_genie(question) if route == "tables" else ask_assistant(question)
    out["route"] = route
    return out
