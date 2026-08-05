"""Show-the-code: the app's AI-function calls, presentable and runnable.

One source of truth for the Playbook page and the generated notebook. Every
query is the real shape the pipeline runs, with the install's own catalog,
schema and model substituted — so what the audience copies runs as-is.
"""
from __future__ import annotations

import base64
import json

import pipeline


def _blocks() -> list[dict]:
    fq, vol = pipeline.FQ, pipeline.VOL_ROOT
    model = pipeline.chat_model()
    advice_schema = json.dumps({
        "type": "json_schema",
        "json_schema": {"name": "advice", "schema": {"type": "object", "properties": {
            "diagnosis": {"type": "string"}, "next_step": {"type": "string"},
            "urgency": {"type": "string", "enum": ["now", "this week", "routine"]},
        }, "required": ["diagnosis", "next_step", "urgency"]}, "strict": True}})
    return [
        {"title": "ai_parse_document · a PDF becomes structured text",
         "note": "One function turns a binary PDF into layout-aware text. The "
                 "app runs this over the whole inbox in a single statement.",
         "sql": f"""SELECT regexp_extract(path, '([^/]+)\\\\.pdf$', 1) AS doc_id,
       substr(to_json(ai_parse_document(content)), 1, 1200) AS parsed_head
FROM READ_FILES('{vol}/inbox/', format => 'binaryFile')
LIMIT 1"""},
        {"title": "ai_classify · the router",
         "note": "The classifier answers in the industry's own labels; the app "
                 "maps the spoken label back to a structural key in SQL.",
         "sql": f"""SELECT doc_id,
       ai_classify(substr(to_json(doc), 1, 3000),
                   ARRAY('supplier invoice', 'purchase order', 'warranty claim',
                         'quality inspection', 'supplier contract', 'safety incident',
                         'shipping manifest', 'HR document', 'marketing')) AS label
FROM {fq}.parsed
LIMIT 5"""},
        {"title": "ai_extract · fields out of prose",
         "note": "The labels ARE the prompt. try_cast everywhere: a malformed "
                 "answer must never kill a run, and a NULL date must never "
                 "silently read as an expired claim.",
         "sql": f"""SELECT doc_id, x.unit_serial,
       try_cast(x.purchase_date AS DATE)  AS purchase_date,
       try_cast(x.failure_date AS DATE)   AS failure_date,
       try_cast(regexp_extract(x.warranty_term_months, '([0-9]+)', 1) AS INT) AS term_months,
       try_cast(regexp_replace(x.claim_amount, '[^0-9.]', '') AS DOUBLE)      AS claim_amount
FROM (SELECT l.doc_id,
             ai_extract(substr(to_json(p.doc), 1, 3500),
               ARRAY('unit_serial', 'purchase_date', 'failure_date',
                     'warranty_term_months', 'claim_amount', 'production_line')) AS x
      FROM {fq}.labeled l JOIN {fq}.parsed p USING (doc_id)
      WHERE l.doc_type = 'warranty_claim'
      LIMIT 3)"""},
        {"title": "The audit is arithmetic, not AI",
         "note": "The money figure is date math over extracted fields — "
                 "reproducible from the source document, no model in the loop.",
         "sql": f"""SELECT doc_id, claim_amount,
       add_months(purchase_date, warranty_term_months) AS coverage_ended,
       failure_date,
       datediff(failure_date, add_months(purchase_date, warranty_term_months)) AS days_past_term
FROM {fq}.extract_warranty_claims
WHERE claim_status = 'outside window'
ORDER BY claim_amount DESC"""},
        {"title": "ai_query · any gateway model, structured answers",
         "note": "Free-form calls with a JSON schema the answer must match. "
                 "This powers research, routing advice and Recover's next steps.",
         "sql": f"""SELECT ai_query('{model}',
    'A warranty claim for $131,000 was filed 44 days after coverage ended. '
    || 'One diagnosis, one concrete next step.',
    responseFormat => '{advice_schema.replace(chr(39), chr(39) * 2)}') AS advice"""},
        {"title": "ai_mask · the secure lane",
         "note": "Personal data is masked before filing; the HR document never "
                 "reaches an agent at all.",
         "sql": """SELECT ai_mask(
  'Employee Dana Whitfield (SSN 522-84-1199, dana.w@example.com) reported the incident.',
  ARRAY('person', 'email')) AS masked"""},
    ]


