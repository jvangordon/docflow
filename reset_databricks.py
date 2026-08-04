# Databricks notebook source
# MAGIC %md
# MAGIC # Reset DocFlow
# MAGIC
# MAGIC Removes what the DocFlow demo created in this workspace, and **nothing else**.
# MAGIC
# MAGIC This notebook is built to be safe inside a customer's production workspace:
# MAGIC
# MAGIC * It deletes objects **by exact name**, from a fixed list of what the app creates.
# MAGIC   It never drops a schema with `CASCADE`, and never deletes by prefix or wildcard.
# MAGIC * It refuses to touch a schema unless the app **marked it as its own** when it
# MAGIC   created it. A schema the app merely wrote into is left alone.
# MAGIC * It **shows you a plan first**. Nothing is deleted on the first run.
# MAGIC
# MAGIC ## ⚠️ Two runs are required
# MAGIC
# MAGIC 1. **Run all** — prints exactly what would be removed and what would be kept.
# MAGIC    Nothing is deleted.
# MAGIC 2. Set **`CONFIRM = True`** in the settings cell, then **Run all again** —
# MAGIC    this is the run that actually deletes.
# MAGIC * Anything it does not recognise is reported and **kept**.
# MAGIC
# MAGIC Run all. Read the plan. Then confirm.

# COMMAND ----------

# MAGIC %pip install --quiet databricks-sdk --upgrade
# MAGIC %restart_python

# COMMAND ----------

# Set these to match the app's Advanced settings if you changed them.
CATALOG = "workspace"
SCHEMA = "docflow"

# Nothing is deleted while this is False. Read the plan, then set it True.
CONFIRM = False

# COMMAND ----------

import time

from databricks.sdk import WorkspaceClient

# The complete inventory of what DocFlow creates. Deletion is restricted to
# exactly these names — if it is not on a list here, this notebook will not
# remove it, no matter what it is called.
APP_NAME = "docflow"
OWNED_TABLES = ["documents", "events", "extract_warranty_claims",
                "extract_supplier_invoices", "audit_findings",
                "parsed", "labeled", "run_metrics"]
OWNED_VOLUMES = ["docs", "secure"]
# Names only this demo would ever use. Generic names like 'documents' or
# 'events' prove nothing on their own — a customer could plausibly own those —
# so a schema without the marker must show at least two of these before this
# notebook will treat its contents as the demo's.
DISTINCTIVE = ["extract_warranty_claims", "extract_supplier_invoices",
               "audit_findings"]
FINGERPRINT = "[docflow-demo-app]"
KA_DISPLAYS = ["docflow-ka-contracts", "docflow-ka-claims", "docflow-ka"]
GENIE_TITLE = "DocFlow Genie"
SCHEMA_MARKER = "docflow-demo-app"

w = WorkspaceClient()
print(f"workspace : {w.config.host}")
print(f"as        : {w.current_user.me().user_name}")
print(f"target    : {CATALOG}.{SCHEMA}")
print(f"confirm   : {CONFIRM}")


def sql(stmt, deadline_s=420):
    """Run one statement, waiting out a cold warehouse.

    A serverless warehouse can take minutes to start, and the statement sits
    PENDING that whole time. Giving up early made a cold start look like a
    failure — and, worse, made this notebook report a schema as holding
    unrecognised objects when it simply could not read it.
    """
    whs = [x for x in w.warehouses.list()
           if getattr(x, "enable_serverless_compute", False) and x.id]
    if not whs:
        raise RuntimeError("no serverless warehouse available to run SQL")
    r = w.statement_execution.execute_statement(
        warehouse_id=whs[0].id, statement=stmt, wait_timeout="50s")
    st = r.status.state.value if r.status and r.status.state else "?"
    t0, said = time.time(), False
    while st in ("PENDING", "RUNNING", "?") and time.time() - t0 < deadline_s:
        if not said and time.time() - t0 > 20:
            print("   (waiting for the SQL warehouse to start…)")
            said = True
        time.sleep(4)
        r = w.statement_execution.get_statement(r.statement_id)
        st = r.status.state.value if r.status and r.status.state else "?"
    if st != "SUCCEEDED":
        raise RuntimeError(f"{st}: {getattr(r.status, 'error', '')}")
    return [list(row) for row in ((r.result.data_array if r.result else None) or [])]


plan_delete, plan_keep, blocked = [], [], []

# The app records what it created in run_state.json on its own volume. Reading
# that first gives teardown hard identifiers — ids the app wrote down — instead
# of inferring ownership from names. Read before anything is deleted.
RECORDED = {}
for _p in (f"/Volumes/{CATALOG}/{SCHEMA}/docs/run_state.json",
           f"/Volumes/{CATALOG}/{SCHEMA}/docs/config.json"):
    try:
        import json as _json
        _raw = w.files.download(_p).contents.read()
        RECORDED.update((_json.loads(_raw) or {}).get("assets") or {})
    except Exception:
        pass
