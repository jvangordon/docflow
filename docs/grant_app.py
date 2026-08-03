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

    # 2. catalog grants, through the Unity Catalog API rather than SQL, so this
    #    works on a cold workspace where no warehouse exists yet
    from databricks.sdk.service.catalog import PermissionsChange, Privilege
    try:
        # securable_type is a plain string here; the enum serialises wrong.
        w.grants.update(
            securable_type="catalog", full_name=CATALOG,
            changes=[PermissionsChange(
                principal=sp_app_id,
                add=[Privilege.USE_CATALOG, Privilege.CREATE_SCHEMA])])
        print(f"grants     : USE CATALOG + CREATE SCHEMA on {CATALOG}")
    except Exception as e:
        print(f"grants     : FAILED, {str(e)[:170]}")
        print(f"             a metastore admin can run this in any SQL editor:")
        print(f"               GRANT USE CATALOG, CREATE SCHEMA ON CATALOG {CATALOG} "
              f"TO `{sp_app_id}`")
        return 1

    print("\nDone. Open the app and press the fix buttons in the readiness panel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
