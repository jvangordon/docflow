#!/usr/bin/env python3
"""L2 fail-and-repair against the real workspace.

Each scenario breaks a prerequisite for real, asserts the app reports it red
with the right remedy, applies the remedy, and asserts it goes green again.
Everything is restored afterwards.
"""
import os
import sys
import time

os.environ["DOCFLOW_WAREHOUSE_ID"] = ""
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import appconfig  # noqa: E402
import pipeline  # noqa: E402

pipeline.set_target("workspace", "docflow")
W = pipeline.wc()
results = []


def check(key, deep=False):
    return {c["key"]: c for c in appconfig.readiness(deep=deep)["checks"]}[key]


def record(name, ok, note=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{' · ' + note if note else ''}")


def banner(t):
    print(f"\n=== {t} ===")


# ---------------------------------------------------------------- 2.5 volume
banner("2.5 document volume deleted and repaired")
try:
    W.volumes.delete("workspace.docflow.docs")
    print("  deleted volume workspace.docflow.docs")
    time.sleep(2)
    c = check("volume")
    record("volume goes red when deleted", not c["ok"], c["detail"][:60])
    record("volume offers a remedy", bool(c["fix_endpoint"]), c["fix_endpoint"] or "none")
    boot = pipeline.bootstrap()
    time.sleep(2)
    c2 = check("volume")
    record("volume repaired by the app", c2["ok"],
           f"{boot['statements']} statements, {len(boot['errors'])} errors")
except Exception as e:
    record("volume scenario ran", False, str(e)[:110])

# ---------------------------------------------------------------- 2.3 schema
banner("2.3 schema missing, catalog present")
try:
    appconfig.save_config({"catalog": "workspace", "schema": "docflow_missing"})
    c = check("catalog")
    record("schema-missing goes red", not c["ok"], c["detail"][:70])
    record("offers the catalog remedy", c["fix_endpoint"] == "/api/fix/catalog")
    out = appconfig.fix_catalog()
    c2 = check("catalog")
    record("schema created by the app", c2["ok"], str(out.get("created"))[:60])
    pipeline.sql("DROP SCHEMA IF EXISTS workspace.docflow_missing CASCADE")
    print("  cleaned up docflow_missing")
except Exception as e:
    record("schema scenario ran", False, str(e)[:110])
finally:
    appconfig.save_config({"catalog": "workspace", "schema": "docflow"})
    pipeline.set_target("workspace", "docflow")

# ---------------------------------------------------------------- 2.7 assistant
banner("2.7 Knowledge Assistant deleted and recreated by the app")
try:
    from databricks.sdk.service import knowledgeassistants as K
    before = [e.name for e in W.serving_endpoints.list() if e.name.startswith("ka-")]
    print("  assistant endpoints before:", before)
    removed = 0
    for ka in W.knowledge_assistants.list_knowledge_assistants():
        if (ka.display_name or "") == "docflow-ka":
            W.knowledge_assistants.delete_knowledge_assistant(ka.name)
            removed += 1
    print(f"  deleted {removed} assistant(s)")
    time.sleep(8)
    c = check("knowledge_assistant")
    record("assistant goes red when absent", not c["ok"], c["detail"][:60])
    record("assistant offers create button", c["fix_endpoint"] == "/api/fix/assistant")
    res = appconfig.fix_assistant()
    time.sleep(5)
    c2 = check("knowledge_assistant")
    record("assistant recreated by the app", c2["ok"] or bool(res.get("state", {}).get("endpoint")),
           str(res.get("state", {}).get("endpoint"))[:40])
except Exception as e:
    record("assistant scenario ran", False, str(e)[:110])

# ---------------------------------------------------------------- 1.6 ask fallback
banner("1.6 ask falls back to governed SQL when Genie is unavailable")
try:
    import orchestrator
    real_list = W.genie.list_spaces
    orchestrator.GO["assets"].pop("genie_space_id", None)

    class NoSpaces:
        spaces = []
    W.genie.list_spaces = lambda: NoSpaces()
    r = orchestrator.ask("How many warranty claims are outside their coverage window?")
    W.genie.list_spaces = real_list
    record("falls back rather than erroring", not r.get("error"), f"engine={r.get('engine')}")
    record("fallback is labelled honestly", r.get("engine") == "sql", str(r.get("rows"))[:40])
except Exception as e:
    record("ask fallback ran", False, str(e)[:110])

# ---------------------------------------------------------------- 6.3 customer files
banner("6.3 customer documents are read, never modified")
try:
    src = "/Volumes/samples/sec/contracts"
    files = [f for f in W.files.list_directory_contents(src)][:3]
    sizes_before = {f.name: f.file_size for f in files}
    print("  sample customer volume:", src, "->", list(sizes_before)[:3])
    appconfig.save_config({"customer_volume": src})
    cfgv = appconfig.load_config().get("customer_volume")
    record("customer volume persists in config", cfgv == src, cfgv or "")
    sizes_after = {f.name: f.file_size
                   for f in W.files.list_directory_contents(src) if f.name in sizes_before}
    record("source files unchanged after config", sizes_after == sizes_before,
           f"{len(sizes_after)} files compared")
except Exception as e:
    record("customer file scenario ran", False, str(e)[:110])
finally:
    appconfig.save_config({"customer_volume": ""})

print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
for n, ok in results:
    if not ok:
        print("  FAILED:", n)
sys.exit(0 if all(ok for _, ok in results) else 1)
