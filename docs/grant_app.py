#!/usr/bin/env python3
"""One-time admin setup for a freshly installed DocFlow app.

A new Databricks App gets a new service principal with no rights. These two
grants are what let the readiness panel repair the workspace by itself:

  * the cluster-creation entitlement, so the warehouse fix button works
  * USE CATALOG and CREATE SCHEMA, so the catalog fix button works

Run once after `databricks apps create docflow`. Safe to run again.
"""
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import iam

APP = "docflow"
CATALOG = "workspace"


def main() -> int:
    w = WorkspaceClient()

    app = w.apps.get(APP)
    sp_app_id = app.service_principal_client_id
    if not sp_app_id:
        print(f"The app '{APP}' has no service principal yet. Wait for it to "
              f"finish provisioning, then run this again.")
        return 1
    print(f"app        : {APP}")
    print(f"identity   : {sp_app_id}")

    sp = next((s for s in w.service_principals.list()
               if s.application_id == sp_app_id), None)
    if sp is None:
        print("Could not find that service principal in this workspace.")
        return 1

    # 1. entitlement, so the app can create its own warehouse
    have = {e.value for e in (sp.entitlements or [])}
    if "allow-cluster-create" in have:
        print("entitlement: already had allow-cluster-create")
    else:
        try:
            w.service_principals.patch(
                sp.id,
                operations=[iam.Patch(op=iam.PatchOp.ADD, path="entitlements",
                                      value=[{"value": "allow-cluster-create"}])],
                schemas=[iam.PatchSchema.URN_IETF_PARAMS_SCIM_API_MESSAGES_2_0_PATCH_OP])
            print("entitlement: granted allow-cluster-create")
        except Exception as e:
            print(f"entitlement: FAILED, {str(e)[:160]}")
            print("             a workspace admin can tick 'Allow cluster creation' on")
            print("             this service principal under Settings, Identity and access.")

    # 2. catalog grants, so the app can create its schema and volume
    whs = [x for x in w.warehouses.list()
           if getattr(x, "enable_serverless_compute", False) and x.id]
    if not whs:
        print("grants     : skipped, no SQL warehouse exists yet to run GRANT on.")
        print("             Press 'Create one' in the app, then run this script again")
        print("             so the catalog fix button can work too.")
        return 0

    wh = whs[0]
    if str(getattr(wh.state, "value", wh.state)) != "RUNNING":
        print(f"grants     : starting {wh.name} to run the GRANT statements")
        w.warehouses.start(wh.id).result()

    stmts = [
        f"GRANT USE CATALOG ON CATALOG {CATALOG} TO `{sp_app_id}`",
        f"GRANT CREATE SCHEMA ON CATALOG {CATALOG} TO `{sp_app_id}`",
    ]
    for s in stmts:
        r = w.statement_execution.execute_statement(
            warehouse_id=wh.id, statement=s, wait_timeout="50s")
        state = r.status.state.value if r.status and r.status.state else "?"
        err = (r.status.error.message[:110] if r.status and r.status.error else "")
        print(f"grant      : {state:9s} {s.split(' ON ')[0][6:]:<24} {err}")

    print("\nDone. Open the app and press the fix buttons in the readiness panel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
