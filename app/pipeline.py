"""DocFlow pipeline: real Databricks wiring.

Every stage runs actual platform capabilities (AI Functions over a serverless
warehouse, Files API on a UC volume). No simulated results: the frontend
replays what these functions record.
"""
from __future__ import annotations

import io
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem

CATALOG = os.environ.get("DOCFLOW_CATALOG", "workspace")
SCHEMA = os.environ.get("DOCFLOW_SCHEMA", "docflow")
VOLUME = os.environ.get("DOCFLOW_VOLUME", "docs")
WAREHOUSE_ID = os.environ.get("DOCFLOW_WAREHOUSE_ID", "")
CHAT_ENDPOINT = os.environ.get("DOCFLOW_CHAT_ENDPOINT", "databricks-claude-sonnet-4-6")
JUDGE_ENDPOINT = os.environ.get("DOCFLOW_JUDGE_ENDPOINT", "databricks-claude-haiku-4-5")

FQ = f"{CATALOG}.{SCHEMA}"
VOL_ROOT = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
SEC_ROOT = f"/Volumes/{CATALOG}/{SCHEMA}/secure"


def set_target(catalog: str, schema: str, volume: str = "docs") -> None:
    """Point the pipeline at a different catalog.schema at runtime (config-driven)."""
    global CATALOG, SCHEMA, VOLUME, FQ, VOL_ROOT, SEC_ROOT, ASK_TABLES, DDL
    CATALOG, SCHEMA, VOLUME = catalog, schema, volume
    FQ = f"{CATALOG}.{SCHEMA}"
    VOL_ROOT = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
    SEC_ROOT = f"/Volumes/{CATALOG}/{SCHEMA}/secure"
    ASK_TABLES = {f"{FQ}.{t}" for t in (
        "extract_warranty_claims", "extract_supplier_invoices",
        "audit_findings", "documents", "events")}
    DDL[:] = _ddl()

# route matrix: doc_type -> lanes (mirrors corpus.ROUTING / PLAN.md)
ROUTING = {
    "supplier_invoice": {"extract": True, "audit": False, "secure": False},
    "purchase_order": {"extract": True, "audit": False, "secure": False},
    "warranty_claim": {"extract": True, "audit": True, "secure": False},
    "quality_inspection": {"extract": True, "audit": True, "secure": False},
    "safety_incident": {"extract": True, "audit": False, "secure": True},
    "hr_document": {"extract": False, "audit": False, "secure": True},
    "shipping_manifest": {"extract": True, "audit": False, "secure": False},
    "marketing": {"extract": False, "audit": False, "secure": False},
    "supplier_contract": {"extract": False, "audit": False, "secure": False},
}
DOC_TYPES = list(ROUTING.keys())

# ---------------------------------------------------------------- ownership
# This app runs inside customer workspaces. Everything it may create is
# enumerated here, and teardown is only ever allowed to remove things on these
# lists. Anything else in the target schema belongs to the customer and is
# never written to, replaced, or deleted.
OWNED_TABLES = ("documents", "events", "extract_warranty_claims",
                "extract_supplier_invoices", "audit_findings",
                "parsed", "labeled", "run_metrics")
OWNED_VOLUMES = ("docs", "secure")
# Stamped onto the schema the app creates or adopts. Teardown refuses to touch
# a schema that does not carry it.
MARKER = "docflow-demo-app: created by the DocFlow demo, safe to remove"


def schema_marker(cat: str, sch: str) -> str:
    """The comment on a schema, empty when unreadable or unset."""
    try:
        rows = sql(f"DESCRIBE SCHEMA EXTENDED {cat}.{sch}")
    except Exception:
        return ""
    for r in rows or []:
        cells = [str(c) for c in r if c is not None]
        if any(c.strip().lower() in ("comment", "comment:") for c in cells):
            for c in cells:
                if MARKER.split(":")[0] in c:
                    return c
        for c in cells:
            if MARKER.split(":")[0] in c:
                return c
    return ""


def schema_foreign_objects(cat: str, sch: str) -> dict:
    """Objects in the schema this app did not create."""
    out = {"tables": [], "volumes": []}
    try:
        for r in sql(f"SHOW TABLES IN {cat}.{sch}") or []:
            name = str(r[1]) if len(r) > 1 else str(r[0])
            if name and name not in OWNED_TABLES:
                out["tables"].append(name)
    except Exception:
        pass
    try:
        for r in sql(f"SHOW VOLUMES IN {cat}.{sch}") or []:
            name = str(r[1]) if len(r) > 1 else str(r[0])
            if name and name not in OWNED_VOLUMES:
                out["volumes"].append(name)
    except Exception:
        pass
    return out


