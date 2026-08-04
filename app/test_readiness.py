#!/usr/bin/env python3
"""Force every readiness check to fail, and prove it reports the failure.

A check that cannot fail is decoration. For each one this injects the real
failure condition, then asserts the check goes red, stays isolated from its
neighbours, and offers a remedy the app can actually act on.
"""
import os
import sys

os.environ.setdefault("DOCFLOW_WAREHOUSE_ID", "76e7816e53118f52")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import appconfig  # noqa: E402
import pipeline  # noqa: E402


class Boom:
    """Stands in for a workspace client whose calls deny or disappear."""
    def __init__(self, fail: set, names=None, cats=None, sysstate="ENABLE_COMPLETED"):
        self.fail, self._names = fail, names
        self._cats = ["workspace"] if cats is None else cats
        self._sysstate = sysstate

    def _maybe(self, key):
        if key in self.fail:
            raise PermissionError(f"PERMISSION_DENIED: simulated {key} failure")

    # -- surfaces readiness touches
    @property
    def config(self):
        return type("C", (), {"host": "https://example.cloud.databricks.com"})()

    @property
    def current_user(self):
        outer = self
        class U:
            def me(self):
                outer._maybe("identity")
                return type("M", (), {"user_name": "app-sp@example"})()
        return U()

    @property
    def warehouses(self):
        outer = self
        class W:
            def list(self):
                outer._maybe("warehouse_list")
                if "warehouse_none" in outer.fail:
                    return []
                return [type("X", (), {"id": "w1", "name": "DocFlow Serverless",
                                       "enable_serverless_compute": True,
                                       "state": type("S", (), {"value": "STOPPED"})()})()]
        return W()

    @property
    def catalogs(self):
        outer = self
        class C:
            def list(self):
                outer._maybe("catalog_list")
                return [type("K", (), {"name": n})() for n in outer._cats]
        return C()

    @property
    def schemas(self):
        outer = self
        class S:
            def list(self, catalog_name=None):
                outer._maybe("schema_list")
                if "schema_missing" in outer.fail:
                    return []
                return [type("S", (), {"name": "docflow"})()]
        return S()

    @property
    def files(self):
        outer = self
        class F:
            def get_directory_metadata(self, p):
                outer._maybe("volume")
        return F()

    @property
    def serving_endpoints(self):
        outer = self
        class E:
            def list(self):
                outer._maybe("endpoints_list")
                names = outer._names if outer._names is not None else [
                    "databricks-claude-sonnet-4-6", "ka-abc-endpoint"]
                return [type("E", (), {"name": n})() for n in names]
        return E()

    @property
    def metastores(self):
        outer = self
        class M:
            def current(self):
                outer._maybe("metastore")
                return type("MS", (), {"metastore_id": "ms1"})()
        return M()

    @property
    def system_schemas(self):
        outer = self
        class S:
            def list(self, mid):
                outer._maybe("sysschema")
                return [type("S", (), {"schema": "billing",
                                       "state": type("St", (), {"value": outer._sysstate})()})()]
        return S()


def run(label, *, fail=None, names=None, cats=None, sysstate="ENABLE_COMPLETED",
        sql_raises=False, expect_red, expect_fix=None):
    """Inject one failure, then assert exactly that check goes red."""
    appconfig.pipeline.wc = lambda: Boom(fail or set(), names, cats, sysstate)
    appconfig.pipeline._MODEL.update({"name": "", "note": "", "tried": 0})
    if sql_raises:
        appconfig.pipeline.sql = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("UNSUPPORTED: ai_classify is not available in this region"))
    else:
        appconfig.pipeline.sql = lambda *a, **k: [["invoice"]]

    r = appconfig.readiness(deep=True)
    by = {c["key"]: c for c in r["checks"]}
    got = by.get(expect_red)

    problems = []
    if got is None:
        problems.append(f"check '{expect_red}' vanished from the list")
    elif got["ok"]:
        problems.append(f"'{expect_red}' stayed green under its own failure")
    if len(by) != 12:
        problems.append(f"emitted {len(by)} checks, expected 12 (a failure hid its neighbours)")
    if expect_fix and got and got.get("fix_endpoint") != expect_fix:
        problems.append(f"remedy was {got.get('fix_endpoint')}, expected {expect_fix}")
    if got and not got["ok"] and not got.get("auto") and not (
            got.get("fix_endpoint") or got.get("steps") or got.get("human_action")):
        problems.append("failed with no remedy offered")

    ok = not problems
    mark = "PASS" if ok else "FAIL"
    remedy = (got or {}).get("fix_endpoint") or (
        "steps" if (got or {}).get("steps") else "text")
    print(f"  [{mark}] {label:38s} red={expect_red:20s} remedy={remedy}")
    for p in problems:
        print(f"         -> {p}")
    return ok


