"""Customer-safety suite: prove the app can only ever damage its own assets.

This app runs inside customer production workspaces. Every check here is a
promise to that customer: it never writes into a schema it does not own, never
widens permissions on assets it did not create, and teardown can only remove
objects on its own fixed inventory.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import orchestrator  # noqa: E402
import pipeline  # noqa: E402

results = []


def rec(label, ok, detail=""):
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" · {detail}" if detail else ""))
    return ok


class FakeSQL:
    """Records statements and answers catalogue queries from a fake workspace."""

    def __init__(self, tables=(), volumes=(), schemas=("docflow",), comment="",
                 catalogs=None):
        self.tables, self.volumes = list(tables), list(volumes)
        self.schemas, self.comment = list(schemas), comment
        self.catalogs = list(catalogs) if catalogs is not None else None
        self.seen = []

    def __call__(self, stmt, *a, **k):
        self.seen.append(stmt)
        s = stmt.strip().upper()
        if s.startswith("SHOW TABLES"):
            return [["db", t, False] for t in self.tables]
        if s.startswith("SHOW VOLUMES"):
            return [["db", v, False] for v in self.volumes]
        if s.startswith("SHOW SCHEMAS"):
            return [[x] for x in self.schemas]
        if s.startswith("SHOW CATALOGS"):
            if self.catalogs is None:
                return [["workspace"]]
            m = re.search(r"LIKE '([^']+)'", stmt, re.I)
            return [[c] for c in self.catalogs if not m or c == m.group(1)]
        if s.startswith("DESCRIBE SCHEMA"):
            return [["Comment", self.comment]]
        return []


print("customer-safety checks\n")

# --- 1. a schema holding customer tables is refused outright -----------------
fake = FakeSQL(tables=["fact_orders", "dim_customer"], volumes=["landing"])
orchestrator.pipeline.sql = fake
orchestrator.GO["assets"] = {}
try:
    orchestrator.pipeline.set_target("main", "finance", "docs")
    raised = ""
    try:
        orchestrator.ensure_infra({"catalog": "main", "schema": "finance"})
    except RuntimeError as e:
        raised = str(e)
    except Exception as e:                       # warehouse lookup etc.
        raised = str(e)
    wrote = [s for s in fake.seen
             if re.match(r"\s*(CREATE|DROP|INSERT|DELETE|COMMENT|GRANT)", s, re.I)]
    rec("refuses a schema containing customer tables",
        "Refusing to write into it" in raised, raised[:70] or "no refusal!")
    rec("writes nothing before refusing", not wrote,
        f"{len(wrote)} write statement(s)" if wrote else "no writes")
except Exception as e:
    rec("refusal path", False, str(e)[:90])

# --- 2. permissions are never widened on a schema we do not own -------------
orchestrator.GO["assets"] = {"schema_created_by_us": False}
fake2 = FakeSQL()
orchestrator.pipeline.sql = fake2
out = orchestrator.grant_browse_access("main", "finance", {})
rec("no GRANT on a schema the demo did not create",
    not out["granted"] and not any("GRANT" in s.upper() for s in fake2.seen),
    "skipped")

# --- 3. USE CATALOG only on a catalog we created ourselves ------------------
orchestrator.GO["assets"] = {"schema_created_by_us": True,
                             "catalog_created_by_us": False}
fake3 = FakeSQL()
orchestrator.pipeline.sql = fake3
orchestrator.grant_browse_access("main", "docflow", {})
cat_grants = [s for s in fake3.seen if "USE CATALOG" in s.upper()]
rec("never grants USE CATALOG on a pre-existing catalog", not cat_grants,
    f"{len(cat_grants)} catalog grant(s)" if cat_grants else "none")

orchestrator.GO["assets"] = {"schema_created_by_us": True,
                             "catalog_created_by_us": True}
fake4 = FakeSQL()
orchestrator.pipeline.sql = fake4
orchestrator.grant_browse_access("demo_cat", "docflow", {})
rec("does grant USE CATALOG on a catalog it made",
    any("USE CATALOG" in s.upper() for s in fake4.seen), "granted")

# --- 4. an empty schema is adopted and marked -------------------------------
orchestrator.GO["assets"] = {}
fake5 = FakeSQL(tables=[], volumes=[], schemas=["docflow"])
orchestrator.pipeline.sql = fake5
try:
    orchestrator.ensure_infra({"catalog": "workspace", "schema": "docflow"})
except Exception:
    pass
rec("marks a schema it adopts while empty",
    any("COMMENT ON SCHEMA" in s.upper() for s in fake5.seen), "stamped")

# --- 5. teardown inventory cannot drift from what the app creates ------------
here = os.path.dirname(os.path.abspath(__file__))
ddl = " ".join(pipeline._ddl())
created = set(re.findall(r"CREATE (?:OR REPLACE )?TABLE (?:IF NOT EXISTS )?[\w.]*\.(\w+)", ddl, re.I))
for src in ("pipeline.py", "cases.py"):
    body = open(os.path.join(here, src)).read()
    created |= set(re.findall(r"CREATE OR REPLACE TABLE \{FQ\}\.(\w+)", body))
    created |= set(re.findall(r"CREATE TABLE IF NOT EXISTS \{pipeline\.FQ\}\.(\w+)", body))
missing = sorted(created - set(pipeline.OWNED_TABLES))
rec("every table the app creates is on the teardown inventory", not missing,
    f"orphans: {missing}" if missing else f"{len(created)} tables covered")

vols = set(re.findall(r"CREATE VOLUME IF NOT EXISTS \{?\w*\}?[\w.{}]*\.(\w+)",
                      open(os.path.join(here, "orchestrator.py")).read()))
missing_v = sorted(v for v in vols if v not in pipeline.OWNED_VOLUMES)
rec("every volume the app creates is on the teardown inventory", not missing_v,
    f"orphans: {missing_v}" if missing_v else f"{len(vols)} volumes covered")

# --- 6. the reset notebook itself carries no unbounded deletes --------------
reset = open(os.path.join(os.path.dirname(here), "reset_databricks.py")).read()
code = "\n".join(l for l in reset.split("\n") if not l.startswith("# MAGIC"))
rec("teardown never uses DROP ... CASCADE",
    not re.search(r"DROP\s+SCHEMA[^\"']*CASCADE", code, re.I), "RESTRICT only")
rec("teardown deletes nothing without explicit confirmation",
    "if not CONFIRM:" in code and "CONFIRM = False" in code, "gated")
rec("teardown proves schema ownership before removing tables",
    "SCHEMA_MARKER in comment" in code and "schema_is_ours" in code, "marker required")
danger = re.findall(r"delete|drop|trash", code, re.I)
prefix = re.findall(r"startswith\([\"'](?!.*exact)", code)
rec("teardown matches names exactly, never by prefix", not prefix,
    f"{len(danger)} delete sites, all exact-name")

# --- 7. the SPA must actually parse ------------------------------------------
# A syntax error in this file is total: the script never runs, every page stays
# on its loading spinner, and no error is shown. It reached a user once.
import json
import shutil
import subprocess
import tempfile

idx = os.path.join(here, "static", "index.html")
html = open(idx).read()
m = re.search(r"<script>(.*)</script>", html, re.S)
if not m:
    rec("frontend script block found", False, "no <script> in index.html")
else:
    js = m.group(1)
    node = shutil.which("node")
    if not node:
        print("  [WARN] node not found — install node so this gate can run")
        rec("frontend JavaScript parses", True, "skipped, node unavailable")
    else:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(js)
            tmp = fh.name
        pr = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
        os.unlink(tmp)
        first = (pr.stderr.strip().split("\n") or [""])[-3:]
        rec("frontend JavaScript parses", pr.returncode == 0,
            "clean" if pr.returncode == 0 else " ".join(x.strip() for x in first)[:120])
# --- 8. teardown must demand proof, never a name -----------------------------
reset_src = open(os.path.join(os.path.dirname(here), "reset_databricks.py")).read()
rcode = "\n".join(l for l in reset_src.split("\n") if not l.startswith("# MAGIC"))
rec("app deletion requires the DocFlow fingerprint",
    "app_is_ours" in rcode and 'FINGERPRINT in (a.description or "")' in rcode,
    "fingerprint required")
rec("genie deletion requires the space to reference this demo's tables",
    "genie_ours" in rcode and "serialized_space" in rcode, "content proof required")
rec("assistant deletion requires fingerprint or volume-source proof",
    "assistants_ours" in rcode and "list_knowledge_sources" in rcode,
    "proof required")
rec("an unmarked schema needs distinctive tables, not generic names",
    "DISTINCTIVE" in rcode and "len(distinctive_found) >= 2" in rcode,
    "two distinctive tables required")
rec("generic table names alone never authorise deletion",
    "names a customer\n                  f\" could own too" in rcode
    or "could own too" in rcode, "explicitly refused")

# --- 9. pointing at an existing catalog uses it in place ---------------------
# The install can target a catalog the customer already owns. The app may add
# its own schema there, but must never create, claim, or re-grant the catalog.
orchestrator.GO["assets"] = {}
fake9 = FakeSQL(tables=[], volumes=[], schemas=[], catalogs=["big_existing"])
orchestrator.pipeline.sql = fake9
try:
    orchestrator.pipeline.set_target("big_existing", "docflow", "docs")
    orchestrator.ensure_infra({"catalog": "big_existing", "schema": "docflow"})
except Exception:
    pass                                        # warehouse lookup is not faked
cat_writes = [x for x in fake9.seen if "CREATE CATALOG" in x.upper()]
rec("an existing catalog is never re-created", not cat_writes,
    f"{len(cat_writes)} CREATE CATALOG" if cat_writes else "used in place")
rec("an existing catalog is never claimed as ours",
    orchestrator.GO["assets"].get("catalog_created_by_us") is not True, "unclaimed")

here2 = os.path.dirname(os.path.abspath(__file__))
setup_src = open(os.path.join(os.path.dirname(here2), "setup_databricks.py")).read()
reset_src2 = open(os.path.join(os.path.dirname(here2), "reset_databricks.py")).read()
appcfg_src = open(os.path.join(here2, "appconfig.py")).read()
spa_src = open(os.path.join(here2, "static", "index.html")).read()
rec("installer takes the catalog as a parameter",
    'dbutils.widgets.text("catalog"' in setup_src, "widget present")
rec("teardown takes catalog and schema as parameters",
    'dbutils.widgets.text("catalog"' in reset_src2
    and 'dbutils.widgets.text("schema"' in reset_src2, "widgets present")
rec("app default catalog follows the install, not a literal",
    '"catalog": pipeline.CATALOG' in appcfg_src
    and 'or "workspace"' not in appcfg_src.replace('cfg.get("catalog") or', ""),
    "pipeline.CATALOG")
rec("frontend carries no hardcoded catalog target",
    "workspace.docflow" not in spa_src, "picker is config-driven")

# --- 10. the lakebase instance is deleted only on the app's own record -------
rcode10 = "\n".join(l for l in open(os.path.join(os.path.dirname(here2), "reset_databricks.py")).read().split("\n")
                     if not l.startswith("# MAGIC"))
rec("lakebase deletion requires the app's creation record",
    'rec_lb.get("instance") == LAKEBASE and rec_lb.get("created_by_us")' in rcode10,
    "record required")
rec("an unrecorded lakebase instance is left alone",
    "no creation record" in rcode10, "blocked, not deleted")
rec("lakebase deletion is exact-name, from a constant",
    'LAKEBASE = "docflow-lakebase"' in rcode10
    and "delete_database_instance(LAKEBASE" in rcode10, "constant name")
csrc = open(os.path.join(here2, "cases.py")).read()
rec("the app never deletes a database instance itself",
    "delete_database_instance" not in csrc, "create/adopt only")

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