def claim_schema(cat: str, sch: str) -> None:
    """Stamp the schema so teardown can prove this app made it."""
    try:
        sql(f"COMMENT ON SCHEMA {cat}.{sch} IS '{MARKER}'")
    except Exception:
        pass

# research may rename every type into the industry's own language; the
# classifier then classifies against those labels while routing keys stay
# structural underneath
LABELS: dict[str, str] = {}


def set_labels(mapping: dict | None) -> None:
    LABELS.clear()
    for k, v in (mapping or {}).items():
        if k in ROUTING and str(v).strip():
            LABELS[k] = str(v).strip()[:48]


def label_of(t: str) -> str:
    return LABELS.get(t, t)

_w: Optional[WorkspaceClient] = None


def wc() -> WorkspaceClient:
    global _w
    if _w is None:
        _w = WorkspaceClient()
    return _w


# ------------------------------------------------------------- model resolve
# Workspaces disagree about model names. Enterprise workspaces expose
# databricks-* pay-per-token serving endpoints; Free Edition moved managed
# models into Unity AI Gateway, where the same families answer under
# different names and the classic endpoints 404. The app therefore never
# trusts a configured name: it probes candidates with a one-token ai_query
# and uses the first one that actually answers on this warehouse.
_MODEL = {"name": "", "note": "", "tried": 0}

# quality-ordered families; each is tried under every spelling a workspace
# might serve it as
_FAMILIES = (
    "claude-sonnet-4-6", "claude-haiku-4-5", "gpt-5-mini",
    "llama-4-maverick", "qwen35-122b-a10b", "gpt-oss-120b",
    "qwen3-next-80b-a3b-instruct", "meta-llama-3-3-70b-instruct",
    "gpt-oss-20b", "gemma-3-12b",
)


def model_candidates() -> list[str]:
    """Every model name this workspace might answer on, best first."""
    out: list[str] = []

    def push(n):
        n = (n or "").strip()
        if n and n not in out and re.fullmatch(r"[A-Za-z0-9._-]{1,120}", n):
            out.append(n)

    push(CHAT_ENDPOINT)                      # the configured choice always leads
    try:
        import appconfig
        push(appconfig.load_config().get("resolved_model"))   # last known good
    except Exception:
        pass
    try:                                     # enterprise path: real endpoints
        for e in wc().serving_endpoints.list():
            n = e.name or ""
            if n.startswith("databricks-") and not any(
                    k in n for k in ("embed", "gte-", "bge-", "image")):
                push(n)
    except Exception:
        pass
    # Gateway path: UC-registered models. These are the REAL names on Free
    # Edition, so they come before any blind spelling, quality-ranked by the
    # family list where possible.
    uc: list[str] = []
    try:
        for cat, sch in (("system", "ai"), ("workspace", "default")):
            for m in wc().registered_models.list(catalog_name=cat, schema_name=sch):
                if m.name and not any(k in m.name for k in ("embed", "gte", "bge")):
                    uc.append(f"{cat}.{sch}.{m.name}")
                    uc.append(m.name)
    except Exception:
        pass
    def rank(n):
        for i, fam in enumerate(_FAMILIES):
            if fam in n:
                return i
        return len(_FAMILIES)
    for n in sorted(uc, key=rank):
        push(n)
    for fam in _FAMILIES:                    # blind spellings, last resort
        push(f"databricks-{fam}")
        push(f"system.ai.{fam}")
        push(fam)
    return out


def models_available() -> list[str]:
    """Model names actually discovered in this workspace, quality-ranked.
    Feeds the Start page picker, so no blind spellings belong here."""
    out: list[str] = []

    def push(n):
        if n and n not in out:
            out.append(n)

    try:
        for e in wc().serving_endpoints.list():
            n = e.name or ""
            if n.startswith("databricks-") and not any(
                    k in n for k in ("embed", "gte-", "bge-", "image")):
                push(n)
    except Exception:
        pass
    try:
        for cat, sch in (("system", "ai"), ("workspace", "default")):
            for m in wc().registered_models.list(catalog_name=cat, schema_name=sch):
                if m.name and not any(k in m.name for k in ("embed", "gte", "bge")):
                    push(f"{cat}.{sch}.{m.name}")
    except Exception:
        pass

    def rank(n):
        for i, fam in enumerate(_FAMILIES):
            if fam in n:
                return i
        return len(_FAMILIES)
    return sorted(out, key=lambda n: (rank(n), n))[:30]


def chat_model() -> str:
    """The model every ai_query in the app calls. Resolved beats configured."""
    return _MODEL["name"] or CHAT_ENDPOINT


