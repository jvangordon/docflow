"""Run the entire prepare stage against a fake workspace.

The reported failure — a green log that simply stopped after Company research —
was invisible to every existing suite, because nothing exercised go() end to
end. This does: warehouse, schema, model, assistants, research, 24 documents,
source attach, examples. It must reach phase 'prepared' with no exception and
no missing step.
"""
import io
import json
import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import appconfig  # noqa: E402
import orchestrator  # noqa: E402
import pipeline  # noqa: E402

results = []


def rec(label, ok, detail=""):
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" · {detail}" if detail else ""))


# ----------------------------------------------------------------- fake SDK
class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeFiles:
    def __init__(self):
        self.written, self.dirs = {}, set()

    def create_directory(self, path):
        self.dirs.add(path)

    def upload(self, path, body, overwrite=False):
        data = body.read() if hasattr(body, "read") else bytes(body)
        if not data:
            raise RuntimeError(f"refused empty upload to {path}")
        self.written[path] = data

    def download(self, path):
        if path not in self.written:
            raise RuntimeError(f"not found: {path}")
        return Obj(contents=io.BytesIO(self.written[path]))

    def list_directory_contents(self, path):
        return []

    def get_directory_metadata(self, path):
        return Obj()


class FakeDatabase:
    def __init__(self):
        self.made = []

    def list_database_instances(self):
        return [Obj(as_dict=lambda n=n: {"name": n, "state": "AVAILABLE",
                                         "read_write_dns": "fake.host"})
                for n in self.made]

    def create_database_instance(self, inst):
        self.made.append(inst.name)


class FakeKA:
    def __init__(self):
        self.made, self.sources, self.examples = {}, {}, {}

    def list_knowledge_assistants(self):
        return list(self.made.values())

    def create_knowledge_assistant(self, ka):
        n = f"knowledge-assistants/{len(self.made) + 1}"
        obj = Obj(name=n, display_name=ka.display_name,
                  description=getattr(ka, "description", ""),
                  endpoint_name=f"ka-{len(self.made) + 1}-endpoint", state=None)
        self.made[ka.display_name] = obj
        return obj

    def sync_knowledge_sources(self, parent):
        self.synced = getattr(self, "synced", [])
        self.synced.append(parent)

    def list_knowledge_sources(self, parent):
        return self.sources.get(parent, [])

    def create_knowledge_source(self, parent, src):
        self.sources.setdefault(parent, []).append(
            Obj(state="UPDATED", files=getattr(src, "files", None)))
        return self.sources[parent][-1]

    def list_examples(self, parent):
        return self.examples.get(parent, [])

    def create_example(self, parent, ex):
        self.examples.setdefault(parent, []).append(ex)
        return ex


class FakeGenie:
    def __init__(self):
        self.spaces = []

    def list_spaces(self):
        return Obj(spaces=list(self.spaces))

    def create_space(self, warehouse_id=None, serialized_space=None, title=None):
        sp = Obj(space_id=f"sp{len(self.spaces) + 1}", title=title,
                 description="", serialized_space=serialized_space)
        self.spaces.append(sp)
        return sp

    def update_space(self, sid, serialized_space=None, warehouse_id=None):
        return Obj(space_id=sid)

    def get_space(self, sid):
        return next((s for s in self.spaces if s.space_id == sid), Obj(serialized_space=""))


class FakeW:
    def __init__(self):
        self.files = FakeFiles()
        self.knowledge_assistants = FakeKA()
        self.database = FakeDatabase()
        self.genie = FakeGenie()
        self.warehouses = Obj(list=lambda: [
            Obj(id="wh1", name="Serverless Starter Warehouse",
                enable_serverless_compute=True, state=Obj(value="RUNNING"))])
        self.catalogs = Obj(list=lambda: [Obj(name="workspace")])
        self.schemas = Obj(list=lambda c: [], get=lambda f: Obj(comment=""))
        self.serving_endpoints = Obj(list=lambda: [
            Obj(name="databricks-claude-sonnet-4-6")])
        self.registered_models = Obj(list=lambda **k: [])
        self.current_user = Obj(me=lambda: Obj(user_name="sa@example.com"))
        self.config = Obj(host="https://example.cloud.databricks.com")
        self.apps = Obj(list=lambda: [])
        self.grants = Obj(update=lambda **k: None)


THEME = {
    "tagline": "Every claim, one governed answer away",
    "vocabulary": ["warranty recovery", "supplier chargeback"],
    "genie_questions": ["What is the total of claims outside their window?"],
    "assistant_questions": ["What does the contract say about the penalty?"],
    "claims_page_title": "Warranty Recovery Desk",
    "suppliers_page_title": "Supplier Accountability",
    "world": {"site": "Riverton Plant", "vendors": ["Apex Supply"],
              "line_items": ["valve"], "carriers": ["FastFreight"],
              "destinations": ["Depot 4"],
              "type_labels": {"warranty_claim": "Equipment Failure Claim"},
              "contract": {"supplier": "Apex Supply", "penalty_pct": "2%",
                           "cap_pct": "10%", "warranty_months": "24",
                           "filing_days": "30"},
              "narratives": {"component_names": ["Pump seal"],
                             "claim_failures": ["Seal failed under load."]}},
    "story": [{"page": "flow", "line": "Documents route themselves.", "cue": "press Process"}],
}


def fake_sql(stmt, *a, **k):
    s = stmt.strip().upper()
    if s.startswith("SHOW CATALOGS"):
        return [["workspace"]]
    if s.startswith("SHOW SCHEMAS"):
        return []                      # schema absent -> app creates it
    if s.startswith("SHOW TABLES") or s.startswith("SHOW VOLUMES"):
        return []
    if s.startswith("DESCRIBE SCHEMA"):
        return [["Comment", ""]]
    if "AI_QUERY" in s and "RESPONSEFORMAT" in s:
        return [[json.dumps(THEME)]]   # research call
    if "AI_QUERY" in s:
        return [["OK"]]                # model probe
    return []


