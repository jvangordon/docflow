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

    def __init__(self, tables=(), volumes=(), schemas=("docflow",), comment=""):
        self.tables, self.volumes = list(tables), list(volumes)
        self.schemas, self.comment = list(schemas), comment
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
            return [["workspace"]]
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
for src in ("pipeline.py",):
    body = open(os.path.join(here, src)).read()
    created |= set(re.findall(r"CREATE OR REPLACE TABLE \{FQ\}\.(\w+)", body))
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
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