def resolve_chat_model(max_tries: int = 16) -> dict:
    """Probe candidates until one answers; remember it. Raises when none do."""
    cands = model_candidates()[:max_tries]
    errs: list[str] = []
    for name in cands:
        try:
            sql(f"SELECT ai_query('{name}', 'Reply with exactly: OK')", timeout="50s")
            _MODEL.update({"name": name, "tried": len(errs) + 1,
                           "note": "" if name == CHAT_ENDPOINT else
                           f"'{CHAT_ENDPOINT}' is not served here · using {name}"})
            try:
                import appconfig
                appconfig.save_config({"resolved_model": name})
            except Exception:
                pass
            return dict(_MODEL, model=name)
        except Exception as e:
            errs.append(f"{name}: {str(e)[:60]}")
    raise RuntimeError(
        f"No language model answered ai_query on this warehouse. Tried "
        f"{len(cands)}: {', '.join(c for c in cands[:6])}…  First error: "
        f"{errs[0] if errs else 'none'}")


def warehouse_id() -> str:
    global WAREHOUSE_ID
    if not WAREHOUSE_ID:
        cands = [w for w in wc().warehouses.list()
                 if getattr(w, "enable_serverless_compute", False) and w.id]
        if not cands:
            raise RuntimeError(
                "No serverless SQL warehouse is available to this app. Document "
                "Intelligence needs serverless compute, so a warehouse has to exist "
                "and the app must be allowed to use it.")
        cands.sort(key=lambda w: (getattr(w.state, "value", "") != "RUNNING", w.name or ""))
        WAREHOUSE_ID = cands[0].id
    return WAREHOUSE_ID


def sql(statement: str, timeout: str = "50s", params: Optional[dict] = None,
        row_limit: Optional[int] = None, deadline_s: int = 300) -> list[list[Any]]:
    """Execute one statement, return rows (polls past wait_timeout, follows chunks)."""
    r = wc().statement_execution.execute_statement(
        warehouse_id=warehouse_id(), statement=statement, wait_timeout=timeout,
        row_limit=row_limit,
        parameters=[StatementParameterListItem(name=k, value=str(v))
                    for k, v in (params or {}).items()] or None,
    )
    t0 = time.time()
    state = r.status.state.value if r.status and r.status.state else "UNKNOWN"
    while state in ("PENDING", "RUNNING"):
        if not r.statement_id:
            raise RuntimeError(f"no statement_id returned :: {statement[:120]}")
        if time.time() - t0 > deadline_s:
            try:
                wc().statement_execution.cancel_execution(r.statement_id)
            except Exception:
                pass
            raise RuntimeError(f"SQL exceeded {deadline_s}s :: {statement[:120]}")
        time.sleep(2)
        r = wc().statement_execution.get_statement(r.statement_id)
        state = r.status.state.value if r.status and r.status.state else "UNKNOWN"
    if state != "SUCCEEDED":
        err = r.status.error.message if r.status and r.status.error else state
        raise RuntimeError(f"SQL failed [{state}]: {err} :: {statement[:120]}")
    if not (r.result and r.result.data_array):
        return []
    rows, res = list(r.result.data_array), r.result
    while getattr(res, "next_chunk_index", None) is not None and len(rows) < 5000:
        res = wc().statement_execution.get_statement_result_chunk_n(
            r.statement_id, res.next_chunk_index)
        rows.extend(res.data_array or [])
    return rows


def q(s: str) -> str:
    """Escape for a Spark SQL string literal. Backslash FIRST (Spark honours \\ escapes)."""
    return s.replace("\\", "\\\\").replace("'", "''")


# ------------------------------------------------------------- SQL guard
ASK_TABLES = {f"{FQ}.{t}" for t in (
    "extract_warranty_claims", "extract_supplier_invoices",
    "audit_findings", "documents", "events")}
_BANNED_WORDS = {"insert", "update", "delete", "merge", "create", "drop", "alter",
                 "grant", "revoke", "truncate", "replace", "copy", "restore", "vacuum",
                 "optimize", "refresh", "set", "reset", "use", "call", "with", "values",
                 "load", "undrop", "analyze", "cache", "uncache", "msck", "comment",
                 "export", "declare", "execute"}
_BANNED_FUNCS = {"read_files", "cloud_files", "read_kafka", "read_kinesis",
                 "read_pubsub", "ai_query", "java_method", "reflect", "input_file_name"}


class BadSQL(Exception):
    pass


def _mask(s: str) -> str:
    """Blank comments and string literals so keywords can be scanned safely."""
    out, i, n = [], 0, len(s)
    while i < n:
        two, c = s[i:i + 2], s[i]
        if two == "--" or two == "/*":
            # Comments are never needed in generated SQL and only create
            # keyword-splitting ambiguity. Reject outright (outside literals).
            raise BadSQL("comments not allowed in generated SQL")
        elif c in "'\"":
            quote, i = c, i + 1
            while True:
                if i >= n:
                    raise BadSQL("unterminated string literal")
                if s[i] == "\\":
                    i += 2
                    continue
                if s[i] == quote:
                    if s[i + 1:i + 2] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append(" '' ")
        elif c == "`":
            raise BadSQL("backtick identifiers not allowed")
        else:
            out.append(c)
            i += 1
    return "".join(out)