print("full prepare-stage run against a fake workspace\n")

fakew = FakeW()
pipeline._w = fakew
pipeline.wc = lambda: fakew
pipeline.sql = fake_sql
orchestrator.pipeline.sql = fake_sql
appconfig.save_config = lambda patch: patch
appconfig.load_config = lambda: {"company": "Acme Corp", "industry": "Manufacturing",
                                 "catalog": "workspace", "schema": "docflow"}
pipeline._MODEL.update({"name": "", "note": "", "tried": 0, "asked": ""})
orchestrator.GO.update({"phase": "idle", "steps": [], "sections": {}, "assets": {},
                        "theme": {}, "started": 0.0, "finished": 0.0, "error": ""})
orchestrator._persist = lambda: None

t0 = time.time()
try:
    orchestrator.go({"company": "Acme Corp", "industry": "Manufacturing",
                     "catalog": "workspace", "schema": "docflow"}, stage="prepare")
    crashed = ""
except Exception as e:
    crashed = f"{type(e).__name__}: {e}"

steps = orchestrator.GO["steps"]
names = [s["name"] for s in steps]
errs = [s for s in steps if s["status"] == "err"]

orchestrator.GO["_sources_at_prepare"] = len(
    getattr(fakew.knowledge_assistants, "sources", {}) or {})
rec("prepare completes without raising", not crashed, crashed or f"{time.time()-t0:.1f}s")
rec("reaches phase 'prepared'", orchestrator.GO["phase"] == "prepared",
    orchestrator.GO["phase"] + (f" · {orchestrator.GO.get('error','')[:80]}" if orchestrator.GO.get("error") else ""))
rec("no step reports an error", not errs,
    "; ".join(f"{e['name']}: {e['detail'][:70]}" for e in errs) or "clean")

for want in ("Serverless warehouse", "Language model", "Company research",
             "Generated documents"):
    rec(f"step ran: {want}", any(want in n for n in names),
        "" if any(want in n for n in names) else f"missing · saw {names}")

pdfs = [p for p in fakew.files.written if p.endswith(".pdf")]
inbox = [p for p in pdfs if "/inbox/" in p]
scoped = [p for p in pdfs if "/ka_contracts/" in p or "/ka_claims/" in p]
rec("24 documents reached the inbox", len(inbox) == 24, f"{len(inbox)} files")
rec("nothing was pre-sorted into assistant folders at prepare", len(scoped) == 0,
    f"{len(scoped)} pre-sorted — routing belongs to the classifier, not setup")

# --- act two: the classifier's verdicts drive the copies -------------------
inbox_files = sorted(os.path.basename(p) for p in inbox)
contract_f, claim_f, hr_f = inbox_files[0], inbox_files[1], inbox_files[2]
with orchestrator.pipeline._lock:
    orchestrator.pipeline.STATE.docs = {
        "d1": {"filename": contract_f, "lane": "ka", "doc_type": "supplier_contract"},
        "d2": {"filename": claim_f, "lane": "ie_ka", "doc_type": "warranty_claim"},
        "d3": {"filename": hr_f, "lane": "secure", "doc_type": "hr_record"},
    }
orchestrator.route_to_assistants()
routed = {p for p in fakew.files.written if "/ka_contracts/" in p or "/ka_claims/" in p}
rec("classifier verdicts routed documents to their assistants",
    any(contract_f in p and "/ka_contracts/" in p for p in routed)
    and any(claim_f in p and "/ka_claims/" in p for p in routed),
    f"{len(routed)} routed by label")
rec("secure-lane documents never reach an assistant folder",
    not any(hr_f in p for p in routed), "HR file stayed out")
rec("sources attach in act two, never over empty folders",
    len(getattr(fakew.knowledge_assistants, "sources", {}) or {}) > 0
    and not orchestrator.GO.get("_sources_at_prepare"),
    "attached after routing")
rec("assistants were told their documents changed",
    len(getattr(fakew.knowledge_assistants, "synced", [])) >= 1,
    f"{len(getattr(fakew.knowledge_assistants, 'synced', []))} sync calls")
rec("assistants were created", len(fakew.knowledge_assistants.made) == 2,
    f"{len(fakew.knowledge_assistants.made)} made")
lb = orchestrator.GO["assets"].get("lakebase") or {}
rec("lakebase instance created and recorded for teardown",
    "docflow-lakebase" in fakew.database.made
    and lb.get("instance") == "docflow-lakebase" and lb.get("created_by_us") is True,
    f"made={fakew.database.made} recorded={lb}")
# The research world must actually reach the rendered PDFs, not just the theme.
try:
    from test_corpus import pdf_text
    hit = False
    for v in fakew.files.written.values():
        if v[:4] != b"%PDF":
            continue
        txt = pdf_text(v)
        txt = txt.decode("latin-1", "ignore") if isinstance(txt, bytes) else txt
        if "EQUIPMENT FAILURE CLAIM" in txt.upper():
            hit = True
            break
    rec("research wording reached the rendered documents", hit,
        "industry title found in a PDF" if hit else "industry title missing")
except Exception as e:
    # fall back to the log line build_corpus emits only when a world was applied
    rec("research wording reached the rendered documents",
        any("industry" in (s["detail"] or "") for s in steps),
        f"extractor unavailable ({type(e).__name__}), checked the log instead")
rec("staged message tells the presenter what to do next",
    any("Process documents" in (s["detail"] or "") for s in steps), "cue present")

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
