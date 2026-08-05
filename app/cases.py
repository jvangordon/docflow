"""The recovery desk: findings become cases, decisions become rows.

This is the write-back half of the demo. The lakehouse side detects (audit
findings over the extracted tables), a model advises (diagnosis, next step,
escalation), and the presenter's decision is written to Lakebase — an
operational Postgres row landing next to the analytical story, live on stage.

The store is a Lakebase database instance the app creates and records for
teardown. Where Lakebase is not available (region, tier, permissions), the
same two tables live as Delta tables through the warehouse instead, and the
page says so — the demo degrades honestly rather than dying.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid

import pipeline

INSTANCE = "docflow-lakebase"      # may gain a numeric suffix if the platform
                                   # refuses to release a deleted name's slug
_LB = {"state": "unknown", "dns": "", "detail": "", "created_by_us": False}
_LOCK = threading.Lock()
_CONN: dict = {"conn": None, "born": 0.0}

CASES_DDL = """CREATE TABLE IF NOT EXISTS docflow_cases(
    case_id text PRIMARY KEY,
    doc_id text, kind text, title text, severity text,
    amount_usd numeric, detail text,
    status text DEFAULT 'open',
    advice text DEFAULT '',
    opened_at timestamptz DEFAULT now())"""
ACTIONS_DDL = """CREATE TABLE IF NOT EXISTS docflow_case_actions(
    id serial PRIMARY KEY,
    case_id text, action text, note text, actor text,
    taken_at timestamptz DEFAULT now())"""


# ------------------------------------------------------------------ lakebase
def ensure_instance() -> dict:
    """Create or adopt the app's database instance. Fast: Lakebase provisions
    in seconds, which is itself a talking point."""
    global INSTANCE
    w = pipeline.wc()
    try:
        base = INSTANCE.split("-v")[0]
        for i in w.database.list_database_instances():
            d = i.as_dict()
            nm = d.get("name") or ""
            # docflow-lakebase or docflow-lakebase-vN: both are this app's
            # naming scheme — adopt whichever exists so a restart never
            # creates a second instance beside its own suffixed one.
            if nm == INSTANCE or nm == base or (
                    nm.startswith(base + "-v") and nm[len(base) + 2:].isdigit()):
                INSTANCE = nm
                with _LOCK:
                    _LB.update(state=str(d.get("state") or ""),
                               dns=d.get("read_write_dns") or "")
                return dict(_LB)
        from databricks.sdk.service.database import DatabaseInstance

        def _create():
            w.database.create_database_instance(
                DatabaseInstance(name=INSTANCE, capacity="CU_1"))
        try:
            _create()
        except Exception as ce:
            low = str(ce).lower()
            if "exist" not in low and "slug" not in low:
                raise
            # The name is held by a soft-deleted husk (a UI delete without
            # purge). Finish that purge if the platform lets us; if the slug
            # still will not release (API-created, UI-deleted names have been
            # seen to wedge), take a suffixed name instead of losing the demo.
            recovered = False
            try:
                w.database.delete_database_instance(INSTANCE, purge=True)
                time.sleep(3)
                _create()
                recovered = True
            except Exception:
                pass
            if not recovered:
                base = INSTANCE.split("-v")[0]
                for i in range(2, 6):
                    try:
                        INSTANCE = f"{base}-v{i}"
                        _create()
                        recovered = True
                        break
                    except Exception as se:
                        if "exist" not in str(se).lower() and "slug" not in str(se).lower():
                            break
                if not recovered:
                    INSTANCE = base
                    with _LOCK:
                        _LB.update(state="unavailable", detail=(
                            f"the workspace will not release the name "
                            f"{INSTANCE} nor accept a suffixed one — decisions "
                            f"write to Delta tables instead, same story"))
                    return dict(_LB)
        with _LOCK:
            _LB["created_by_us"] = True
        for _ in range(60):                     # AVAILABLE arrives in seconds
            d = next((i.as_dict() for i in w.database.list_database_instances()
                      if i.as_dict().get("name") == INSTANCE), {})
            if d.get("state") == "AVAILABLE":
                with _LOCK:
                    _LB.update(state="AVAILABLE", dns=d.get("read_write_dns") or "")
                return dict(_LB)
            time.sleep(2)
        with _LOCK:
            _LB.update(state="PROVISIONING", detail="instance still starting")
    except Exception as e:
        with _LOCK:
            _LB.update(state="unavailable", detail=str(e)[:200])
    return dict(_LB)


def _pg():
    """One cached connection; credentials are OAuth tokens that age out, so a
    connection older than ~40 minutes is rebuilt rather than trusted."""
    with _LOCK:
        conn, born = _CONN["conn"], _CONN["born"]
    if conn is not None and time.time() - born < 2400:
        try:
            with conn.cursor() as c:
                c.execute("SELECT 1")
            return conn
        except Exception:
            # The instance died under us (deleted mid-session). Drop the
            # corpse and rebuild — or fail into the Delta path honestly.
            with _LOCK:
                _CONN.update(conn=None, born=0.0)
                _LB.update(state="unknown", dns="")
    import psycopg
    w = pipeline.wc()
    if not _LB.get("dns"):
        ensure_instance()
    if not _LB.get("dns"):
        raise RuntimeError(_LB.get("detail") or "Lakebase instance not available")
    cred = w.database.generate_database_credential(
        request_id=str(uuid.uuid4()), instance_names=[INSTANCE])
    me = w.current_user.me().user_name
    conn = psycopg.connect(host=_LB["dns"], dbname="databricks_postgres",
                           user=me, password=cred.token, sslmode="require",
                           connect_timeout=15, autocommit=True)
    with conn.cursor() as c:
        c.execute(CASES_DDL)
        c.execute(ACTIONS_DDL)
    with _LOCK:
        old = _CONN["conn"]
        _CONN.update(conn=conn, born=time.time())
    if old is not None:
        try:
            old.close()
        except Exception:
            pass
    return conn


def mode() -> str:
    """'lakebase' when Postgres answers, else 'delta' (warehouse fallback)."""
    try:
        _pg()
        return "lakebase"
    except Exception:
        return "delta"


# ---------------------------------------------------- store, either backend
def _delta_ensure() -> None:
    pipeline.sql(f"""CREATE TABLE IF NOT EXISTS {pipeline.FQ}.docflow_cases(
        case_id STRING, doc_id STRING, kind STRING, title STRING,
        severity STRING, amount_usd DOUBLE, detail STRING,
        status STRING, advice STRING, opened_at TIMESTAMP)""")
    pipeline.sql(f"""CREATE TABLE IF NOT EXISTS {pipeline.FQ}.docflow_case_actions(
        id STRING, case_id STRING, action STRING, note STRING,
        actor STRING, taken_at TIMESTAMP)""")


def _rows(q: str, args: tuple = ()) -> list:
    conn = _pg()
    with conn.cursor() as c:
        c.execute(q, args)
        if c.description is None:
            return []
        return [list(r) for r in c.fetchall()]


def seed_from_findings() -> dict:
    """Every audit finding opens (or refreshes) a case. Idempotent: the case id
    is the finding's own identity, so re-processing updates instead of piling."""
    finds = pipeline.sql(
        f"SELECT f.doc_id, f.finding, f.severity, f.detail, "
        f"coalesce(c.claim_amount, 0) "
        f"FROM {pipeline.FQ}.audit_findings f "
        f"LEFT JOIN {pipeline.FQ}.extract_warranty_claims c USING (doc_id)")
    n = 0
    use = mode()
    if use == "lakebase":
        try:
            for doc_id, finding, sev, detail, amount in finds:
                cid = re.sub(r"[^a-z0-9]+", "-",
                             f"{doc_id}-{finding}".lower()).strip("-")[:80]
                _rows("""INSERT INTO docflow_cases
                           (case_id, doc_id, kind, title, severity, amount_usd, detail)
                         VALUES (%s,%s,%s,%s,%s,%s,%s)
                         ON CONFLICT (case_id) DO UPDATE
                           SET severity=EXCLUDED.severity, detail=EXCLUDED.detail,
                               amount_usd=EXCLUDED.amount_usd""",
                      (cid, doc_id, finding, f"{finding} · {doc_id}", sev,
                       float(amount or 0), detail))
                n += 1
            return {"cases": n, "store": "lakebase"}
        except Exception:
            with _LOCK:
                _CONN.update(conn=None, born=0.0)
                _LB.update(state="unknown", dns="")
            use, n = "delta", 0
    for doc_id, finding, sev, detail, amount in finds:
        cid = re.sub(r"[^a-z0-9]+", "-",
                     f"{doc_id}-{finding}".lower()).strip("-")[:80]
        title = f"{finding} · {doc_id}"
        if True:
            _delta_ensure()
            pipeline.sql(
                f"DELETE FROM {pipeline.FQ}.docflow_cases WHERE case_id = :c",
                params={"c": cid})
            pipeline.sql(
                f"INSERT INTO {pipeline.FQ}.docflow_cases VALUES "
                f"(:c, :d, :k, :t, :s, :a, :de, 'open', '', current_timestamp())",
                params={"c": cid, "d": doc_id, "k": finding, "t": title,
                        "s": sev, "a": float(amount or 0), "de": detail})
        n += 1
    return {"cases": n, "store": use}


