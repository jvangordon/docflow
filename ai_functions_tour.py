# Databricks notebook source
# MAGIC %md
# MAGIC # The AI functions behind DocFlow — as plain SQL
# MAGIC
# MAGIC Every capability in the demo is one SQL function you can call yourself.
# MAGIC These are the same calls the app makes, `LIMIT`ed so each cell runs in
# MAGIC seconds. Run a DocFlow prepare + process first so the documents and
# MAGIC tables exist, set the three widgets above, then run top to bottom.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "docflow")
dbutils.widgets.text("model", "databricks-claude-sonnet-4-6")
CAT = dbutils.widgets.get("catalog").strip()
SCH = dbutils.widgets.get("schema").strip()
MODEL = dbutils.widgets.get("model").strip()
FQ = f"{CAT}.{SCH}"
VOL = f"/Volumes/{CAT}/{SCH}/docs"
print(f"tables: {FQ} · documents: {VOL} · model: {MODEL}")

# COMMAND ----------

# MAGIC %md ## 1 · `ai_parse_document` — a PDF becomes structured text
# MAGIC One function turns a binary PDF into layout-aware text and elements.
# MAGIC The app runs this over the whole inbox in a single statement.

# COMMAND ----------

display(spark.sql(f"""
  SELECT regexp_extract(path, '([^/]+)\\\\.pdf$', 1) AS doc_id,
         substr(to_json(ai_parse_document(content)), 1, 1200) AS parsed_head
  FROM READ_FILES('{VOL}/inbox/', format => 'binaryFile')
  LIMIT 1"""))

# COMMAND ----------

# MAGIC %md ## 2 · `ai_classify` — the router
# MAGIC The classifier answers in the industry's own labels; the `CASE` maps the
# MAGIC spoken label back to the structural key every downstream stage filters
# MAGIC on. This is the exact shape the app runs.

# COMMAND ----------

display(spark.sql(f"""
  SELECT doc_id,
         ai_classify(substr(to_json(doc), 1, 3000),
                     ARRAY('supplier invoice', 'purchase order', 'warranty claim',
                           'quality inspection', 'supplier contract', 'safety incident',
                           'shipping manifest', 'HR document', 'marketing')) AS label
  FROM {FQ}.parsed
  LIMIT 5"""))

# COMMAND ----------

# MAGIC %md ## 3 · `ai_extract` — fields out of prose
# MAGIC The labels ARE the prompt. Note `try_cast` everywhere: one malformed
# MAGIC model answer must never kill a pipeline, and a NULL date must never
# MAGIC silently read as an expired claim.

# COMMAND ----------

display(spark.sql(f"""
  SELECT doc_id, x.unit_serial,
         try_cast(x.purchase_date AS DATE)                                   AS purchase_date,
         try_cast(x.failure_date AS DATE)                                    AS failure_date,
         try_cast(regexp_extract(x.warranty_term_months, '([0-9]+)', 1) AS INT) AS term_months,
         try_cast(regexp_replace(x.claim_amount, '[^0-9.]', '') AS DOUBLE)   AS claim_amount
  FROM (SELECT l.doc_id,
               ai_extract(substr(to_json(p.doc), 1, 3500),
                 ARRAY('unit_serial', 'purchase_date', 'failure_date',
                       'warranty_term_months', 'claim_amount', 'production_line')) AS x
        FROM {FQ}.labeled l JOIN {FQ}.parsed p USING (doc_id)
        WHERE l.doc_type = 'warranty_claim'
        LIMIT 3)"""))

# COMMAND ----------

# MAGIC %md ## 4 · The audit is arithmetic, not AI
# MAGIC Deliberate beat: the money figure comes from date math over extracted
# MAGIC fields — reproducible from the source document, no model in the loop.

# COMMAND ----------

display(spark.sql(f"""
  SELECT doc_id, claim_amount,
         add_months(purchase_date, warranty_term_months) AS coverage_ended,
         failure_date,
         datediff(failure_date, add_months(purchase_date, warranty_term_months)) AS days_past_term
  FROM {FQ}.extract_warranty_claims
  WHERE claim_status = 'outside window'
  ORDER BY claim_amount DESC"""))

# COMMAND ----------

display(spark.sql(f"""
  SELECT concat('$', format_number(sum(claim_amount), 2)) AS caught_outside_coverage
  FROM {FQ}.extract_warranty_claims
  WHERE claim_status = 'outside window'"""))

# COMMAND ----------

# MAGIC %md ## 5 · `ai_query` — any gateway model, structured answers
# MAGIC Free-form calls against the model the workspace serves, with a JSON
# MAGIC schema the answer must match. This powers research, routing advice and
# MAGIC the Recover page's next-step suggestions.

# COMMAND ----------

import json
schema = json.dumps({
    "type": "json_schema",
    "json_schema": {"name": "advice", "schema": {"type": "object", "properties": {
        "diagnosis": {"type": "string"},
        "next_step": {"type": "string"},
        "urgency": {"type": "string", "enum": ["now", "this week", "routine"]},
    }, "required": ["diagnosis", "next_step", "urgency"]}, "strict": True}})
q = ("A warranty claim for $131,000 was filed 44 days after coverage ended. "
     "One diagnosis, one concrete next step.")
display(spark.sql(f"""
  SELECT ai_query('{MODEL}', '{q}',
                  responseFormat => '{schema.replace("'", "''")}') AS advice"""))

# COMMAND ----------

# MAGIC %md ## 6 · `ai_mask` — the secure lane
# MAGIC Personal data is masked before anything is filed; the HR document never
# MAGIC reaches an agent at all. Inline sample so this cell touches no real file.

# COMMAND ----------

display(spark.sql("""
  SELECT ai_mask(
    'Employee Dana Whitfield (SSN 522-84-1199, dana.w@example.com) reported the incident.',
    ARRAY('person', 'email')) AS masked"""))

# COMMAND ----------

# MAGIC %md
# MAGIC **Where the app goes further:** it chains these into lanes (classify →
# MAGIC route → extract → audit → secure), indexes the prose lanes into
# MAGIC Knowledge Assistants over the sync API, opens a case per audit finding,
# MAGIC and writes your decisions to Lakebase. Same functions, orchestrated.