print("forcing each readiness check to fail\n")
results = [
    run("identity denied", fail={"identity"}, expect_red="identity"),
    run("no serverless warehouse", fail={"warehouse_none"}, expect_red="warehouse",
        expect_fix="/api/fix/warehouse"),
    run("cannot list warehouses", fail={"warehouse_list"}, expect_red="warehouse"),
    run("target catalog absent", cats=["samples"], expect_red="catalog",
        expect_fix="/api/fix/catalog"),
    run("catalog there, schema absent", fail={"schema_missing"}, expect_red="catalog",
        expect_fix="/api/fix/catalog"),
    run("no privilege to list schemas", fail={"schema_list"}, expect_red="catalog"),
    run("volume unreachable", fail={"volume"}, expect_red="volume",
        expect_fix="/api/bootstrap"),
    run("no model answers a probe", sql_raises=True, expect_red="endpoints",
        expect_fix="/api/fix/models"),
    run("assistant absent", names=["databricks-gpt"], expect_red="knowledge_assistant"),
    run("AI Functions unavailable", sql_raises=True, expect_red="ai_functions"),
    run("billing schema not enabled", sysstate="DISABLE_INITIALIZED",
        expect_red="billing_schema", expect_fix="/api/fix/billing"),
    run("system schema unreadable", fail={"sysschema"}, expect_red="billing_schema"),
]

# Free Edition regression: no databricks-* endpoints visible, yet a model
# answers under a gateway name. The check must pass on the probe, and the two
# agent rows must present as built-at-go rather than as user tasks.
appconfig.pipeline.wc = lambda: Boom(set(), [], None, "ENABLE_COMPLETED")
appconfig.pipeline._MODEL.update({"name": "", "note": "", "tried": 0})
appconfig.pipeline.sql = lambda *a, **k: [["OK"]]
_r = appconfig.readiness(deep=True)
_by = {c["key"]: c for c in _r["checks"]}
_probs = []
if not _by["endpoints"]["ok"]:
    _probs.append("endpoints red although a model answered the probe")
# The two API-creatable bricks are built for you; IE is the only Agent Bricks
# type with no create API, so it stays a user action with a link, not a chore
# the app pretends it can do.
# The assistant is built over the API; classification and extraction are SQL
# functions the run calls directly. None of the three is a user chore.
for _k in ("knowledge_assistant", "classification", "extraction"):
    if not _by[_k].get("auto"):
        _probs.append(f"{_k} is not marked auto")
    if _by[_k].get("fix_endpoint"):
        _probs.append(f"{_k} still advertises a fix button")
if not (_by["classification"]["ok"] and _by["extraction"]["ok"]):
    _probs.append("SQL capabilities should never read as missing")
print(f"\n  [{'PASS' if not _probs else 'FAIL'}] gateway workspace: probe green, agents auto")
for _p in _probs:
    print(f"         -> {_p}")
results.append(not _probs)

# every fix endpoint the checks advertise must exist in the API
import app as fastapi_app  # noqa: E402
routes = {getattr(r, "path", "") for r in fastapi_app.app.routes}
appconfig.pipeline.wc = lambda: Boom(set())
appconfig.pipeline.sql = lambda *a, **k: [["invoice"]]
advertised = {c["fix_endpoint"] for c in appconfig.readiness()["checks"] if c["fix_endpoint"]}
dead = sorted(advertised - routes)
print(f"\n  [{'PASS' if not dead else 'FAIL'}] every advertised fix endpoint exists"
      f"{'' if not dead else ' -> dead: ' + ', '.join(dead)}")
results.append(not dead)

# a fully healthy workspace must go green and be runnable
appconfig.pipeline.wc = lambda: Boom(set())
r = appconfig.readiness(deep=True)
healthy = r["ready_to_configure"] and all(
    c["ok"] for c in r["checks"] if c["key"] in appconfig.REQUIRED)
print(f"  [{'PASS' if healthy else 'FAIL'}] healthy workspace reports ready "
      f"(required all green: {healthy})")
results.append(healthy)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