def guard_select(gen: str) -> str:
    """Return the exact text to execute, or raise. Validated string == executed string."""
    if not gen or len(gen) > 4000:
        raise BadSQL("empty or oversized statement")
    safe = re.sub(r"\s*```\s*$", "", re.sub(r"^\s*```[A-Za-z]*\s*", "", gen.strip())).strip()
    masked = _mask(safe).strip()
    while masked.endswith(";"):
        masked = masked[:-1].rstrip()
        safe = safe.rstrip()[:-1].rstrip()
    if ";" in masked:
        raise BadSQL("multiple statements")
    if not masked.isascii():
        raise BadSQL("non-ascii outside string literals")
    depth = 0
    for ch in masked:
        depth += (ch == "(") - (ch == ")")
        if depth < 0:
            raise BadSQL("unbalanced parentheses")
    if depth:
        raise BadSQL("unbalanced parentheses")
    toks = re.findall(r"[A-Za-z_][A-Za-z0-9_.]*|[(),]", masked)
    if not toks or toks[0].lower() != "select" or not masked.lower().startswith("select"):
        raise BadSQL("not a single SELECT")
    for k, t in enumerate(toks):
        low = t.lower()
        if low in _BANNED_WORDS or low.split(".", 1)[0] in _BANNED_WORDS:
            raise BadSQL(f"disallowed keyword: {t}")
        if low in _BANNED_FUNCS or low.rsplit(".", 1)[-1] in _BANNED_FUNCS:
            raise BadSQL(f"disallowed function: {t}")
        if low.count(".") >= 2 and low not in ASK_TABLES:
            raise BadSQL(f"table not in allowlist: {t}")
        if low in ("from", "join"):
            nxt = toks[k + 1] if k + 1 < len(toks) else ""
            if nxt != "(" and nxt.lower() not in ASK_TABLES:
                raise BadSQL(f"table not in allowlist: {nxt or '<eof>'}")
    return safe


# ---------------------------------------------------------------- bootstrap
def _ddl() -> list:
    return [
        f"CREATE SCHEMA IF NOT EXISTS {FQ}",
        f"CREATE VOLUME IF NOT EXISTS {FQ}.{VOLUME}",
        f"""CREATE TABLE IF NOT EXISTS {FQ}.documents(
            doc_id STRING, filename STRING, doc_type STRING, confidence DOUBLE,
            route STRING, stage STRING, status STRING, pages INT,
            cost_usd DOUBLE, run_id INT, detail STRING, updated_at TIMESTAMP)""",
        f"""CREATE TABLE IF NOT EXISTS {FQ}.events(
            run_id INT, doc_id STRING, stage STRING, detail STRING, ts TIMESTAMP)""",
        f"""CREATE TABLE IF NOT EXISTS {FQ}.extract_warranty_claims(
            doc_id STRING, unit_serial STRING, purchase_date DATE, failure_date DATE,
            warranty_term_months INT, claim_amount DOUBLE, production_line STRING,
            claim_status STRING)""",
        f"""CREATE TABLE IF NOT EXISTS {FQ}.extract_supplier_invoices(
            doc_id STRING, vendor STRING, invoice_no STRING, total DOUBLE)""",
        f"""CREATE TABLE IF NOT EXISTS {FQ}.audit_findings(
            doc_id STRING, finding STRING, severity STRING, detail STRING,
            judge STRING)""",
    ]


DDL = _ddl()


def bootstrap() -> dict:
    out = {"statements": 0, "errors": []}
    for stmt in DDL:
        try:
            sql(stmt)
            out["statements"] += 1
        except Exception as e:  # keep going; report
            out["errors"].append(str(e)[:200])
    for sub in ("inbox", "processed", "archive"):
        try:
            wc().files.create_directory(f"{VOL_ROOT}/{sub}")
        except Exception:
            pass
    return out


def probe() -> dict:
    """Capability probe: ai functions + endpoints + tiers."""
    caps = {"warehouse": warehouse_id(), "volume": VOL_ROOT}
    try:
        r = sql("SELECT ai_classify('probe invoice text', ARRAY('invoice','other'))")
        caps["ai_functions"] = bool(r)
    except Exception as e:
        caps["ai_functions"] = False
        caps["ai_functions_error"] = str(e)[:200]
    eps = {"foundation": [], "custom": []}
    try:
        for e in wc().serving_endpoints.list():
            (eps["foundation"] if e.name.startswith("databricks-") else eps["custom"]).append(e.name)
    except Exception:
        pass
    caps["endpoints"] = {"foundation": len(eps["foundation"]), "custom": eps["custom"][:20]}
    caps["brick_detected"] = any("extract" in n.lower() or "labeler" in n.lower() for n in eps["custom"])
    return caps


