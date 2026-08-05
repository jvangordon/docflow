# Making the agents visible: IE + Text Classification tiles

DocFlow runs classification and extraction as `ai_classify` / `ai_extract` in
SQL — the same engines behind the Agent Bricks tiles, called directly. That is
the right architecture for a pipeline, but an audience connects faster when
they can open **Agents** in the left nav and *see* the bricks. Information
Extraction and Text Classification tiles have **no public create API** (only
Knowledge Assistant, Custom LLM and Supervisor do), so these two are created
by hand in the UI. Ten minutes, once per workspace.

> Do this **after** a DocFlow run has reached *Staged* or later, so the
> volume, schema and documents the tiles point at already exist. Replace
> `CATALOG.SCHEMA` below with your install target (the Start page shows it).

---

## 1 · Text Classification agent — the router, as a tile

**Agents → Create agent (or +New → Agent) → Text Classification.**

| Field | Value |
|---|---|
| Name | `docflow-tc-router` |
| Description | Routes back-office documents to the lane they need. Demo twin of DocFlow's in-SQL `ai_classify` router. |
| Input | The document text. Point it at the volume `/Volumes/CATALOG/SCHEMA/docs/inbox` if the tile accepts documents, or at table `CATALOG.SCHEMA.parsed`, column `doc` (the parsed text) if it asks for a table. |
| Output table | `CATALOG.SCHEMA.docflow_tc_output` — keep the `docflow_tc_` prefix so it can never be confused with a customer table. |

**Labels** — use the same nine the app routes on, with one-line descriptions:

- `supplier_invoice` — a bill from a supplier requesting payment
- `purchase_order` — an order we issued to a supplier
- `warranty_claim` — a claim that a delivered unit failed inside/outside coverage
- `quality_inspection` — an inspection report with findings
- `supplier_contract` — an agreement: terms, penalties, warranty windows
- `safety_incident` — a workplace safety event report
- `shipping_manifest` — a shipment's contents and routing
- `hr_document` — personnel material; never enters an agent lane
- `marketing` — supplier promotional mail; no action

*Stage line:* "The app calls this same classifier from SQL on every run — this
tile is the packaged version your team would manage here, with the same labels."

## 2 · Information Extraction agent — claims fields, as a tile

**Agents → Create agent → Information Extraction.**

| Field | Value |
|---|---|
| Name | `docflow-ie-claims` |
| Description | Pulls the queryable fields out of warranty claims. Demo twin of DocFlow's in-SQL `ai_extract`. |
| Source documents | `/Volumes/CATALOG/SCHEMA/docs/ka_claims` (claims land here after the classifier routes them — press **Process documents** first) |
| Output table | `CATALOG.SCHEMA.docflow_ie_claims` |

**Fields to extract** — the exact set the app extracts, with the wording
lesson included:

- `claim_id` — the claim's own reference number
- `unit_serial` — serial number of the failed unit
- `purchase_date` — date the unit was purchased
- `failure_date` — date the failure was reported
- `warranty_term_months` — coverage length in months
- `claim_amount` — amount claimed
- `production_line` — line or site named on the claim
- `vendor_company_that_issued_this_invoice` — *only if you demo invoices too:*
  the label **is** the prompt; the bare label `vendor` reads the "Bill to"
  party (the buyer). Spelling out the intent in the field name fixes it —
  that's a genuinely good on-stage beat about how extraction is steered.

*Stage line:* "Same fields the pipeline extracted — the coverage math and the
$-figure you saw on Recover come from these."

## 3 · Show the code

Open the **`ai_functions_tour`** notebook in this Git folder: every function
the app calls (`ai_parse_document`, `ai_classify`, `ai_extract`, `ai_query`,
`ai_mask`), as runnable cells against your install's own tables, `LIMIT`ed so
they run in seconds. Widgets at the top take catalog/schema/model.

## 4 · Cleanup — these two are yours, not the app's

DocFlow's reset deletes **only what the app itself created and recorded** —
that is its safety promise in customer workspaces, and hand-made tiles carry
no DocFlow fingerprint. After the demo, delete by hand:

- Agents UI: `docflow-tc-router`, `docflow-ie-claims`
- Tables: `docflow_tc_output`, `docflow_ie_claims`

## 5 · Two-account setup (one live, one finished)

Nothing is shared between installs — config, state and assets live inside
each workspace. So: install in both accounts, run account A to **done** the
day before (Ask + Recover fully lit), and leave account B at **Staged** —
walk on stage, press *Process documents* in B for the live swim lanes, and
flip to A whenever you want the finished state without waiting. The two-run
"Process them again" replay also works on A at any time.