def questions() -> dict:
    """Two Genie questions and two per assistant, plus one combined submittal.

    Platform-owned questions lead where present; fallbacks are the corpus's
    own planted story, so every answer resolves."""
    genie = ["How many warranty claims are outside their coverage window, "
             "and what is the total amount?",
             "Which vendor billed the most across the supplier invoices?"]
    contracts = ["What does the supplier contract say about the penalty for "
                 "late delivery, and who signs off on a warranty claim?",
                 "What must be included when filing a warranty claim, and what "
                 "is the filing deadline?"]
    claims = ["What did the inspector find on the failed unit, and what "
              "failure mode is described?",
              "What does the largest claim say happened, and what was the "
              "operational impact?"]
    try:
        import orchestrator
        pq = orchestrator._call(orchestrator.platform_questions, 6,
                                "reading the platform's questions")
        if pq.get("genie"):
            genie = [q for q in pq["genie"] if q][:2] or genie
        plat = [q for q in (pq.get("assistant") or []) if q]
        if plat:
            kw = ("contract", "agreement", "clause", "penalt", "policy",
                  "terms", "deadline", "notice", "filing")
            pc = [q for q in plat if any(k in q.lower() for k in kw)]
            pl = [q for q in plat if q not in pc]
            contracts = (pc + contracts)[:2]
            claims = (pl + claims)[:2]
    except Exception:
        pass
    combined = " ".join(genie + [contracts[0], claims[0]])
    digest = ("Summarize the current document intake: how many warranty claims "
              "are within warranty, outside their coverage window, and needing "
              "review, and the total dollar amount in each group — show a bar "
              "chart of amounts by status. Then list the three largest "
              "outside-window claims with unit serial, amount, and days past "
              "coverage, and finish with one sentence on what changed most.")
    return {"genie": genie, "contracts": contracts, "claims": claims,
            "combined": combined, "digest": digest}


def payload() -> dict:
    """Everything the Playbook page renders, with live values substituted."""
    cat, sch = pipeline.CATALOG, pipeline.SCHEMA
    return {
        "questions": questions(),
        "catalog": cat, "schema": sch, "model": pipeline.chat_model(),
        "volume": pipeline.VOL_ROOT,
        "blocks": _blocks(),
        "tiles": {
            "tc": {"name": "docflow-tc-router",
                   "source": f"{pipeline.VOL_ROOT}/inbox",
                   "table": f"{cat}.{sch}.docflow_tc_output",
                   "labels": [
                       "supplier_invoice — a bill from a supplier requesting payment",
                       "purchase_order — an order we issued to a supplier",
                       "warranty_claim — a claim that a delivered unit failed",
                       "quality_inspection — an inspection report with findings",
                       "supplier_contract — terms, penalties, warranty windows",
                       "safety_incident — a workplace safety event report",
                       "shipping_manifest — a shipment's contents and routing",
                       "hr_document — personnel material; never enters an agent lane",
                       "marketing — supplier promotional mail; no action"]},
            "ie": {"name": "docflow-ie-claims",
                   "source": f"{pipeline.VOL_ROOT}/ka_claims",
                   "table": f"{cat}.{sch}.docflow_ie_claims",
                   "fields": [
                       "claim_id — the claim's own reference number",
                       "unit_serial — serial number of the failed unit",
                       "purchase_date — date the unit was purchased",
                       "failure_date — date the failure was reported",
                       "warranty_term_months — coverage length in months",
                       "claim_amount — amount claimed",
                       "production_line — line or site named on the claim"],
                   "lesson": ("The label IS the prompt: the bare label 'vendor' reads "
                              "the Bill-to party (the buyer). Naming the field "
                              "'vendor_company_that_issued_this_invoice' fixes it.")},
        },
    }


def notebook_source() -> str:
    """A ready-to-run notebook with this install's values baked in."""
    cells = ["# Databricks notebook source",
             "# MAGIC %md",
             "# MAGIC # DocFlow · the AI functions, as plain SQL",
             "# MAGIC Generated by the app for this install — values are already "
             "filled in. Run top to bottom after a DocFlow prepare + process."]
    for b in _blocks():
        cells.append("# COMMAND ----------")
        cells.append("# MAGIC %md ## " + b["title"] + "\n# MAGIC " + b["note"])
        cells.append("# COMMAND ----------")
        cells.append("# MAGIC %sql\n" + "\n".join(
            "# MAGIC " + line for line in b["sql"].split("\n")))
    return "\n".join(cells) + "\n"


def create_notebook() -> dict:
    """Write the notebook into /Workspace/Shared so anyone in the room can open it."""
    from databricks.sdk.service.workspace import ImportFormat, Language
    w = pipeline.wc()
    folder = "/Workspace/Shared/docflow"
    path = f"{folder}/ai_functions_tour"
    w.workspace.mkdirs(folder)
    w.workspace.import_(path,
                        content=base64.b64encode(notebook_source().encode()).decode(),
                        format=ImportFormat.SOURCE, language=Language.PYTHON,
                        overwrite=True)
    url = ""
    try:
        oid = w.workspace.get_status(path).object_id
        url = f"{w.config.host.rstrip('/')}/editor/notebooks/{oid}"
    except Exception:
        pass
    return {"path": path, "url": url}