def list_cases() -> dict:
    use = mode()
    if use == "lakebase":
        try:
            cs = _rows("""SELECT case_id, doc_id, kind, title, severity, amount_usd,
                                 detail, status, advice, opened_at::text
                          FROM docflow_cases
                          ORDER BY CASE severity WHEN 'HIGH' THEN 0 ELSE 1 END,
                                   amount_usd DESC""")
            acts = _rows("""SELECT case_id, action, note, actor, taken_at::text
                            FROM docflow_case_actions ORDER BY id""")
        except Exception:
            with _LOCK:
                _CONN.update(conn=None, born=0.0)
                _LB.update(state="unknown", dns="")
            use = "delta"
    if use == "delta":
        _delta_ensure()
        cs = pipeline.sql(
            f"SELECT case_id, doc_id, kind, title, severity, amount_usd, detail, "
            f"status, advice, cast(opened_at AS STRING) FROM {pipeline.FQ}.docflow_cases "
            f"ORDER BY CASE severity WHEN 'HIGH' THEN 0 ELSE 1 END, amount_usd DESC")
        acts = pipeline.sql(
            f"SELECT case_id, action, note, actor, cast(taken_at AS STRING) "
            f"FROM {pipeline.FQ}.docflow_case_actions ORDER BY taken_at")
    keys = ["case_id", "doc_id", "kind", "title", "severity", "amount_usd",
            "detail", "status", "advice", "opened_at"]
    out = [dict(zip(keys, r)) for r in cs]
    for c in out:
        c["amount_usd"] = float(c["amount_usd"] or 0)
        c["trail"] = [{"action": a[1], "note": a[2], "actor": a[3], "at": a[4]}
                      for a in acts if a[0] == c["case_id"]]
        try:
            c["advice"] = json.loads(c["advice"]) if c["advice"] else None
        except Exception:
            c["advice"] = {"next_step": str(c["advice"])[:400]}
    return {"cases": out, "store": use, "instance": INSTANCE if use == "lakebase" else "",
            "detail": _LB.get("detail", "")}