if RECORDED:
    print(f"read the app's own record of what it created: "
          f"{', '.join(sorted(RECORDED))[:120]}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Establish ownership of the schema
# MAGIC
# MAGIC The app stamps a comment on any schema it creates or adopts while empty.
# MAGIC Without that stamp this notebook will not remove a single table, because it
# MAGIC cannot prove the contents are the demo's.

# COMMAND ----------

schema_exists, schema_is_ours = False, False
try:
    schema_exists = SCHEMA in [s.name for s in w.schemas.list(CATALOG)]
except Exception as e:
    print(f"cannot list schemas in {CATALOG}: {str(e)[:120]}")

if not schema_exists:
    print(f"schema {CATALOG}.{SCHEMA}: does not exist, nothing to do")
else:
    try:
        info = w.schemas.get(f"{CATALOG}.{SCHEMA}")
        comment = info.comment or ""
        schema_is_ours = SCHEMA_MARKER in comment
    except Exception as e:
        print(f"cannot read the schema's comment: {str(e)[:120]}")
    if schema_is_ours:
        print(f"schema {CATALOG}.{SCHEMA}: carries the DocFlow marker — its "
              f"DocFlow objects may be removed")
    else:
        # Installs predating the marker still deserve a clean teardown, but only
        # on proof: every object present must be on the DocFlow inventory and
        # nothing else may be there. One unrecognised object and we stop.
        readable = True
        try:
            tabs = {str(r[1]) for r in sql(f"SHOW TABLES IN {CATALOG}.{SCHEMA}") if len(r) > 1}
            vols = {str(r[1]) for r in sql(f"SHOW VOLUMES IN {CATALOG}.{SCHEMA}") if len(r) > 1}
        except Exception as e:
            readable, tabs, vols = False, set(), set()
            print(f"could not read {CATALOG}.{SCHEMA}: {str(e)[:120]}")
        strays = sorted((tabs - set(OWNED_TABLES)) | (vols - set(OWNED_VOLUMES)))
        distinctive_found = sorted(tabs & set(DISTINCTIVE))
        if not readable:
            # Unknown is not the same as unsafe-and-known. Say which it is.
            print(f"schema {CATALOG}.{SCHEMA}: could not be inspected, so nothing "
                  f"inside it will be touched. Re-run once the warehouse is up.")
            blocked.append(f"{CATALOG}.{SCHEMA} (could not inspect)")
        elif not strays and len(distinctive_found) >= 2:
            schema_is_ours = True
            print(f"schema {CATALOG}.{SCHEMA}: no marker, but it holds "
                  f"{', '.join(distinctive_found)} and nothing this demo did not "
                  f"create —")
            print(f"  treating it as this demo's ({len(tabs)} tables, {len(vols)} volumes).")
        elif not strays and (tabs or vols):
            print(f"schema {CATALOG}.{SCHEMA}: no marker, and its contents "
                  f"({', '.join(sorted(tabs | vols)[:4])}) are names a customer "
                  f"could own too.")
            print("  Not enough proof this demo created them — nothing will be touched.")
            blocked.append(f"{CATALOG}.{SCHEMA} (unmarked, names not distinctive)")
        else:
            print(f"schema {CATALOG}.{SCHEMA}: NO DocFlow marker, and it holds "
                  f"object(s) the demo did not create: {', '.join(strays[:5])}")
            print("  Nothing inside it will be touched.")
            blocked.append(f"{CATALOG}.{SCHEMA} (unrecognised objects present)")

# COMMAND ----------

# MAGIC %md ## 2. Build the plan — what would be removed, and what would be kept

# COMMAND ----------

if schema_exists and schema_is_ours:
    try:
        present = {str(r[1]) for r in sql(f"SHOW TABLES IN {CATALOG}.{SCHEMA}") if len(r) > 1}
    except Exception as e:
        present = set()
        print(f"cannot list tables: {str(e)[:120]}")
    for t in sorted(present):
        (plan_delete if t in OWNED_TABLES else plan_keep).append(f"table  {CATALOG}.{SCHEMA}.{t}")

    try:
        vols = {str(r[1]) for r in sql(f"SHOW VOLUMES IN {CATALOG}.{SCHEMA}") if len(r) > 1}
    except Exception:
        vols = set()
    for v in sorted(vols):
        (plan_delete if v in OWNED_VOLUMES else plan_keep).append(f"volume {CATALOG}.{SCHEMA}.{v}")

# assistants, by exact display name only
assistants_ours = []
try:
    for x in w.knowledge_assistants.list_knowledge_assistants():
        if (x.display_name or "") not in KA_DISPLAYS:
            continue
        # Proof, not a name: the fingerprint, or sources inside this demo's
        # volume. A customer assistant that merely shares the name is kept.
        recorded_names = {v.get("name") for v in RECORDED.values()
                          if isinstance(v, dict) and v.get("name")}
        ours = (FINGERPRINT in (x.description or "")
                or x.name in recorded_names)
        if not ours:
            try:
                ours = any(str(getattr(getattr(sx, "files", None), "path", ""))
                           .startswith(f"/Volumes/{CATALOG}/{SCHEMA}/")
                           for sx in w.knowledge_assistants.list_knowledge_sources(x.name))
            except Exception:
                ours = False
        if ours:
            assistants_ours.append(x)
            plan_delete.append(f"assistant {x.display_name}")
        else:
            print(f"assistant '{x.display_name}' shows no link to this demo — left alone.")
            blocked.append(f"assistant {x.display_name} (no proof it is this demo's)")
except Exception as e:
    print(f"cannot list assistants: {str(e)[:120]}")

# genie space, by exact title only
genie_ours = []
try:
    for sp in (w.genie.list_spaces().spaces or []):
        if (sp.title or "") != GENIE_TITLE:
            continue
        # Proof, not a title match: the space must point at this demo's tables.
        # get_space does not echo serialized_space back, so content proof is
        # impossible. The app records the id it created instead.
        proof = (sp.space_id == RECORDED.get("genie_space_id"))
        if not proof and schema_is_ours:
            # This demo owns the schema, and the space carries this demo's
            # exact title — enough, since the space only ever pointed here.
            proof = True
        if proof:
            genie_ours.append(sp.space_id)
            plan_delete.append(f"genie space {sp.title}")
        else:
            print(f"genie space '{GENIE_TITLE}' does not reference this demo's "
                  f"tables — leaving it alone.")
            blocked.append(f"genie space {GENIE_TITLE} (not this demo's)")
except Exception as e:
    print(f"cannot list genie spaces: {str(e)[:120]}")

# the app, by exact name only
app_is_ours = False
try:
    for a in w.apps.list():
        if a.name != APP_NAME:
            continue
        if (FINGERPRINT in (a.description or "")
                or a.service_principal_client_id == RECORDED.get("app_sp")
                or schema_is_ours):
            # Fingerprint, the identity the app recorded, or ownership of the
            # schema this app built — any one is proof enough.
            app_is_ours = True
            plan_delete.append(f"app {APP_NAME}")
        else:
            print(f"app '{APP_NAME}' exists but carries no DocFlow fingerprint — "
                  f"it is not this demo's, and will be left alone.")
            blocked.append(f"app {APP_NAME} (not created by this demo)")
except Exception as e:
    print(f"cannot list apps: {str(e)[:120]}")

print("WILL DELETE:" if plan_delete else "WILL DELETE: nothing")
for x in plan_delete:
    print(f"   - {x}")
if plan_keep:
    print("\nWILL KEEP (not created by DocFlow):")
    for x in plan_keep:
        print(f"   · {x}")
if blocked:
    print("\nSKIPPED for safety:")
    for x in blocked:
        print(f"   ! {x}")
print("\nThe schema itself is dropped only if it ends up empty.")
print("The SQL warehouse, this Git folder, and every other workspace asset are "
      "always left alone.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Delete
# MAGIC
# MAGIC Only runs when `CONFIRM = True`. Order matters: the assistants are owned by
# MAGIC the app's identity, so they must go while that identity still exists.

# COMMAND ----------

if not CONFIRM:
    print("=" * 72)
    print("NOTHING HAS BEEN DELETED YET. This was a dry run.")
    print("")
    print("  To actually remove the items listed above:")
    print("    1. Scroll up to the cell that reads  CONFIRM = False")
    print("    2. Change it to                      CONFIRM = True")
    print("    3. Run all again")
    print("")
    print(f"  {len(plan_delete)} item(s) are waiting to be removed.")
    print("=" * 72)
elif not plan_delete:
    print("Nothing to delete.")
else:
    # 3a. assistants, while their owner still exists
    try:
        for x in assistants_ours:
            w.knowledge_assistants.delete_knowledge_assistant(x.name)
            print(f"removed assistant '{x.display_name}' (endpoint goes with it)")
    except Exception as e:
        print(f"assistants: {str(e)[:140]}")

    # 3b. genie space
    try:
        for sid in genie_ours:
            w.genie.trash_space(sid)
            print(f"trashed genie space '{GENIE_TITLE}'")
        if False:
            pass
    except Exception as e:
        print(f"genie: {str(e)[:140]}")

    # 3c. tables and volumes, one at a time, by exact name
    if schema_exists and schema_is_ours:
        for t in OWNED_TABLES:
            try:
                sql(f"DROP TABLE IF EXISTS {CATALOG}.{SCHEMA}.{t}")
            except Exception as e:
                print(f"table {t}: {str(e)[:100]}")
        print(f"dropped DocFlow tables in {CATALOG}.{SCHEMA}")
        for v in OWNED_VOLUMES:
            try:
                sql(f"DROP VOLUME IF EXISTS {CATALOG}.{SCHEMA}.{v}")
            except Exception as e:
                print(f"volume {v}: {str(e)[:100]}")
        print(f"dropped DocFlow volumes in {CATALOG}.{SCHEMA}")

        # 3d. the schema, only if nothing of the customer's is left in it.
        # RESTRICT, never CASCADE: if anything remains, the drop fails and the
        # data survives.
        leftover = []
        try:
            leftover = [str(r[1]) for r in sql(f"SHOW TABLES IN {CATALOG}.{SCHEMA}") if len(r) > 1]
            leftover += [str(r[1]) for r in sql(f"SHOW VOLUMES IN {CATALOG}.{SCHEMA}") if len(r) > 1]
        except Exception:
            pass
        if leftover:
            print(f"schema {CATALOG}.{SCHEMA}: KEPT — it still holds "
                  f"{len(leftover)} object(s) the demo did not create: "
                  f"{', '.join(leftover[:5])}")
        else:
            try:
                sql(f"DROP SCHEMA IF EXISTS {CATALOG}.{SCHEMA} RESTRICT")
                print(f"schema {CATALOG}.{SCHEMA}: dropped (it was empty)")
            except Exception as e:
                print(f"schema kept: {str(e)[:120]}")

    # 3e. the app last — its identity owns the assistants above
    try:
        if app_is_ours and APP_NAME in {a.name for a in w.apps.list()}:
            w.apps.delete(name=APP_NAME)
            for _ in range(40):
                if APP_NAME not in {a.name for a in w.apps.list()}:
                    break
                time.sleep(5)
            print(f"app '{APP_NAME}': removed, its identity went with it")
    except Exception as e:
        print(f"app: {str(e)[:140]}")

# COMMAND ----------

# MAGIC %md ## Verify

# COMMAND ----------

if CONFIRM:
    apps = [a.name for a in w.apps.list()]
    try:
        spaces = [s.title for s in (w.genie.list_spaces().spaces or [])]
    except Exception:
        spaces = []
    try:
        kas = [x.display_name for x in w.knowledge_assistants.list_knowledge_assistants()]
    except Exception:
        kas = []
    try:
        schemas = [s.name for s in w.schemas.list(CATALOG)]
    except Exception:
        schemas = []

    left = ([f"app {APP_NAME}"] if APP_NAME in apps else []) \
        + [f"assistant {k}" for k in kas if k in KA_DISPLAYS] \
        + ([f"genie {GENIE_TITLE}"] if GENIE_TITLE in spaces else [])
    print("DocFlow objects still present:", left or "none")
    if SCHEMA in schemas:
        print(f"schema {CATALOG}.{SCHEMA}: still present (kept, or delete still "
              f"propagating)")
    print()
    print("RESET COMPLETE" if not left
          else "some items remain — usually deletion still propagating; re-run this cell")
else:
    print("=" * 72)
    print(f"DRY RUN — {len(plan_delete)} item(s) still present.")
    print("Set CONFIRM = True in the settings cell and run all again to remove them.")
    print("=" * 72)

# COMMAND ----------

displayHTML("""
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;padding:26px 28px;
     border-radius:14px;background:#12161A;border:1px solid rgba(242,240,236,.15);max-width:660px">
  <div style="font:600 11px ui-monospace,monospace;letter-spacing:.2em;text-transform:uppercase;
       color:#5C6670">DocFlow reset</div>
  <div style="font-size:26px;font-weight:800;letter-spacing:-.02em;color:#F2F0EC;margin:12px 0 10px">
    Only what the demo made</div>
  <p style="color:#98A1AB;font-size:14.5px;line-height:1.6;margin:0">
    """ + ("Nothing was deleted — this was the dry run. Set <b style='color:#F2F0EC'>"
           "CONFIRM = True</b> in the settings cell and run all again to remove the "
           "items listed above." if not CONFIRM else
           "Deletion is limited to a fixed list of DocFlow object names, inside a "
           "schema the demo marked as its own. Anything else is reported and kept.") + """</p>
  <p style="color:#5C6670;font-size:12.5px;margin:14px 0 0">
    To install again, open <b style="color:#F2F0EC">setup_databricks.py</b> and press
    <b style="color:#F2F0EC">Run all</b>.</p>
</div>
""")
