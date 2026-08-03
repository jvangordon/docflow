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
CATALOG = "workspace"   # catalog the app may create its schema in

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
    if "DOCFLOW_OWNER" not in body:
        body = body.rstrip() + f"\nenv:\n  - name: DOCFLOW_OWNER\n    value: {me}\n"
        import io as _io
        w.workspace.upload(yaml_path, _io.BytesIO(body.encode()),
                           format=ImportFormat.AUTO, overwrite=True)
        print(f"recorded installer identity: {me}")
except Exception as e:
    print(f"could not record installer identity ({str(e)[:80]}) — the app will "
          f"grant to workspace groups instead")

dep = w.apps.deploy(app_name=APP_NAME,
                    app_deployment=AppDeployment(source_code_path=SOURCE)).result()
print("deployment:", dep.status.state if dep.status else "?",
      "-", dep.status.message if dep.status else "")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Give the app the rights to set the workspace up
# MAGIC
# MAGIC A new app has an identity with rights to nothing. These two grants are what
# MAGIC let the readiness panel create a warehouse, a schema and a volume for you
# MAGIC instead of sending you to the console.

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