# ---------------------------------------------------------------- run state
_lock = threading.Lock()
_pending: list = []


@dataclass
class RunState:
    run_id: int = 0
    phase: str = "idle"  # idle|ingest|parse|label|route|extract|audit|secure|done|error
    docs: dict = field(default_factory=dict)  # doc_id -> {...}
    log: list = field(default_factory=list)
    started: float = 0.0
    finished: float = 0.0
    error: str = ""
    money: dict = field(default_factory=lambda: {"caught_usd": 0.0, "cost_usd": 0.0})

    stage_times: dict = field(default_factory=dict)

    def stage_timings(self) -> list:
        with _lock:
            return [{"name": k, "seconds": round(v, 1)} for k, v in self.stage_times.items()]

    def snapshot(self) -> dict:
        with _lock:
            docs = {k: dict(v) for k, v in self.docs.items()}
            log = [dict(e) for e in self.log[-80:]]
            money = dict(self.money)
            phase, run_id, error = self.phase, self.run_id, self.error
            started, finished = self.started, self.finished
        return {
            "run_id": run_id, "phase": phase, "docs": docs,
            "log": log, "error": error, "money": money,
            "elapsed_s": round((finished or time.time()) - started, 1) if started else 0,
        }


STATE = RunState()


def try_start() -> bool:
    """Atomically claim the run slot (defeats double-click TOCTOU)."""
    with _lock:
        if STATE.phase not in ("idle", "done", "error"):
            return False
        STATE.phase = "starting"
        return True


def _ev(doc_id: str, stage: str, detail: str) -> None:
    with _lock:
        STATE.log.append({"t": round(time.time() - STATE.started, 1), "doc": doc_id, "stage": stage, "detail": detail})
        if doc_id in STATE.docs:
            STATE.docs[doc_id]["stage"] = stage
            STATE.docs[doc_id]["detail"] = detail
        _pending.append((STATE.run_id, doc_id, stage, detail[:250]))


def _flush_events() -> None:
    """One batched INSERT per stage instead of one per event."""
    with _lock:
        batch, _pending[:] = list(_pending), []
    if not batch:
        return
    vals = ",".join(f"({rid}, '{q(d)}', '{q(s)}', '{q(t)}', current_timestamp())"
                    for rid, d, s, t in batch)
    try:
        sql(f"INSERT INTO {FQ}.events VALUES {vals}")
    except Exception:
        pass  # best-effort; in-memory state is the live source


# ---------------------------------------------------------------- stages
def stage_ingest() -> list[str]:
    files = [
        f.name for f in wc().files.list_directory_contents(f"{VOL_ROOT}/inbox")
        if f.name and f.name.lower().endswith(".pdf")
    ]
    with _lock:
        for name in files:
            doc_id = name.rsplit(".", 1)[0]
            STATE.docs[doc_id] = {"doc_id": doc_id, "filename": name, "stage": "inbox",
                                  "doc_type": None, "confidence": None, "route": [], "detail": ""}
    return files


def stage_parse() -> None:
    """ai_parse_document over the whole inbox in one batch statement."""
    sql(f"""CREATE OR REPLACE TABLE {FQ}.parsed AS
        SELECT regexp_extract(path, '([^/]+)\\\\.pdf$', 1) AS doc_id,
               path,
               ai_parse_document(content) AS doc
        FROM READ_FILES('{VOL_ROOT}/inbox/', format => 'binaryFile')""", timeout="50s")
    rows = sql(f"SELECT doc_id, substr(to_json(doc), 1, 60) FROM {FQ}.parsed")
    for doc_id, _ in rows:
        _ev(doc_id, "parsed", "layout + text recovered (ai_parse_document)")


ROUTING_SCHEMA = json.dumps({
    "type": "json_schema",
    "json_schema": {
        "name": "routing",
        "schema": {
            "type": "object",
            "properties": {
                "doc_type": {"type": "string", "enum": DOC_TYPES},
                "confidence": {"type": "number"},
                "sensitivity": {"type": "string",
                                "enum": ["public", "internal", "confidential", "restricted"]},
                "needs_extraction": {"type": "boolean"},
                "needs_qa": {"type": "boolean"},
                "retention_class": {"type": "string"},
                "why": {"type": "string"},
            },
            "required": ["doc_type", "confidence", "sensitivity", "needs_extraction",
                         "needs_qa", "retention_class", "why"],
        },
        "strict": True,
    },
})

