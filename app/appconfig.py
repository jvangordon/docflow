"""DocFlow app configuration, theming, readiness and metrics.

Design note: config lives as a JSON file on the UC volume, not in a Delta table,
so reading and writing it works while the SQL warehouse is stopped. Only the
pipeline needs the warehouse.
"""
from __future__ import annotations

import io
import json
import re
import time
from typing import Any, Optional

import pipeline

CONFIG_PATH = f"{pipeline.VOL_ROOT}/config.json"

# Deterministic lane policy, mirrored from pipeline.LANE_POLICY so the config
# page can promise lane coverage before a run happens.
LANE_NAMES = {
    "ie": "Information Extraction",
    "ka": "Knowledge Assistant",
    "ie_ka": "Both engines on one document",
    "secure": "Secure filing only",
    "archive": "No action",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "company": "",
    "industry": "",
    "notes": "",
    "catalog": "workspace",
    "schema": "docflow",
    "customer_volume": "",
    "chat_endpoint": "databricks-claude-sonnet-4-6",
    "accent_hex": "#FF3621",
    "doc_plan": {
        "supplier_invoice": 6,
        "purchase_order": 3,
        "warranty_claim": 5,
        "quality_inspection": 4,
        "safety_incident": 2,
        "hr_document": 1,
        "shipping_manifest": 2,
        "marketing": 1,
    },
    "updated_at": None,
}

HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


# ------------------------------------------------------------------ config io
def _installer() -> str:
    """Who ran the installer, recorded into the app env at deploy time."""
    import os
    return os.environ.get("DOCFLOW_OWNER", "")


def load_config() -> dict:
    try:
        resp = pipeline.wc().files.download(CONFIG_PATH)
        raw = resp.contents.read()
        cfg = json.loads(raw)
        merged = dict(DEFAULT_CONFIG)
        merged.update({k: v for k, v in cfg.items() if v is not None})
        merged["doc_plan"] = {**DEFAULT_CONFIG["doc_plan"], **(cfg.get("doc_plan") or {})}
        return merged
    except Exception:
        return dict(DEFAULT_CONFIG)


def save_config(patch: dict) -> dict:
    cfg = load_config()
    for key in ("company", "industry", "notes", "catalog", "schema",
                "customer_volume", "chat_endpoint"):
        if key in patch and patch[key] is not None:
            cfg[key] = str(patch[key])[:200]
    hexv = patch.get("accent_hex")
    if hexv:
        if not HEX_RE.match(str(hexv)):
            raise ValueError("accent_hex must be a hex color such as #FF3621")
        cfg["accent_hex"] = str(hexv).upper()
    plan = patch.get("doc_plan")
    if isinstance(plan, dict):
        clean = {}
        for k, v in plan.items():
            if k in DEFAULT_CONFIG["doc_plan"]:
                try:
                    clean[k] = max(0, min(40, int(v)))
                except (TypeError, ValueError):
                    continue
        cfg["doc_plan"] = {**cfg["doc_plan"], **clean}
    cfg["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        pipeline.wc().files.upload(
            CONFIG_PATH, io.BytesIO(json.dumps(cfg, indent=2).encode()), overwrite=True)
    except Exception as e:
        cfg["save_warning"] = f"config held in memory only: {str(e)[:160]}"
    return cfg


def lane_coverage(doc_plan: dict) -> dict:
    """How many documents each capability lane will receive under policy."""
    out = {k: 0 for k in LANE_NAMES}
    for doc_type, count in (doc_plan or {}).items():
        lane = pipeline.LANE_POLICY.get(doc_type)
        if lane:
            out[lane] = out.get(lane, 0) + int(count or 0)
    empty = [k for k in ("ie", "ka", "ie_ka", "secure") if out.get(k, 0) == 0]
    return {
        "counts": out,
        "names": LANE_NAMES,
        "empty_demo_lanes": empty,
        # Two supplier contracts route to the assistant alone; a still-empty ka
        # lane now means the run has not processed yet, not a missing doc type.
        "known_gap": None,
        "total_docs": sum(int(v or 0) for v in (doc_plan or {}).values()),
    }


