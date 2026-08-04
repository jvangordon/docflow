# Databricks notebook source
# MAGIC %md
# MAGIC # Install DocFlow
# MAGIC
# MAGIC You are looking at this because you cloned the repo into your workspace as a
# MAGIC Git folder. Press **Run all**. Nothing else is needed, and no command line.
# MAGIC
# MAGIC This notebook runs as **you**, which is the point: it can create the app and
# MAGIC then grant that app the two rights it needs to set the workspace up on its own.
# MAGIC
# MAGIC When it finishes it prints a link. Open it and you are at the Start page.

# COMMAND ----------

# MAGIC %pip install --quiet databricks-sdk --upgrade
# MAGIC %restart_python

# COMMAND ----------

APP_NAME = "docflow"

# Catalog the app works in. The widget above the notebook lets you point the
# install at an EXISTING catalog (say, a sandbox your admin gave you) — the
# notebook only creates the catalog when it does not exist yet, and the app
# never touches anything in it beyond its own schema.
CATALOG = "workspace"
try:
    dbutils.widgets.text("catalog", CATALOG)          # noqa: F821
    CATALOG = dbutils.widgets.get("catalog").strip() or CATALOG  # noqa: F821
except NameError:
    pass

# COMMAND ----------

import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.apps import AppDeployment
from databricks.sdk.service.workspace import ImportFormat

w = WorkspaceClient()
me = w.current_user.me().user_name


def find_source_path() -> str:
    """The app folder inside this Git clone."""
    try:
        ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()  # noqa: F821
        here = ctx.notebookPath().get()
        folder = "/Workspace" + here.rsplit("/", 1)[0]
        return folder + "/app"
    except Exception:
        return f"/Workspace/Users/{me}/agentbricks-doc-demo/app"


SOURCE = find_source_path()
print(f"workspace : {w.config.host}")
print(f"as        : {me}")
print(f"source    : {SOURCE}")

# COMMAND ----------

# MAGIC %md ## 1. Create the app

# COMMAND ----------

from databricks.sdk.service.apps import App

existing = {a.name for a in w.apps.list()}
if APP_NAME in existing:
    print(f"'{APP_NAME}' already exists, reusing it")
else:
    print(f"creating '{APP_NAME}', this provisions compute and takes a few minutes")
    w.apps.create(app=App(name=APP_NAME,
                          description="DocFlow: documents in, governed tables and cited answers out.")).result()
    print("created")

# COMMAND ----------

# MAGIC %md ## 2. Deploy the code from this Git folder

# COMMAND ----------

# Tell the app who installed it, so its grants can name a real person instead
# of guessing at workspace group names.
try:
    import os as _os
    yaml_path = SOURCE.replace("/Workspace", "", 1) + "/app.yaml"
    body = w.workspace.download(yaml_path).read().decode()
    add = []
    if "DOCFLOW_OWNER" not in body:
        add.append(("DOCFLOW_OWNER", me))
    if "DOCFLOW_CATALOG" not in body and CATALOG != "workspace":
        add.append(("DOCFLOW_CATALOG", CATALOG))
    if add:
        if "\nenv:" not in body:
            body = body.rstrip() + "\nenv:\n"
        else:
            body = body.rstrip() + "\n"
        for k, v in add:
            body += f"  - name: {k}\n    value: {v}\n"
        import io as _io
        w.workspace.upload(yaml_path, _io.BytesIO(body.encode()),
                           format=ImportFormat.AUTO, overwrite=True)
        print("recorded: " + ", ".join(k for k, _ in add))
except Exception as e:
    print(f"could not record installer identity ({str(e)[:80]}) — the app will "
          f"grant to workspace groups instead")

dep = w.apps.deploy(app_name=APP_NAME,
                    app_deployment=AppDeployment(source_code_path=SOURCE)).result()
print("deployment:", dep.status.state if dep.status else "?",
      "-", dep.status.message if dep.status else "")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Make the catalog, and give the app its rights
# MAGIC
# MAGIC A new app has an identity with rights to nothing, and creating a catalog
# MAGIC needs a privilege that identity will never have in a fresh workspace. This
# MAGIC notebook runs as **you**, so it creates the catalog here and then grants the
# MAGIC app what it needs — which is what lets the readiness panel build the rest
# MAGIC for you instead of sending you to the console.

# COMMAND ----------

from databricks.sdk.service import iam
from databricks.sdk.service.catalog import PermissionsChange, Privilege

sp = None
for _ in range(30):
    sp = w.apps.get(APP_NAME).service_principal_client_id
    if sp:
        break
    time.sleep(4)
