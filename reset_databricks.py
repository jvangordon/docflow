# Databricks notebook source
# MAGIC %md
# MAGIC # Reset DocFlow
# MAGIC
# MAGIC Removes everything DocFlow created in this workspace, so the next install
# MAGIC starts genuinely fresh. Press **Run all**.
# MAGIC
# MAGIC **Removed:** the `docflow` app and its identity · the Knowledge Assistant and
# MAGIC its endpoint · the Genie space · the `workspace.docflow` schema with every
# MAGIC table, the volume, and all generated documents.
# MAGIC
# MAGIC **Kept:** this Git folder (it is the installer) and the workspace's SQL
# MAGIC warehouse. Delete those by hand if you want a truly blank slate.

# COMMAND ----------

# MAGIC %pip install --quiet databricks-sdk --upgrade
# MAGIC %restart_python

# COMMAND ----------

APP_NAME = "docflow"
CATALOG = "workspace"
SCHEMA = "docflow"
KA_DISPLAY = "docflow-ka"
GENIE_TITLE = "DocFlow Genie"

# COMMAND ----------

import time

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
print(f"workspace : {w.config.host}")
print(f"as        : {w.current_user.me().user_name}")

# COMMAND ----------

# MAGIC %md ## 1. The app

# COMMAND ----------

if APP_NAME in {a.name for a in w.apps.list()}:
    w.apps.delete(name=APP_NAME)
    for _ in range(40):
        if APP_NAME not in {a.name for a in w.apps.list()}:
            break
        time.sleep(5)
    gone = APP_NAME not in {a.name for a in w.apps.list()}
    print(f"app '{APP_NAME}': {'removed, its identity went with it' if gone else 'delete still propagating, harmless'}")
else:
    print(f"app '{APP_NAME}': already gone")

# COMMAND ----------

# MAGIC %md ## 2. The Knowledge Assistant

# COMMAND ----------

try:
    hits = [x for x in w.knowledge_assistants.list_knowledge_assistants()
            if (x.display_name or "") == KA_DISPLAY]
    for x in hits:
        w.knowledge_assistants.delete_knowledge_assistant(x.name)
        print(f"assistant '{KA_DISPLAY}': removed ({x.name}), endpoint goes with it")
    if not hits:
        print(f"assistant '{KA_DISPLAY}': already gone")
except Exception as e:
    print(f"assistant: could not remove — {str(e)[:140]}")
    print("  remove it by hand under AI/ML, Agents if it is still listed")

# COMMAND ----------

# MAGIC %md ## 3. The Genie space

# COMMAND ----------

try:
    hits = [s for s in (w.genie.list_spaces().spaces or [])
            if (s.title or "") == GENIE_TITLE]
    for s in hits:
        w.genie.trash_space(s.space_id)
        print(f"genie space '{GENIE_TITLE}': trashed")
    if not hits:
        print(f"genie space '{GENIE_TITLE}': already gone")
except Exception as e:
    print(f"genie: could not remove — {str(e)[:140]}")

# COMMAND ----------

# MAGIC %md ## 4. The schema, tables, volume and documents

# COMMAND ----------

whs = [x for x in w.warehouses.list()
       if getattr(x, "enable_serverless_compute", False) and x.id]
if SCHEMA not in [s.name for s in w.schemas.list(CATALOG)]:
    print(f"schema {CATALOG}.{SCHEMA}: already gone")
elif not whs:
    print("no serverless warehouse to run the DROP — remove the schema in Catalog Explorer")
else:
    r = w.statement_execution.execute_statement(
        warehouse_id=whs[0].id, wait_timeout="50s",
        statement=f"DROP SCHEMA IF EXISTS {CATALOG}.{SCHEMA} CASCADE")
    state = r.status.state.value if r.status and r.status.state else "?"
    t0 = time.time()
    while state in ("PENDING", "RUNNING") and time.time() - t0 < 240:
        time.sleep(4)
        r = w.statement_execution.get_statement(r.statement_id)
        state = r.status.state.value if r.status and r.status.state else "?"
    print(f"schema {CATALOG}.{SCHEMA}: dropped with everything in it ({state})")

# COMMAND ----------

# MAGIC %md ## Verify

# COMMAND ----------

apps = [a.name for a in w.apps.list()]
ka_eps = []
try:
    ka_eps = [e.name for e in w.serving_endpoints.list() if (e.name or "").startswith("ka-")]
except Exception:
    pass
spaces = [s.title for s in (w.genie.list_spaces().spaces or [])]
schemas = [s.name for s in w.schemas.list(CATALOG)]

rows = [
    ("apps", apps or "none"),
    ("ka endpoints", ka_eps or "none"),
    ("genie spaces", spaces or "none"),
    (f"schemas in {CATALOG}", schemas),
]
clean = APP_NAME not in apps and not ka_eps and GENIE_TITLE not in spaces and SCHEMA not in schemas
for k, v in rows:
    print(f"{k:22s}: {v}")
print()
print("RESET COMPLETE — workspace is fresh" if clean
      else "some items are still listed above — usually deletion still propagating; re-run this cell")

# COMMAND ----------

displayHTML("""
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;padding:26px 28px;
     border-radius:14px;background:#12161A;border:1px solid rgba(242,240,236,.15);max-width:640px">
  <div style="font:600 11px ui-monospace,monospace;letter-spacing:.2em;text-transform:uppercase;
       color:#5C6670">DocFlow removed</div>
  <div style="font-size:26px;font-weight:800;letter-spacing:-.02em;color:#F2F0EC;margin:12px 0 10px">
    This workspace is fresh</div>
  <p style="color:#98A1AB;font-size:14.5px;line-height:1.6;margin:0">
    To install again, open <b style="color:#F2F0EC">setup_databricks.py</b> in this folder
    and press <b style="color:#F2F0EC">Run all</b>.</p>
</div>
""")