# ------------------------------------------------------------------ theming
def _clamp(n: int) -> int:
    return max(0, min(255, n))


def _rgb(hex_value: str) -> tuple[int, int, int]:
    h = hex_value.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _shift(hex_value: str, factor: float) -> str:
    r, g, b = _rgb(hex_value)
    return "#%02X%02X%02X" % (_clamp(int(r * factor)), _clamp(int(g * factor)), _clamp(int(b * factor)))


def theme_css(accent_hex: str) -> str:
    """Only the accent moves. Oat canvas, navy ink, and red's meaning stay fixed."""
    if not HEX_RE.match(accent_hex or ""):
        accent_hex = DEFAULT_CONFIG["accent_hex"]
    r, g, b = _rgb(accent_hex)
    return f""":root {{
  --lava: {accent_hex};
  --brand-red: {accent_hex};
  --stamp-red: {_shift(accent_hex, 0.88)};
  --money: {accent_hex};
  --accent-soft: rgba({r},{g},{b},0.10);
  --accent-edge: rgba({r},{g},{b},0.42);
  --glow-red: 0 4px 14px rgba({r},{g},{b},0.28);
}}
/* CTA stays ink: a button is chrome, and accent on oat can fail contrast. */
"""


def warehouse_is_running() -> bool:
    """True only if a serverless warehouse is already awake. Never starts one."""
    try:
        for w in pipeline.wc().warehouses.list():
            if getattr(w, "enable_serverless_compute", False) and w.id:
                if getattr(w.state, "value", str(w.state)) == "RUNNING":
                    return True
        return False
    except Exception:
        return False


# ------------------------------------------------------------------ readiness
# Checks that must pass before a run can start. The rest are enhancements.
REQUIRED = ("identity", "warehouse", "catalog", "volume", "endpoints", "ai_functions")


def _host() -> str:
    try:
        return (pipeline.wc().config.host or "").rstrip("/")
    except Exception:
        return ""


def _clean(msg: str, limit: int = 180) -> str:
    """Platform errors carry host names, account ids and request ids. Keep the
    sentence a person needs and drop the identifiers."""
    msg = re.sub(r"\s*(Config:|RequestId=|ErrorClass=)[^\n]*", "", str(msg))
    msg = re.sub(r"https?://\S+", "", msg)
    msg = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "", msg)
    msg = re.sub(r"\s{2,}", " ", msg).strip(" .,")
    return (msg[:limit] + ("." if msg and not msg.endswith(".") else "")) if msg else "Unknown error."