ADVICE_SCHEMA = json.dumps({
    "type": "json_schema",
    "json_schema": {"name": "advice", "schema": {"type": "object", "properties": {
        "diagnosis": {"type": "string"},
        "next_step": {"type": "string"},
        "escalate_to": {"type": "string"},
        "urgency": {"type": "string", "enum": ["now", "this week", "routine"]},
        "draft_note": {"type": "string"},
    }, "required": ["diagnosis", "next_step", "escalate_to", "urgency", "draft_note"]},
        "strict": True}})


def advise(case_id: str, model: str = "") -> dict:
    """One model call turns a finding into a recommended move, stored on the case."""
    data = list_cases()
    case = next((c for c in data["cases"] if c["case_id"] == case_id), None)
    if case is None:
        raise ValueError("no such case")
    use_model = (model or "").strip() or pipeline.chat_model()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", use_model):
        raise ValueError("that model name is not valid")
    ctx = pipeline.sql(
        f"SELECT substr(to_json(doc), 1, 2200) FROM {pipeline.FQ}.parsed "
        f"WHERE doc_id = :d", params={"d": case["doc_id"]})
    excerpt = ctx[0][0] if ctx and ctx[0] else ""
    prompt = (
        "You advise a back-office recovery desk. One finding, one recommendation. "
        "Be concrete and grounded ONLY in the material below — name the amount, "
        "the dates, the party. escalate_to is a role (e.g. 'Supplier quality "
        "manager', 'AP lead'), not a person. draft_note is 1-2 sentences the "
        "operator can file as-is.\n\n"
        f"FINDING: {case['kind']} · severity {case['severity']} · "
        f"${case['amount_usd']:,.0f}\nDETAIL: {case['detail']}\n"
        f"DOCUMENT EXCERPT: {excerpt}")
    rows = pipeline.sql(
        f"SELECT ai_query('{use_model}', :p, responseFormat => '{ADVICE_SCHEMA}')",
        params={"p": prompt}, timeout="50s", deadline_s=180)
    raw = (rows[0][0] if rows and rows[0] else "") or "{}"
    try:
        advice = json.loads(raw)
    except Exception:
        advice = {"diagnosis": raw[:300], "next_step": "", "escalate_to": "",
                  "urgency": "routine", "draft_note": ""}
    advice["model"] = use_model
    if data["store"] == "lakebase":
        _rows("UPDATE docflow_cases SET advice=%s WHERE case_id=%s",
              (json.dumps(advice), case_id))
    else:
        pipeline.sql(f"UPDATE {pipeline.FQ}.docflow_cases SET advice = :a "
                     f"WHERE case_id = :c",
                     params={"a": json.dumps(advice), "c": case_id})
    return {"case_id": case_id, "advice": advice, "store": data["store"]}