# capability lane assignment from the routing record (owner's model):
#   needs_extraction & needs_qa -> "ie_ka"  (same doc, both engines)
#   needs_extraction only       -> "ie"
#   needs_qa only               -> "ka"
#   neither, sensitive          -> "secure"
#   neither, not sensitive      -> "archive"
# Deterministic routing POLICY by document type. The agent reads and recommends;
# policy decides. Certification found the model's needs_qa/sensitivity judgments vary
# run to run on identical input, so a lane narrated on stage could contradict itself.
# Policy is stable and auditable; the agent's recommendation is still shown, and any
# disagreement is surfaced rather than hidden.
LANE_POLICY = {
    "supplier_invoice": "ie",
    "purchase_order": "ie",
    "shipping_manifest": "ie",
    "warranty_claim": "ie_ka",
    "quality_inspection": "ie_ka",
    "safety_incident": "secure",
    "hr_document": "secure",
    "marketing": "archive",
    "supplier_contract": "ka",
}


def lane_from_record(rec: dict) -> str:
    """What the agent's own recommendation implies (may differ from policy)."""
    ext, qa = bool(rec.get("needs_extraction")), bool(rec.get("needs_qa"))
    sensitive = (rec.get("sensitivity") or "").lower() in ("confidential", "restricted")
    if sensitive and not (ext or qa):
        return "secure"
    if ext and qa:
        return "ie_ka"
    if ext:
        return "ie"
    if qa:
        return "ka"
    return "archive"


def lane_for(rec: dict) -> str:
    """Policy decides the lane; the agent's read is advisory."""
    return LANE_POLICY.get(rec.get("doc_type") or "", lane_from_record(rec))


def stage_label() -> None:
    """Text classification in SQL, then the agent's advisory read of it.

    ai_classify IS the Text Classification capability — the same function the
    Agent Bricks tile wraps — so the document type comes from it directly and
    no agent has to be built by hand. The structured ai_query beside it is
    advisory only: it explains the routing in a sentence and gives its own
    opinion on extraction and Q&A, which the deterministic policy then either
    confirms or overrules on screen.
    """
    display = {t: label_of(t) for t in DOC_TYPES}
    types = ", ".join("'" + display[t].replace("'", "''") + "'" for t in DOC_TYPES)
    back = {v: k for k, v in display.items()}
    sql(f"""CREATE OR REPLACE TABLE {FQ}.labeled AS
        SELECT doc_id,
               ai_classify(substr(to_json(doc), 1, 3000), ARRAY({types})) AS doc_type,
               ai_query('{chat_model()}',
                 concat('This document has already been classified. Decide how it ',
                        'should be routed and explain the decision. ',
                        'Set needs_extraction true when the document has recurring fields ',
                        'worth putting in a table (invoices, purchase orders, claims, ',
                        'inspections, manifests). Set needs_qa true when a person would ask ',
                        'questions of its prose rather than its fields (contracts, policies, ',
                        'manuals, safety data sheets, reference material). Both can be true. ',
                        'Set both false for material needing only secure filing or no action. ',
                        'Explain the routing in one sentence in the why field. Text: ',
                        substr(to_json(doc), 1, 3000)),
                 responseFormat => '{ROUTING_SCHEMA.replace("'", "''")}') AS routing
        FROM {FQ}.parsed""", timeout="50s")
    for doc_id, doc_type, routing in sql(
            f"SELECT doc_id, doc_type, routing FROM {FQ}.labeled"):
        try:
            rec = json.loads(routing)
        except Exception:
            rec = {"confidence": 0.0, "sensitivity": "internal",
                   "needs_extraction": False, "needs_qa": False,
                   "retention_class": "unclassified", "why": "routing record unparseable"}
        # ai_classify decides the type; the model's own guess never overrides it.
        # It answered in the industry's label; routing runs on the structural key.
        rec["label"] = doc_type or ""
        rec["doc_type"] = back.get(doc_type, doc_type) or rec.get("doc_type") or "unknown"
        with _lock:
            if doc_id in STATE.docs:
                STATE.docs[doc_id].update({
                    "doc_type": rec.get("doc_type"),
                    "label": rec.get("label") or label_of(rec.get("doc_type") or ""),
                    "confidence": rec.get("confidence"),
                    "sensitivity": rec.get("sensitivity"),
                    "needs_extraction": rec.get("needs_extraction"),
                    "needs_qa": rec.get("needs_qa"),
                    "retention_class": rec.get("retention_class"),
                    "why": rec.get("why"),
                })
        _ev(doc_id, "labeled",
            f"{rec.get('label') or rec.get('doc_type')} · {rec.get('confidence')} · "
            f"{rec.get('sensitivity')}")