def readiness(deep: bool = False) -> dict:
    """Verify every prerequisite. Each check is isolated so one failure never
    hides the others, and nothing is asserted that was not actually tested.

    deep=True additionally runs the checks that need SQL. Those start a
    warehouse, so they only run when explicitly requested.
    """
    checks: list[dict] = []
    host = _host()
    cfg = load_config()
    cat, sch = cfg.get("catalog") or "workspace", cfg.get("schema") or "docflow"

    def add(key, label, ok, detail, fix=None, fix_label=None, human=None,
            link=None, link_label=None, steps=None, untested=False, optional=False,
            depends_on=None, auto=False):
        checks.append({"key": key, "label": label, "ok": bool(ok), "detail": detail,
                       "fixable_by_app": bool(fix), "fix_endpoint": fix,
                       "fix_label": fix_label, "human_action": human,
                       "link": link, "link_label": link_label, "steps": steps or [],
                       "untested": untested, "depends_on": depends_on, "auto": auto,
                       "optional": optional or key not in REQUIRED})

    w = None
    # ---- 1. identity
    try:
        w = pipeline.wc()
        me = w.current_user.me()
        who = getattr(me, "user_name", None) or getattr(me, "display_name", "")
        add("identity", "App identity resolves", True, f"running as {who}")
    except Exception as e:
        add("identity", "App identity resolves", False, str(e)[:180],
            human="The app cannot authenticate to this workspace.",
            steps=["Confirm the app is started in the workspace",
                   "Redeploy so a fresh service principal token is issued"])

    # ---- 2. serverless warehouse
    wh_state = None
    try:
        cands = [x for x in w.warehouses.list()
                 if getattr(x, "enable_serverless_compute", False) and x.id]
        if cands:
            best = next((x for x in cands
                         if getattr(x.state, "value", str(x.state)) == "RUNNING"), cands[0])
            wh_state = getattr(best.state, "value", str(best.state))
            add("warehouse", "Serverless SQL warehouse", True,
                f"{best.name} · {wh_state}. Document Intelligence needs serverless, not Pro or Classic.")
        else:
            add("warehouse", "Serverless SQL warehouse", False,
                "No serverless warehouse is visible to this app.",
                fix="/api/fix/warehouse", fix_label="Create one",
                link=f"{host}/sql/warehouses", link_label="Open SQL Warehouses",
                human="The button creates a 2X-Small that stops itself after 10 idle "
                      "minutes. It needs the app's identity to hold the 'Allow cluster "
                      "creation' entitlement; if it does not, use the steps below.",
                steps=[
                    "Settings, Identity and access, Service principals",
                    "Open this app's service principal and tick 'Allow cluster creation'",
                    "Or create a serverless warehouse yourself and grant the app CAN USE",
                    "Re-check here",
                ])
    except Exception as e:
        add("warehouse", "Serverless SQL warehouse", False, str(e)[:180],
            link=f"{host}/sql/warehouses", link_label="Open SQL Warehouses",
            human="The app identity cannot list warehouses.",
            steps=["Open SQL Warehouses", "Grant the app service principal CAN USE on a serverless warehouse"])

    # ---- 3. target catalog exists and is writable by this identity
    #      This is the check that matters most: a run dies here, not earlier.
    try:
        cats = [c.name for c in w.catalogs.list()]
        if cat not in cats:
            # Creating a catalog needs CREATE CATALOG on the metastore, which an
            # app identity does not get in a fresh workspace. Offer the button
            # (it works where the right exists) but lead with the two things
            # that always work, so nobody hunts for a privilege they cannot grant.
            add("catalog", f"Catalog {cat}", False,
                f"'{cat}' does not exist here, and creating a catalog needs a "
                f"metastore privilege this app's identity will not have.",
                fix="/api/fix/catalog", fix_label="Try anyway",
                link=f"{host}/explore/data", link_label="Open Catalog Explorer",
                human="Two things that always work:",
                steps=[
                    f"Pick a catalog you already have under Advanced on the left — "
                    f"any catalog you can create a schema in works.",
                    f"Or create '{cat}' yourself in Catalog Explorer, then re-run "
                    f"setup_databricks.py so the app is granted rights on it.",
                ])
        else:
            try:
                schemas = [s.name for s in w.schemas.list(catalog_name=cat)]
                if sch in schemas:
                    add("catalog", f"Catalog {cat}.{sch}", True,
                        f"schema exists and is visible to this identity")
                else:
                    add("catalog", f"Catalog {cat}.{sch}", False,
                        f"catalog '{cat}' is visible but schema '{sch}' does not exist yet.",
                        fix="/api/fix/catalog", fix_label="Create schema",
                        human="Needs CREATE SCHEMA on the catalog.")
            except Exception as e:
                add("catalog", f"Catalog {cat}.{sch}", False,
                    f"cannot list schemas in '{cat}': {str(e)[:110]}",
                    fix="/api/fix/catalog", fix_label="Try to create",
                    link=f"{host}/explore/data/{cat}", link_label="Open catalog",
                    human="Grant the app identity USE CATALOG and CREATE SCHEMA.",
                    steps=[f"Open the {cat} catalog, Permissions tab",
                           "Grant the app service principal USE CATALOG and CREATE SCHEMA",
                           "Re-check here"])
    except Exception as e:
        add("catalog", f"Catalog {cat}.{sch}", False, str(e)[:180],
            link=f"{host}/explore/data", link_label="Open Catalog",
            human="The app identity cannot list catalogs.")

    # ---- 4. document volume
    try:
        w.files.get_directory_metadata(f"{pipeline.VOL_ROOT}/inbox")
        add("volume", "Document volume writable", True, f"{pipeline.VOL_ROOT}/inbox is reachable")
    except Exception as e:
        add("volume", "Document volume writable", False, str(e)[:150],
            fix="/api/bootstrap", fix_label="Create volume",
            link=f"{host}/explore/data/{cat}/{sch}", link_label="Open schema",
            human="Or grant READ VOLUME and WRITE VOLUME on the target volume.")

    # ---- 5/6/7. serving endpoints, assistant, extraction agent (each isolated)
    # The old form of this check listed databricks-* endpoints and called that
    # proof. Free Edition proved it wrong: its models answer under AI Gateway
    # names while the classic endpoints 404. The only honest test is asking a
    # model to answer, which needs the warehouse, so cold workspaces see it as
    # a waiting check rather than a false pass.
    names: list[str] = []
    try:
        names = [e.name for e in w.serving_endpoints.list()]
    except Exception:
        pass
    if pipeline._MODEL["name"]:
        add("endpoints", "Language model answers", True,
            f"ai_query answers on {pipeline._MODEL['name']}"
            + (f" · {pipeline._MODEL['note']}" if pipeline._MODEL["note"] else ""))
    elif deep:
        try:
            r = pipeline.resolve_chat_model()
            add("endpoints", "Language model answers", True,
                r["note"] or f"ai_query answers on {r['model']}")
        except Exception as e:
            add("endpoints", "Language model answers", False, _clean(str(e)),
                fix="/api/fix/models", fix_label="Find a working model",
                link=f"{host}/ml/ai-gateway", link_label="Open AI Gateway",
                human="No model answered a probe. Add a model in AI Gateway, or "
                      "set one this workspace serves under Advanced on the left.")
    elif wh_state == "RUNNING":
        add("endpoints", "Language model answers", False,
            "Not tested yet this session. Go tests it in its first seconds, "
            "or test now.",
            fix="/api/fix/models", fix_label="Test now",
            untested=True)
    else:
        add("endpoints", "Language model answers", False,
            "Tested the moment a warehouse is up; go does it in its first "
            "seconds either way.",
            human="Runs with the warehouse check above.",
            untested=True, depends_on="warehouse")

    custom = [n for n in names if not n.startswith("databricks-")]
    ka = [n for n in custom if n.startswith("ka-") or "knowledge" in n.lower()]
    add("knowledge_assistant", "Knowledge Assistant · built at go", bool(ka),
        f"detected: {ka[0]}" if ka else
        "POST /api/2.1/knowledge-assistants. The run creates it and attaches "
        "the document volume, even where the Agents UI offers no tile for it.",
        auto=True)

    # Classification and extraction are SQL, not agents to build. ai_classify
    # and ai_extract are the same functions the Agent Bricks tiles wrap, so
    # these rows report the capability, not a chore.
    add("classification", "Text classification · ai_classify in SQL", True,
        "The run classifies every document with ai_classify over the warehouse. "
        "Nothing to build, nothing to click.",
        auto=True)

    add("extraction", "Information extraction · ai_extract in SQL", True,
        "The run extracts typed fields with ai_extract over the warehouse. A "
        "managed Information Extraction agent is adopted if one exists, but the "
        "demo never needs one.",
        auto=True)

    # ---- browse access: the app SP owns the schema, so people are locked out
    #      by default. Tested for real, because a presenter finds out mid-demo.
    if deep or wh_state == "RUNNING":
        try:
            rows = pipeline.sql(f"SHOW GRANTS ON SCHEMA {cat}.{sch}")
            who = {str(r[0]) for r in rows if r and r[0]}
            human = [p for p in who if "@" in p or "users" in p.lower()]
            add("browse", "People can open the documents", bool(human),
                f"granted to {', '.join(sorted(human)[:3])}" if human else
                "Only the app's identity can open this schema, so nobody in the "
                "room can browse the documents it generates.",
                fix=None if human else "/api/fix/grants",
                fix_label=None if human else "Grant browse access",
                human=None if human else
                    f"Or run as yourself: GRANT USE SCHEMA, SELECT ON SCHEMA "
                    f"{cat}.{sch} TO `<you>`",
                optional=True)
        except Exception:
            add("browse", "People can open the documents", False,
                "Could not read the grants on this schema yet.",
                fix="/api/fix/grants", fix_label="Grant browse access",
                untested=True, optional=True)
    else:
        add("browse", "People can open the documents", False,
            "Checked once a warehouse is up; go grants it during the run.",
            untested=True, depends_on="warehouse", optional=True)

    # ---- 8. AI Functions actually execute (needs compute)
    if deep or wh_state == "RUNNING":
        try:
            pipeline.sql("SELECT ai_classify('probe invoice', ARRAY('invoice','other'))")
            add("ai_functions", "Document Intelligence functions run", True,
                "ai_classify returned a result on this warehouse")
        except Exception as e:
            add("ai_functions", "Document Intelligence functions run", False, str(e)[:180],
                human="These functions need serverless compute in a supported region.",
                steps=["Confirm the warehouse is serverless, not Pro or Classic",
                       "Confirm the workspace region supports AI Functions"])
    elif wh_state is None:
        # Nothing to start: say so and point at the check that must come first,
        # rather than offering a button that cannot succeed.
        add("ai_functions", "Document Intelligence functions run", False,
            "Waiting on a serverless warehouse. This check runs SQL, so it needs "
            "compute before it can be tested.",
            human="Create the warehouse above first, then test.",
            untested=True, depends_on="warehouse")
    else:
        add("ai_functions", "Document Intelligence functions run", False,
            f"Not tested yet. The warehouse is {wh_state} and this check runs SQL.",
            fix="/api/fix/probe", fix_label="Start and test",
            human="Starting a warehouse uses compute, so this is never automatic.",
            untested=True)

    # ---- 9. billed usage (actually inspected, not assumed)
    try:
        ms = w.metastores.current()
        states = {s.schema: str(getattr(s.state, "value", s.state))
                  for s in w.system_schemas.list(ms.metastore_id)}
        bstate = states.get("billing", "ABSENT")
        enabled = bstate in ("ENABLE_COMPLETED", "ENABLE_INITIALIZED")
        queryable = None
        if deep:
            try:
                pipeline.sql("SELECT 1 FROM system.billing.usage LIMIT 1")
                queryable = True
            except Exception:
                queryable = False
        if bstate == "MANAGED":
            # Databricks owns this schema here; no button can change it, so do
            # not offer one. The only honest signal is whether it queries.
            add("billing_schema", "Billed usage available", bool(queryable),
                "Databricks manages system.billing for this workspace, so it cannot be "
                "switched on from here. " + (
                    "The usage table answers, so real cost is available."
                    if queryable else
                    "Cost is shown as an estimate, which never blocks a demo."
                    if queryable is False else
                    "Not tested yet, because reading it runs SQL."),
                fix=None if queryable is not None else "/api/fix/probe",
                fix_label=None if queryable is not None else "Test",
                untested=queryable is None)
        else:
            add("billing_schema", "Billed usage available", enabled and queryable is not False,
                f"system.billing is {bstate}." + ("" if enabled else
                " Cost is shown as an estimate until this is enabled."),
                fix=None if enabled else "/api/fix/billing",
                fix_label=None if enabled else "Enable",
                human=None if enabled else
                "Needs account admin rights. The button asks, and reports what the platform answers.",
                steps=[] if enabled else [
                    "Account console, Settings, System schemas",
                    "Enable 'billing' for this metastore",
                    "Re-check here",
                ])
    except Exception as e:
        add("billing_schema", "Billed usage available", False,
            f"Could not read the system schema state. {_clean(str(e), 110)}",
            human="Cost stays an estimate, which never blocks a demo.")

    required = [c for c in checks if c["key"] in REQUIRED]
    blockers = [c["label"] for c in required if not c["ok"] and not c.get("untested")]
    unverified = [c["label"] for c in required if not c["ok"] and c.get("untested")]
    return {
        "ready_to_configure": not blockers,
        "ready_to_run": not blockers and wh_state == "RUNNING",
        "blockers": blockers,
        "unverified": unverified,
        "required_total": len(required),
        "required_ok": len([c for c in required if c["ok"]]),
        "warehouse_state": wh_state,
        "checks": checks,
        "note": ("Readiness never starts compute on its own. Anything that would begin "
                 "billing is offered as an explicit action."),
    }