STATUS_OF = {"approve": "recovery approved", "escalate": "escalated",
             "dismiss": "dismissed", "reopen": "open"}


def act(case_id: str, action: str, note: str = "", actor: str = "") -> dict:
    """The write-back: the presenter's decision lands as a row, on stage."""
    if action not in STATUS_OF:
        raise ValueError("action must be approve, escalate, dismiss or reopen")
    note = (note or "")[:500]
    actor = (actor or "the app")[:120]
    use = mode()
    if use == "lakebase":
        try:
            _rows("INSERT INTO docflow_case_actions(case_id, action, note, actor) "
                  "VALUES (%s,%s,%s,%s)", (case_id, action, note, actor))
            _rows("UPDATE docflow_cases SET status=%s WHERE case_id=%s",
                  (STATUS_OF[action], case_id))
            row = _rows("SELECT taken_at::text FROM docflow_case_actions "
                        "WHERE case_id=%s ORDER BY id DESC LIMIT 1", (case_id,))
        except Exception:
            # The instance vanished between the health check and the write.
            # The decision still lands — in Delta — rather than erroring out.
            with _LOCK:
                _CONN.update(conn=None, born=0.0)
                _LB.update(state="unknown", dns="")
            use = "delta"
    if use == "delta":
        _delta_ensure()
        pipeline.sql(
            f"INSERT INTO {pipeline.FQ}.docflow_case_actions VALUES "
            f"(uuid(), :c, :a, :n, :who, current_timestamp())",
            params={"c": case_id, "a": action, "n": note, "who": actor})
        pipeline.sql(f"UPDATE {pipeline.FQ}.docflow_cases SET status = :s "
                     f"WHERE case_id = :c",
                     params={"s": STATUS_OF[action], "c": case_id})
        row = pipeline.sql(
            f"SELECT cast(max(taken_at) AS STRING) FROM "
            f"{pipeline.FQ}.docflow_case_actions WHERE case_id = :c",
            params={"c": case_id})
    return {"case_id": case_id, "status": STATUS_OF[action],
            "written_at": (row[0][0] if row and row[0] else ""),
            "store": use, "instance": INSTANCE if use == "lakebase" else ""}