print("app identity:", sp)

rec = next((s for s in w.service_principals.list() if s.application_id == sp), None)
if rec and "allow-cluster-create" in {e.value for e in (rec.entitlements or [])}:
    print("cluster creation: already granted")
elif rec:
    try:
        w.service_principals.patch(
            rec.id,
            operations=[iam.Patch(op=iam.PatchOp.ADD, path="entitlements",
                                  value=[{"value": "allow-cluster-create"}])],
            schemas=[iam.PatchSchema.URN_IETF_PARAMS_SCIM_API_MESSAGES_2_0_PATCH_OP])
        print("cluster creation: granted")
    except Exception as e:
        print("cluster creation: FAILED —", str(e)[:160])
        print("  a workspace admin can tick 'Allow cluster creation' on this")
        print("  service principal under Settings, Identity and access.")

# Creating a catalog needs CREATE CATALOG on the metastore, which an app's
# identity will not have in a fresh workspace. This notebook runs as you, so
# it does that part here rather than letting the app fail at it later.
def _sql(stmt):
    whs = [x for x in w.warehouses.list()
           if getattr(x, "enable_serverless_compute", False) and x.id]
    if not whs:
        raise RuntimeError("no serverless warehouse yet")
    r = w.statement_execution.execute_statement(
        warehouse_id=whs[0].id, statement=stmt, wait_timeout="50s")
    st = r.status.state.value if r.status and r.status.state else "?"
    t0 = time.time()
    while st in ("PENDING", "RUNNING") and time.time() - t0 < 180:
        time.sleep(3)
        r = w.statement_execution.get_statement(r.statement_id)
        st = r.status.state.value if r.status and r.status.state else "?"
    if st != "SUCCEEDED":
        raise RuntimeError(f"{st}: {getattr(r.status, 'error', '')}")
    return r

have = []
try:
    have = [c.name for c in w.catalogs.list()]
except Exception:
    pass
if CATALOG in have:
    print(f"catalog '{CATALOG}': already exists")
else:
    made = False
    try:
        _sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
        made = True
        print(f"catalog '{CATALOG}': created (as you, not as the app)")
    except Exception as e1:
        try:
            w.catalogs.create(name=CATALOG)
            made = True
            print(f"catalog '{CATALOG}': created over the catalogs API")
        except Exception as e2:
            print(f"catalog '{CATALOG}': COULD NOT CREATE — {str(e1)[:110]}")
            print(f"  Create it yourself in Catalog Explorer, or pick a catalog you")
            print(f"  already own under Advanced on the app's Start page. Then re-run")
            print(f"  this notebook so the app gets its grants on it.")

try:
    w.grants.update(securable_type="catalog", full_name=CATALOG,
                    changes=[PermissionsChange(
                        principal=sp,
                        add=[Privilege.USE_CATALOG, Privilege.CREATE_SCHEMA])])
    print(f"catalog access: granted on {CATALOG}")
except Exception as e:
    print("catalog access: FAILED —", str(e)[:160])
    print(f"  a metastore admin can run:")
    print(f"    GRANT USE CATALOG, CREATE SCHEMA ON CATALOG {CATALOG} TO `{sp}`")

# COMMAND ----------

# MAGIC %md ## Done

# COMMAND ----------

url = w.apps.get(APP_NAME).url
displayHTML(f"""
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;padding:26px 28px;
     border-radius:14px;background:#12161A;border:1px solid rgba(242,240,236,.15);max-width:640px">
  <div style="font:600 11px ui-monospace,monospace;letter-spacing:.2em;text-transform:uppercase;
       color:#5C6670">DocFlow is installed</div>
  <div style="font-size:26px;font-weight:800;letter-spacing:-.02em;color:#F2F0EC;margin:12px 0 10px">
    Open the app</div>
  <a href="{url}" target="_blank" style="display:inline-block;background:linear-gradient(135deg,#FF3B20,#FF7A45);
     color:#fff;font-weight:700;text-decoration:none;padding:11px 22px;border-radius:9px">{url}</a>
  <p style="color:#98A1AB;font-size:14.5px;line-height:1.6;margin:18px 0 0">
    Press <b style="color:#F2F0EC">Set up this workspace</b>, then give it a customer name
    and an industry and press <b style="color:#F2F0EC">Go</b>.</p>
  <p style="color:#5C6670;font-size:12.5px;margin:14px 0 0">
    To update later: pull in this Git folder, then run this notebook again.</p>
</div>
""")