def create_serverless_warehouse(name: str = "DocFlow Serverless") -> dict:
    """Create a small serverless warehouse. Explicit user action only."""
    from databricks.sdk.service.sql import CreateWarehouseRequestWarehouseType
    w = pipeline.wc().warehouses.create(
        name=name, cluster_size="2X-Small", max_num_clusters=1,
        auto_stop_mins=10, enable_serverless_compute=True,
        warehouse_type=CreateWarehouseRequestWarehouseType.PRO,
    ).result()
    return {"created": True, "warehouse_id": w.id, "name": name,
            "auto_stop_mins": 10, "note": "Auto stops after 10 idle minutes."}


def fix_catalog() -> dict:
    """Create the target catalog and schema. SQL path: on Default Storage
    workspaces the catalogs API refuses, but CREATE CATALOG succeeds."""
    cfg = load_config()
    cat, sch = cfg.get("catalog") or "workspace", cfg.get("schema") or "docflow"
    made = []
    try:
        pipeline.sql(f"CREATE CATALOG IF NOT EXISTS {cat}")
        made.append(f"catalog {cat}")
    except Exception as e:
        return {"ok": False, "stage": "catalog", "error": str(e)[:220],
                "human_action": f"Ask a metastore admin for CREATE CATALOG, "
                                f"or point the app at an existing catalog.",
                "sql": f"GRANT CREATE SCHEMA, USE CATALOG ON CATALOG {cat} TO `<app service principal>`"}
    try:
        pipeline.sql(f"CREATE SCHEMA IF NOT EXISTS {cat}.{sch}")
        made.append(f"schema {cat}.{sch}")
    except Exception as e:
        return {"ok": False, "stage": "schema", "error": str(e)[:220],
                "sql": f"GRANT CREATE SCHEMA, USE CATALOG ON CATALOG {cat} TO `<app service principal>`"}
    return {"ok": True, "created": made}


