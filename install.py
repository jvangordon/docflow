#!/usr/bin/env python3
"""Install DocFlow into the current Databricks workspace. One command.

    python3 install.py                 install into your default CLI profile
    python3 install.py -p myprofile    install into another workspace

Creates the app, uploads the code, starts it, then grants its identity the two
rights it needs to repair the workspace by itself. Safe to run again.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import pathlib

APP = "docflow"
CATALOG = "workspace"
HERE = pathlib.Path(__file__).parent.resolve()

BOLD, DIM, GREEN, AMBER, RED, OFF = (
    "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")


def say(step: str, msg: str, tone: str = "") -> None:
    tint = {"ok": GREEN, "warn": AMBER, "err": RED}.get(tone, "")
    print(f"  {DIM}{step:<11}{OFF}{tint}{msg}{OFF}", flush=True)


def cli(*args: str, profile: str | None = None, timeout: int = 900) -> tuple[int, str]:
    cmd = ["databricks", *args] + (["-p", profile] if profile else [])
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr).strip()


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("-p", "--profile", default=None,
                    help="Databricks CLI profile (default: your DEFAULT profile)")
    ap.add_argument("--catalog", default=CATALOG,
                    help=f"catalog the app may create its schema in (default: {CATALOG})")
    a = ap.parse_args()

    print(f"\n{BOLD}Installing DocFlow{OFF}\n")

    if not shutil.which("databricks"):
        say("cli", "The Databricks CLI is not installed.", "err")
        print("\n  Install it, then run this again:")
        print("    brew tap databricks/tap && brew install databricks\n")
        return 1

    try:
        from databricks.sdk import WorkspaceClient
    except ImportError:
        say("python", "The databricks-sdk package is missing.", "err")
        print("\n  Install it, then run this again:")
        print("    pip install databricks-sdk\n")
        return 1

    w = WorkspaceClient(profile=a.profile) if a.profile else WorkspaceClient()
    host = (w.config.host or "").rstrip("/")
    try:
        me = w.current_user.me().user_name
    except Exception as e:
        say("auth", f"Cannot reach the workspace. {str(e)[:110]}", "err")
        print("\n  Run: databricks auth login\n")
        return 1
    say("workspace", host)
    say("as", me)

    # 1. the app itself
    existing = {app.name for app in w.apps.list()}
    if APP in existing:
        say("app", f"'{APP}' already exists, reusing it", "ok")
    else:
        say("app", "creating, this provisions compute and takes a few minutes")
        rc, out = cli("apps", "create", APP, profile=a.profile)
        if rc != 0 and "already exists" not in out:
            say("app", out[-220:], "err")
            return 1
        say("app", "created", "ok")

    # 2. the code
    target = f"/Workspace/Users/{me}/{APP}-app"
    say("code", f"uploading to {target}")
    rc, out = cli("sync", str(HERE / "app"), target, "--full", profile=a.profile)
    if rc != 0:
        say("code", out[-220:], "err")
        return 1
    say("code", "deploying and starting")
    rc, out = cli("apps", "deploy", APP, "--source-code-path", target, profile=a.profile)
    if rc != 0:
        say("code", out[-220:], "err")
        return 1
    say("code", "running", "ok")

    # 3. the identity, and the two rights that let the app fix things itself
    sp = None
    for _ in range(30):
        try:
            sp = w.apps.get(APP).service_principal_client_id
        except Exception:
            sp = None
        if sp:
            break
        time.sleep(4)
    if not sp:
        say("identity", "the app has no service principal yet, run this again shortly", "warn")
        return 0
    say("identity", sp)

    from databricks.sdk.service import iam
    rec = next((s for s in w.service_principals.list() if s.application_id == sp), None)
    if rec and "allow-cluster-create" in {e.value for e in (rec.entitlements or [])}:
        say("rights", "cluster creation already granted", "ok")
    elif rec:
        try:
            w.service_principals.patch(
                rec.id,
                operations=[iam.Patch(op=iam.PatchOp.ADD, path="entitlements",
                                      value=[{"value": "allow-cluster-create"}])],
                schemas=[iam.PatchSchema.URN_IETF_PARAMS_SCIM_API_MESSAGES_2_0_PATCH_OP])
            say("rights", "granted cluster creation", "ok")
        except Exception as e:
            say("rights", f"could not grant cluster creation. {str(e)[:100]}", "warn")

    from databricks.sdk.service.catalog import PermissionsChange, Privilege
    try:
        w.grants.update(securable_type="catalog", full_name=a.catalog,
                        changes=[PermissionsChange(
                            principal=sp,
                            add=[Privilege.USE_CATALOG, Privilege.CREATE_SCHEMA])])
        say("rights", f"granted catalog access on {a.catalog}", "ok")
    except Exception as e:
        say("rights", f"could not grant catalog access. {str(e)[:100]}", "warn")
        print(f"\n  A metastore admin can run this in any SQL editor:")
        print(f"    GRANT USE CATALOG, CREATE SCHEMA ON CATALOG {a.catalog} TO `{sp}`")

    url = ""
    try:
        url = w.apps.get(APP).url or ""
    except Exception:
        pass

    print(f"\n{GREEN}{BOLD}  Installed.{OFF}\n")
    if url:
        print(f"  {BOLD}{url}{OFF}\n")
    print("  Open it, press Set up this workspace, then fill in the customer")
    print("  and industry and press Go.\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  cancelled\n")
        sys.exit(130)