def stage_route() -> None:
    """Lane = which Agent Bricks capability handles it (IE / KA / IE+KA / secure)."""
    for doc_id, d in list(STATE.docs.items()):
        lane = lane_for(d)
        agent_lane = lane_from_record(d)
        with _lock:
            STATE.docs[doc_id]["lane"] = lane
            STATE.docs[doc_id]["agent_lane"] = agent_lane
            STATE.docs[doc_id]["policy_agrees"] = (lane == agent_lane)
            STATE.docs[doc_id]["route"] = {
                "ie": ["Information Extraction"],
                "ka": ["Knowledge Assistant"],
                "ie_ka": ["Information Extraction", "Knowledge Assistant"],
                "secure": ["Secure filing"],
                "archive": ["No action"],
            }[lane]
        _ev(doc_id, "routed", f"lane: {lane} · {d.get('why') or ''}"[:240])


def stage_extract() -> None:
    sql(f"""CREATE OR REPLACE TABLE {FQ}.extract_warranty_claims AS
        SELECT doc_id,
               x.unit_serial,
               try_cast(x.purchase_date AS DATE) AS purchase_date,
               try_cast(x.failure_date AS DATE) AS failure_date,
               try_cast(regexp_extract(x.warranty_term_months, '([0-9]+)', 1) AS INT) AS warranty_term_months,
               try_cast(regexp_replace(x.claim_amount, '[^0-9.]', '') AS DOUBLE) AS claim_amount,
               x.production_line,
               -- try_cast throughout: one malformed model response must never kill a
               -- live run, and a NULL date must never silently read as an expired claim.
               CASE
                 WHEN try_cast(x.purchase_date AS DATE) IS NULL
                   OR try_cast(x.failure_date AS DATE) IS NULL
                   OR try_cast(regexp_extract(x.warranty_term_months, '([0-9]+)', 1) AS INT) IS NULL
                   OR try_cast(regexp_replace(x.claim_amount, '[^0-9.]', '') AS DOUBLE) IS NULL
                   THEN 'needs review'
                 WHEN add_months(try_cast(x.purchase_date AS DATE),
                                 try_cast(regexp_extract(x.warranty_term_months, '([0-9]+)', 1) AS INT))
                      >= try_cast(x.failure_date AS DATE)
                   THEN 'within warranty'
                 ELSE 'outside window'
               END AS claim_status
        FROM (SELECT l.doc_id,
                     ai_extract(substr(to_json(p.doc),1,3500),
                       ARRAY('unit_serial','purchase_date','failure_date',
                             'warranty_term_months','claim_amount','production_line')) AS x
              FROM {FQ}.labeled l JOIN {FQ}.parsed p USING(doc_id)
              WHERE l.doc_type = 'warranty_claim')""", timeout="50s")
    # Labels ARE the prompt for ai_extract. The bare label 'vendor' reads the
    # "Bill to" party off these invoices (the buyer, not the issuer), so the
    # label is spelled out to pin the issuing company.
    sql(f"""CREATE OR REPLACE TABLE {FQ}.extract_supplier_invoices AS
        SELECT doc_id,
               x.vendor_company_that_issued_this_invoice AS vendor,
               x.invoice_number AS invoice_no,
               x.unit_serials,
               try_cast(regexp_replace(x.invoice_total_amount_due, '[^0-9.]', '') AS DOUBLE) AS total
        FROM (SELECT l.doc_id,
                     ai_extract(substr(to_json(p.doc),1,3500),
                       ARRAY('vendor_company_that_issued_this_invoice',
                             'invoice_number','invoice_total_amount_due','unit_serials')) AS x
              FROM {FQ}.labeled l JOIN {FQ}.parsed p USING(doc_id)
              WHERE l.doc_type = 'supplier_invoice')""", timeout="50s")
    for doc_id, in sql(f"SELECT doc_id FROM {FQ}.extract_warranty_claims"):
        _ev(doc_id, "extracted", "ai_extract -> extract_warranty_claims")
    for doc_id, in sql(f"SELECT doc_id FROM {FQ}.extract_supplier_invoices"):
        _ev(doc_id, "extracted", "ai_extract -> extract_supplier_invoices")