def fix_assistant() -> dict:
    """Create the Knowledge Assistant now rather than waiting for go."""
    import orchestrator
    orchestrator.ensure_ka()
    st = orchestrator.ka_state()
    return {"ok": bool(st.get("endpoint")), "state": st}


def fix_grants() -> dict:
    """Re-run the browse grants against the current target."""
    import orchestrator
    cfg = load_config()
    cat, sch = cfg.get("catalog") or "workspace", cfg.get("schema") or "docflow"
    out = orchestrator.grant_browse_access(cat, sch, cfg)
    if out["granted"]:
        return {"ok": True, "created": [f"browse access for {p}" for p in out["granted"]]}
    return {"ok": False,
            "human_action": f"Run as yourself in a SQL editor: GRANT USE SCHEMA, "
                            f"SELECT ON SCHEMA {cat}.{sch} TO `<your email>`",
            "error": (out["errors"] or [""])[0]}


def fix_models() -> dict:
    """Probe model names until one answers, save the winner to config."""
    r = pipeline.resolve_chat_model()
    save_config({"chat_endpoint": r["model"]})
    return {"ok": True, "model": r["model"],
            "note": r["note"] or f"{r['model']} answers ai_query"}


def fix_billing() -> dict:
    """Ask the platform to enable the billing system schema and report the
    answer verbatim. This usually requires account admin rights."""
    w = pipeline.wc()
    try:
        ms = w.metastores.current()
        w.system_schemas.enable(ms.metastore_id, "billing")
        return {"ok": True, "note": "Requested. Re-check in a moment."}
    except Exception as e:
        return {"ok": False, "error": _clean(str(e)),
                "human_action": "Enable it from the account console: Settings, "
                                "System schemas, billing. Cost stays an estimate "
                                "until then, which never blocks a demo."}


