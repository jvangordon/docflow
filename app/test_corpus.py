#!/usr/bin/env python3
"""Smoke test for the DocFlow synthetic corpus generator.

Run:  python3 test_corpus.py

Generates two identical runs (plus one variant-company/seed run) under
/tmp/docflow-corpus-test and checks: file presence, per-type counts, the
planted demo story (exact values), table math, watermark + footer on every
page, content guardrails, routing matrix, and cross-run determinism down to
the PDF bytes.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corpus  # noqa: E402

ROOT = "/tmp/docflow-corpus-test"
EXPECTED_COUNTS = {"supplier_invoice": 4, "purchase_order": 2, "warranty_claim": 5,
                   "quality_inspection": 4, "safety_incident": 2, "hr_document": 1,
                   "shipping_manifest": 1, "marketing": 1, "supplier_contract": 4}
PREFIX = {"supplier_invoice": "INV-", "purchase_order": "PO-", "warranty_claim": "WC-",
          "quality_inspection": "QIR-", "safety_incident": "SI-", "hr_document": "HR-",
          "shipping_manifest": "SM-", "marketing": "MKT-", "supplier_contract": "CT-"}
PLANTED = {"INV-88213", "WC-2214", "WC-2231", "QIR-0781", "QIR-0782", "QIR-0783", "QIR-0784"}


def cents(s):
    d, c = s.split(".")
    return int(d) * 100 + int(c)


def pdf_text(data):
    """Decompress every content stream (ASCII85- and/or Flate-encoded)."""
    parts = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        raw = m.group(1)
        if b"~>" in raw:
            try:
                raw = base64.a85decode(raw.strip(), adobe=True)
            except ValueError:
                pass
        try:
            raw = zlib.decompressobj().decompress(raw)
        except zlib.error:
            pass
        parts.append(raw)
    return b"".join(parts)


def run(name, company="Acme Manufacturing", seed=38):
    out = os.path.join(ROOT, name)
    shutil.rmtree(out, ignore_errors=True)
    return out, corpus.generate_corpus(company, out, seed=seed)


def check_story(manifest):
    by_id = {e["doc_id"]: e for e in manifest["generated"]}
    wc = by_id["WC-2214"]["ground_truth"]
    assert wc["serial_number"] == "SN-44781"
    assert wc["purchase_date"] == "2023-11-02" and wc["warranty_term_months"] == 24
    assert wc["failure_date"] == "2026-03-18" and wc["claim_amount"] == "2140.00"
    assert wc["production_line"] == "Line 3" and wc["within_warranty"] is False
    assert by_id["WC-2214"]["planted_trap"] is True
    w2 = by_id["WC-2231"]["ground_truth"]
    assert w2["purchase_date"] == "2023-08-15" and w2["warranty_term_months"] == 24
    assert w2["failure_date"] == "2026-01-22" and w2["claim_amount"] == "1170.00"
    assert w2["within_warranty"] is False and by_id["WC-2231"]["planted_trap"] is True
    inside = [e for e in manifest["generated"] if e["type"] == "warranty_claim"
              and e["doc_id"] not in ("WC-2214", "WC-2231")]
    assert len(inside) == 3
    assert all(e["ground_truth"]["within_warranty"] is True for e in inside)

    qirs = sorted((e for e in manifest["generated"] if e["type"] == "quality_inspection"),
                  key=lambda e: e["ground_truth"]["inspection_date"])
    assert [q["ground_truth"]["line3_defect_rate_pct"] for q in qirs] == [1.2, 1.9, 3.1, 4.8]
    for q in qirs:
        assert q["planted_trap"] is True
        for row in q["ground_truth"]["lines"]:
            assert abs(row["defects"] * 100.0 / row["units_inspected"]
                       - row["defect_rate_pct"]) < 1e-9, ("rate mismatch", q["doc_id"], row)
    for line in ("Line 1", "Line 2", "Line 4"):
        rates = [next(r["defect_rate_pct"] for r in q["ground_truth"]["lines"]
                      if r["line"] == line) for q in qirs]
        assert max(rates) - min(rates) <= 0.35 and max(rates) < 1.5, (line, rates)

    inv = by_id["INV-88213"]
    assert inv["ground_truth"]["vendor"] == "Miller Tooling LLC"
    assert inv["ground_truth"]["invoice_date"] == "2023-11-02"
    assert "SN-44781" in inv["ground_truth"]["serial_numbers"]
    assert any("SN-44781" in li["description"] for li in inv["ground_truth"]["line_items"])
    assert inv["planted_trap"] is True
    assert wc["proof_of_purchase"] == "INV-88213"
    assert {e["doc_id"] for e in manifest["generated"] if e["planted_trap"]} == PLANTED


def check_shape_and_math(manifest):
    assert set(manifest) >= {"company", "seed", "generated"}
    assert len(manifest["generated"]) == 24
    counts = {}
    for e in manifest["generated"]:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
        assert e["doc_id"].startswith(PREFIX[e["type"]]), e["doc_id"]
        assert e["filename"] == e["doc_id"] + ".pdf"
        assert isinstance(e["planted_trap"], bool) and isinstance(e["ground_truth"], dict)
        gt = e["ground_truth"]
        if e["type"] in ("supplier_invoice", "purchase_order"):
            for li in gt["line_items"]:
                assert cents(li["amount"]) == li["qty"] * cents(li["unit_price"]), li
            total_items = sum(cents(li["amount"]) for li in gt["line_items"])
            if e["type"] == "supplier_invoice":
                assert total_items == cents(gt["subtotal"])
                assert cents(gt["subtotal"]) + cents(gt["tax"]) == cents(gt["total"])
            else:
                assert total_items == cents(gt["total"])
        if e["type"] == "shipping_manifest":
            assert sum(p["cartons"] for p in gt["packages"]) == gt["total_cartons"]
            assert sum(p["weight_lb"] for p in gt["packages"]) == gt["total_weight_lb"]
            assert len(gt["packages"]) == gt["package_count"]
        if e["type"] == "safety_incident":
            assert gt["site"] == "Plant 7, Demoville"
    assert counts == EXPECTED_COUNTS, counts


def check_guardrails(manifest):
    by_id = {e["doc_id"]: e for e in manifest["generated"]}
    assert by_id["HR-0007"]["ground_truth"]["ssn"] == "000-00-0000"
    blob = json.dumps(manifest)
    for em in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", blob):
        assert em.endswith("@example.com"), em
    for ph in re.findall(r"\b555-\d{4}\b", blob):
        assert re.fullmatch(r"555-01\d{2}", ph), ph
    people = set(corpus.PEOPLE)
    for e in manifest["generated"]:
        for key in ("employee", "inspector"):
            if key in e["ground_truth"]:
                assert e["ground_truth"][key] in people, (e["doc_id"], key)


def check_pdfs(out_dir, manifest):
    for e in manifest["generated"]:
        path = os.path.join(out_dir, e["filename"])
        assert os.path.isfile(path), path
        data = open(path, "rb").read()
        assert data.startswith(b"%PDF") and len(data) > 1500, path
        pages = len(re.findall(rb"/Type\s*/Page\b", data))
        assert 1 <= pages <= 2, (e["doc_id"], pages)
        text = pdf_text(data)
        assert text.count(b"(SYNTHETIC DEMO DATA)") >= pages, ("watermark", e["doc_id"])
        footer = b"(Synthetic demonstration document generated by DocFlow. Not a real record.)"
        assert text.count(footer) >= pages, ("footer", e["doc_id"])


def check_routing():
    R = corpus.ROUTING
    assert R["warranty_claim"] == {"extract": True, "audit": True, "secure": False}
    assert R["quality_inspection"] == {"extract": True, "audit": True, "secure": False}
    assert R["safety_incident"] == {"extract": True, "audit": False, "secure": True}
    assert R["hr_document"] == {"extract": False, "audit": False, "secure": True}
    for t in ("supplier_invoice", "purchase_order", "shipping_manifest"):
        assert R[t] == {"extract": True, "audit": False, "secure": False}
    assert R["marketing"] == {"extract": False, "audit": False, "secure": False}
    assert set(R) == set(corpus.TAXONOMY) == set(EXPECTED_COUNTS)
    assert sum(v["count"] for v in corpus.TAXONOMY.values()) == 24
    assert {t: v["count"] for t, v in corpus.TAXONOMY.items()} == EXPECTED_COUNTS


def main():
    check_routing()
    out1, m1 = run("run1")
    assert m1["company"] == "Acme Manufacturing" and m1["seed"] == 38
    check_shape_and_math(m1)
    check_story(m1)
    check_guardrails(m1)
    check_pdfs(out1, m1)
    disk = json.load(open(os.path.join(out1, "manifest.json")))
    assert disk == json.loads(json.dumps(m1)), "manifest.json != returned manifest"

    out2, m2 = run("run2")
    assert json.dumps(m1, sort_keys=True) == json.dumps(m2, sort_keys=True), \
        "manifests differ across identical runs"
    for e in m1["generated"]:
        h1 = hashlib.sha256(open(os.path.join(out1, e["filename"]), "rb").read()).hexdigest()
        h2 = hashlib.sha256(open(os.path.join(out2, e["filename"]), "rb").read()).hexdigest()
        assert h1 == h2, ("pdf bytes differ across runs", e["doc_id"])

    # different company + seed: shape, story, and guardrails must still hold
    out3, m3 = run("run3", company="Smith & Sons Manufacturing", seed=7)
    check_shape_and_math(m3)
    check_story(m3)
    check_guardrails(m3)
    check_pdfs(out3, m3)
    assert json.dumps(m3, sort_keys=True) != json.dumps(m1, sort_keys=True)

    counts = {}
    for e in m1["generated"]:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    print("corpus smoke test: ALL GREEN")
    for t, n in counts.items():
        print(f"  {t:20s} {n}")
    print(f"  planted traps: {sorted(e['doc_id'] for e in m1['generated'] if e['planted_trap'])}")


if __name__ == "__main__":
    main()

# ---- hostile world shapes: the model ignoring the schema must cost nothing --
import tempfile as _tf
_hostile = [
    "just a sentence describing the company",
    {"contract": "a supply agreement with Acme covering pumps",
     "type_labels": ["not", "a", "dict"],
     "generated": "twenty-four documents about pumps",
     "narratives": "one long paragraph",
     "vendors": "Acme Industrial",
     "site": ["a list", "of sites"]},
    {"narratives": {"claim_impacts": "a single string not a list",
                    "contract_warranty_procedure": ["list", "for", "scalar"]}},
]
for _w in _hostile:
    _out = apply_world(_w) if "apply_world" in dir() else __import__("corpus").apply_world(_w)
    assert _out["contract"]["penalty_pct"] == "5", "hostile world leaked into contract"
with _tf.TemporaryDirectory() as _td:
    _man = __import__("corpus").generate_corpus("Hostile Shapes Inc", _td, seed=38,
                                                world=_hostile[1])
    assert len(_man["generated"]) == 24, f"hostile world broke generation: {len(_man['generated'])}"
print("hostile world shapes survived: defaults used, 24 PDFs generated")