def stage_audit() -> None:
    sql(f"DELETE FROM {FQ}.audit_findings")
    sql(f"""INSERT INTO {FQ}.audit_findings
        SELECT doc_id, 'Warranty window exceeded', 'HIGH',
               concat('coverage ended ', add_months(purchase_date, warranty_term_months),
                      ', failure reported ', failure_date, ', ',
                      datediff(failure_date, add_months(purchase_date, warranty_term_months)),
                      ' days past term'),
               'deterministic window math, no model involved'
        FROM {FQ}.extract_warranty_claims WHERE claim_status = 'outside window'""")
    # Extraction rows the model could not parse cleanly are surfaced, never hidden.
    sql(f"""INSERT INTO {FQ}.audit_findings
        SELECT doc_id, 'Incomplete extraction', 'MEDIUM',
               'one or more fields could not be read cleanly, routed for human review',
               'deterministic null check'
        FROM {FQ}.extract_warranty_claims WHERE claim_status = 'needs review'""")
    caught = sql(f"SELECT coalesce(sum(claim_amount),0) FROM {FQ}.extract_warranty_claims WHERE claim_status='outside window'")
    with _lock:
        STATE.money["caught_usd"] = float(caught[0][0]) if caught else 0.0
    for doc_id, finding, sev, detail, _ in sql(f"SELECT * FROM {FQ}.audit_findings"):
        _ev(doc_id, "audit", f"{finding} [{sev}] {detail}")


def stage_secure() -> None:
    rows = sql(f"""SELECT l.doc_id, ai_mask(substr(to_json(p.doc),1,3000), ARRAY('person','email','phone_number'))
                   FROM {FQ}.labeled l JOIN {FQ}.parsed p USING(doc_id)
                   WHERE l.doc_type IN ('hr_document','safety_incident')""", timeout="50s")
    for doc_id, redacted in rows:
        data = (redacted or "").encode()
        wc().files.upload(f"{SEC_ROOT}/{doc_id}.redacted.txt", io.BytesIO(data), overwrite=True)
        _ev(doc_id, "secured", "ai_mask redaction sealed to the secure volume")


def run_pipeline() -> None:
    with _lock:
        STATE.run_id += 1
        STATE.phase = "ingest"
        STATE.docs = {}
        STATE.log = []
        STATE.error = ""
        STATE.started = time.time()
        STATE.finished = 0.0
        STATE.money = {"caught_usd": 0.0, "cost_usd": 0.0}
    try:
        t_ing = time.time()
        n = len(stage_ingest())
        with _lock:
            STATE.stage_times["ingest"] = time.time() - t_ing
        if n == 0:
            with _lock:
                STATE.phase = "idle"
                STATE.error = "Inbox is empty. Generate documents first."
                STATE.finished = time.time()
            return
        for phase, fn in (("parse", stage_parse), ("label", stage_label),
                          ("route", stage_route), ("extract", stage_extract),
                          ("audit", stage_audit), ("secure", stage_secure)):
            with _lock:
                STATE.phase = phase
            t_stage = time.time()
            fn()
            with _lock:
                STATE.stage_times[phase] = time.time() - t_stage
            _flush_events()
        with _lock:
            # rough demo-grade cost model: parse pages + per-call task functions
            # Labelled an ESTIMATE everywhere it renders: per-page parse plus per-call
            # task functions. Authoritative billing lives in system.billing.usage
            # (billing_origin_product = AI_FUNCTIONS).
            STATE.money["cost_usd"] = round(n * 0.0009 + n * 3 * 0.0002, 4)
            STATE.money["cost_is_estimate"] = True
            STATE.money["cost_basis"] = (
                f"{n} documents: per-page parse plus three task-function calls each. "
                "Authoritative figures in system.billing.usage.")
            STATE.phase = "done"
            STATE.finished = time.time()
    except Exception as e:
        _flush_events()
        with _lock:
            STATE.phase = "error"
            STATE.error = str(e)[:500]
            STATE.finished = time.time()


# ---------------------------------------------------------------- ask (Genie-pattern)
SCHEMA_HINT = (
    "extract_warranty_claims(doc_id STRING, unit_serial STRING, purchase_date DATE, "
    "failure_date DATE, warranty_term_months INT, claim_amount DOUBLE, "
    "production_line STRING, claim_status STRING); "
    "extract_supplier_invoices(doc_id STRING, vendor STRING, invoice_no STRING, total DOUBLE); "
    "audit_findings(doc_id STRING, finding STRING, severity STRING, detail STRING, judge STRING)"
)


def ask_structured(question: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", chat_model()):
        return {"error": "invalid chat endpoint configured"}
    prompt = (
        f"You translate questions to Databricks SQL. Tables in schema {FQ}: {SCHEMA_HINT}. "
        f"Return ONLY one SELECT statement, fully qualified table names, no markdown, "
        f"no CTEs, no WITH clause. Question: {question}"
    )
    rows = sql(f"SELECT ai_query('{chat_model()}', :prompt)", timeout="50s",
               params={"prompt": prompt})
    gen = rows[0][0] if rows and rows[0] else ""
    try:
        safe = guard_select(gen)
    except BadSQL as e:
        return {"error": f"rejected generated SQL: {e}", "sql": (gen or "")[:500]}
    data = sql(safe, timeout="50s", row_limit=50)
    return {"sql": safe, "rows": data, "engine": f"ai_query({chat_model()}) + serverless warehouse"}