def fix_everything() -> dict:
    """Repair the workspace in one press.

    Order matters: a warehouse has to exist before the catalog and volume can be
    created, because those run SQL. Each step reports for itself, and one
    failure never stops the ones that do not depend on it.
    """
    done: list[dict] = []

    def run(key, label, fn, needs=None):
        if needs and not any(d["key"] == needs and d["ok"] for d in done):
            done.append({"key": key, "label": label, "ok": False, "skipped": True,
                         "detail": f"skipped, needs {needs} first"})
            return
        try:
            out = fn()
            ok = out.get("ok", True) is not False
            done.append({"key": key, "label": label, "ok": ok,
                         "detail": (out.get("error") or _summarise(out))[:160]})
        except Exception as e:
            done.append({"key": key, "label": label, "ok": False,
                         "detail": _clean(str(e), 150)})

    checks = {c["key"]: c for c in readiness()["checks"]}

    if not checks.get("warehouse", {}).get("ok"):
        run("warehouse", "Serverless warehouse", create_serverless_warehouse)
    else:
        done.append({"key": "warehouse", "label": "Serverless warehouse", "ok": True,
                     "detail": "already available"})

    if not checks.get("catalog", {}).get("ok"):
        run("catalog", "Catalog and schema", fix_catalog, needs="warehouse")
    else:
        done.append({"key": "catalog", "label": "Catalog and schema", "ok": True,
                     "detail": "already available"})

    if not checks.get("volume", {}).get("ok"):
        run("volume", "Document volume", lambda: pipeline.bootstrap(), needs="warehouse")
    else:
        done.append({"key": "volume", "label": "Document volume", "ok": True,
                     "detail": "already available"})

    if not checks.get("endpoints", {}).get("ok"):
        run("endpoints", "Language model", fix_models, needs="warehouse")
    else:
        done.append({"key": "endpoints", "label": "Language model", "ok": True,
                     "detail": "already answering"})

    rd = readiness(deep=True)
    return {"ok": not rd["blockers"], "steps": done, "readiness": rd,
            "blockers": rd["blockers"]}


def _summarise(out: dict) -> str:
    if isinstance(out.get("created"), list):
        return "created " + ", ".join(out["created"])
    if out.get("warehouse_id"):
        return f"created {out.get('name', 'warehouse')}, stops after 10 idle minutes"
    if out.get("statements"):
        return f"{out['statements']} statements applied"
    return "done"


def fix_probe() -> dict:
    """Start the warehouse, then run the deep checks that need SQL.

    Reports failure honestly when there is nothing to start: a green result on
    an action that changed nothing is worse than no button at all.
    """
    w = pipeline.wc()
    try:
        cands = [x for x in w.warehouses.list()
                 if getattr(x, "enable_serverless_compute", False) and x.id]
    except Exception as e:
        return {"ok": False, "error": _clean(str(e)),
                "human_action": "The app cannot list warehouses in this workspace."}
    if not cands:
        return {"ok": False,
                "error": "No serverless warehouse is visible to this app.",
                "human_action": "Use 'Create one' on the warehouse check first, then test again.",
                "depends_on": "warehouse"}
    target = next((x for x in cands
                   if getattr(x.state, "value", str(x.state)) == "RUNNING"), cands[0])
    started = None
    if getattr(target.state, "value", str(target.state)) != "RUNNING":
        try:
            w.warehouses.start(target.id).result()
            started = target.name
        except Exception as e:
            return {"ok": False, "error": _clean(str(e)),
                    "human_action": f"Could not start {target.name}. Start it from SQL Warehouses."}
    pipeline.WAREHOUSE_ID = target.id
    rd = readiness(deep=True)
    by = {c["key"]: c for c in rd["checks"]}
    ran = bool(by.get("ai_functions", {}).get("ok"))
    return {"ok": ran,
            "started": started or f"{target.name} already running",
            "error": None if ran else by.get("ai_functions", {}).get("detail", "")[:200],
            "readiness": rd}


# ------------------------------------------------------------------ metrics
def metrics() -> dict:
    """Measured facts about the last run. Absent values are omitted, never faked."""
    snap = pipeline.STATE.snapshot()
    docs = snap.get("docs") or {}
    out: dict[str, Any] = {
        "run_id": snap.get("run_id"),
        "phase": snap.get("phase"),
        "elapsed_s": snap.get("elapsed_s"),
        "docs_total": len(docs),
        "stages": pipeline.STATE.stage_timings(),
    }

    lanes: dict[str, int] = {k: 0 for k in LANE_NAMES}
    disagreements = []
    conf_buckets = {"0.90-1.00": 0, "0.80-0.90": 0, "below 0.80": 0}
    confs: list[float] = []
    sens: dict[str, int] = {}
    for doc_id, d in docs.items():
        lane = d.get("lane")
        if lane in lanes:
            lanes[lane] += 1
        if d.get("policy_agrees") is False:
            disagreements.append({"doc_id": doc_id, "policy_lane": d.get("lane"),
                                  "agent_lane": d.get("agent_lane")})
        c = d.get("confidence")
        if isinstance(c, (int, float)):
            confs.append(float(c))
            conf_buckets["0.90-1.00" if c >= 0.9 else
                         "0.80-0.90" if c >= 0.8 else "below 0.80"] += 1
        s = (d.get("sensitivity") or "").lower()
        if s:
            sens[s] = sens.get(s, 0) + 1
    out["lanes"] = lanes
    out["lane_names"] = LANE_NAMES
    out["policy_disagreements"] = disagreements
    if confs:
        confs.sort()
        out["confidence"] = {
            "buckets": [{"range": k, "n": v} for k, v in conf_buckets.items()],
            "min": round(min(confs), 2),
            "median": round(confs[len(confs) // 2], 2),
        }
    if sens:
        out["sensitivity"] = sens

    money = snap.get("money") or {}
    out["cost"] = {"usd": money.get("cost_usd"), "is_estimate": True,
                   "basis": money.get("cost_basis") or
                   "Per-page parse plus task-function calls. Authoritative figures "
                   "in system.billing.usage."}

    # Table-backed figures need the warehouse. Never START one to render a page:
    # a serverless warehouse begins billing the moment a statement wakes it.
    if not warehouse_is_running():
        out["tables_unavailable"] = (
            "Table figures are not shown because the SQL warehouse is stopped. "
            "Reading them would start it and begin billing. Start the warehouse "
            "or run the pipeline to populate these.")
        return out
    try:
        wr = pipeline.sql(f"""SELECT
                count(*),
                sum(CASE WHEN claim_status='outside window' THEN 1 ELSE 0 END),
                sum(CASE WHEN claim_status='needs review' THEN 1 ELSE 0 END),
                coalesce(sum(CASE WHEN claim_status='outside window'
                                  THEN claim_amount ELSE 0 END),0)
            FROM {pipeline.FQ}.extract_warranty_claims""")
        inv = pipeline.sql(f"SELECT count(*) FROM {pipeline.FQ}.extract_supplier_invoices")
        af = pipeline.sql(f"""SELECT count(*),
                sum(CASE WHEN severity='HIGH' THEN 1 ELSE 0 END),
                sum(CASE WHEN severity='MEDIUM' THEN 1 ELSE 0 END)
            FROM {pipeline.FQ}.audit_findings""")
        out["extraction"] = {"warranty_rows": int(wr[0][0] or 0),
                             "invoice_rows": int(inv[0][0] or 0),
                             "needs_review_rows": int(wr[0][2] or 0)}
        out["audit"] = {"findings": int(af[0][0] or 0),
                        "high": int(af[0][1] or 0), "medium": int(af[0][2] or 0),
                        "caught_usd": float(wr[0][3] or 0.0)}
    except Exception as e:
        out["tables_unavailable"] = (
            "Table figures need the SQL warehouse running. " + str(e)[:120])
    return out
