# DocFlow

DocFlow is a Databricks App that demos Agent Bricks document intelligence on your own workspace.
It generates a watermarked synthetic document inbox, then turns it into governed Delta tables and answers while the customer watches.
Everything runs inside the workspace: a serverless SQL warehouse runs the AI Functions, a Unity Catalog volume holds the files, and model calls go to serving endpoints you pick.
Nothing on screen is simulated. The canvas replays recorded pipeline events, and the cost figure comes from the run's own numbers.
Install is one bundle command or one UI walkthrough. Zero notebooks.

## The install promise, stated honestly

Two numbers.

1. About 15 minutes from install to a running demo on GA functions. That path needs no previews.
2. The full preview floor (document UIs flipped on, an agent built in the product UI) has a target of 45 minutes. The measured number is not published yet. It gets published here after someone who is not the author runs the full path in a fresh workspace.

## What it shows

Four ways to handle a document, all on one screen:

1. **Information Extraction.** Invoices and claims get parsed with `ai_parse_document`, then extracted into typed Delta tables with `ai_extract`. When an Information Extraction agent endpoint is detected, the app swaps it in and shows the confidence delta against the fallback.
2. **Knowledge Assistant.** Documents whose value is their words, like contracts, feed a Knowledge Assistant agent so questions come back answered with page citations. Knowledge Assistant is GA.
3. **Both on the same document.** A warranty claim lands in a table for the numbers and stays askable for the words. Structured questions get answered with visible SQL. Wording questions get cited answers. Same file, both lanes.
4. **Secure filing only.** Sensitive documents, like an HR medical file, get masked with `ai_mask` before anything reads them. The original moves to a volume path locked behind a Unity Catalog grant. No open extraction happens on it.

An audit judge sits on the extraction lane. It flags claims that fail their own math, and a human confirms or overrides with a recorded reason.

## Prerequisites

- A serverless SQL warehouse, in a region where AI Functions are available. AI Functions do not run on Pro or Classic warehouses.
- Permission to create a Databricks App in the workspace.
- A Unity Catalog catalog you can `CREATE SCHEMA` in. The default target is `workspace.docflow` with a volume named `docs`.
- Optional, for the full show floor: a workspace admin who can flip the Agent Bricks experiences on the Previews page. The Information Extraction and Classification document UIs are Public Preview. The demo runs without them on GA functions alone.
- Path B only: Databricks CLI 0.283.0 or newer, authenticated to your workspace. This bundle was validated with CLI v1.0.0.

## Install path A: workspace UI, no CLI

1. Get the code into the workspace. In the left sidebar pick Workspace, then Create, then Git folder, and paste this repo's URL. If Git access is blocked, upload the `app` folder into your workspace files instead.
2. Open Databricks Apps from the app switcher and pick Create app, then Custom. Name it `docflow`.
3. On the configuration step, add three app resources:
   - SQL warehouse: your serverless warehouse, permission `CAN_USE`.
   - Serving endpoint: a chat model, permission `CAN_QUERY`. The code default is `databricks-claude-sonnet-4-6`.
   - Serving endpoint: a judge model, permission `CAN_QUERY`. The code default is `databricks-claude-haiku-4-5`.
4. Point the app's source code path at the `app` folder inside your Git folder and deploy.
5. The code defaults cover a standard workspace: catalog `workspace`, schema `docflow`, volume `docs`, and it will find a serverless warehouse on its own if none is set. To change any of them, add an `env` block to `app/app.yaml`:

```yaml
command: ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
env:
  - name: DOCFLOW_CATALOG
    value: main
  - name: DOCFLOW_WAREHOUSE_ID
    value: <warehouse-id>
```

Valid names: `DOCFLOW_CATALOG`, `DOCFLOW_SCHEMA`, `DOCFLOW_VOLUME`, `DOCFLOW_WAREHOUSE_ID`, `DOCFLOW_CHAT_ENDPOINT`, `DOCFLOW_JUDGE_ENDPOINT`.

## Install path B: one command

From the repo root:

```bash
databricks bundle deploy -t dev
```

That creates the `docflow` app, binds the warehouse and both serving endpoints, sets all six `DOCFLOW_*` environment variables, uploads the code, and deploys the app in started mode.

Retarget without editing anything:

```bash
databricks bundle deploy -t dev --var="catalog=main" --var="warehouse_id=<id>" --var="chat_endpoint=<endpoint>"
```

Defaults for every variable live in `databricks.yml`. If a `docflow` app already exists in the workspace from an earlier manual install, adopt it into the bundle first:

```bash
databricks bundle deployment bind docflow docflow
databricks bundle deploy -t dev
```

Open the app with `databricks bundle open docflow`, or from the Apps page. If the app shows stopped, `databricks bundle run docflow` starts it.

## Grant the app its catalog rights

The app runs as its own service principal, shown on the app's page in the workspace. Before first run, grant it the right to build its schema:

```sql
GRANT USE CATALOG, CREATE SCHEMA ON CATALOG workspace TO `<app-service-principal>`;
```

Swap `workspace` for your catalog if you retargeted. The app creates and then owns the schema, volume, and tables, so no further grants are needed.

## First run

1. **Bootstrap.** Open the app, go to the settings page, press Bootstrap workspace. This runs idempotent DDL: schema, volume, demo tables. Safe to press twice.
2. **Generate documents.** Press generate. The app writes a synthetic corpus of 24 PDFs to the volume inbox in 20 to 40 seconds. Every page carries a visible SYNTHETIC DEMO DATA watermark, and every person and vendor on them is fictional.
3. **Run the pipeline.** Parse, label, route, extract, audit, secure. One to four minutes. The first statement on an idle warehouse is the slow one, so warm it before an audience. The presenter checklist in `docs/RUNBOOK.md` covers this.
4. **Ask.** Open the ask page and ask the money question. The answer arrives with its SQL on screen. Asking before the pipeline runs gets an honest "no tables exist yet," which is the demo's opening beat.

## What it costs to run

Document parsing is billed per page under AI Functions. On US East list pricing that is roughly $0.70 to $1.05 per thousand pages of simple text, up to about $6 per thousand for complex diagram pages. Call it a dollar per thousand pages at the low end. Labeling, extraction, judging, and answers are per-token calls on the endpoints you chose. The app computes each run's cost from these rates and puts it on the money board, recorded in `run_metrics`, so the demo quotes its own bill instead of a slide. The reference run processed 24 documents for well under a dollar. For metered billing truth, check your account's usage tables. One adjacent fact: Genie Agents moves to pay-as-you-go on August 1, 2026, with 150 free LLM DBUs per month.

## Limits and preview status, stated plainly

Verified 2026-07-31. The runtime copy of this table is `app/static-staging/platform_facts.json`. If this section and that file disagree, the file wins because it is maintained.

| Piece | Status | Note |
|---|---|---|
| `ai_parse_document` | GA | 500 pages and 100 MB per file. Serverless compute only. |
| `ai_classify`, `ai_extract`, `ai_query` | GA | GA since June 2026. |
| `ai_mask` | Public Preview | The secure lane's redaction primitive. |
| Databricks Apps | GA | The app itself. |
| Knowledge Assistant | GA | Cited answers over documents. |
| Supervisor Agent | GA | SDK management is Beta. |
| Information Extraction document UI | Public Preview | Previews page flip. Successor to the legacy IE brick. |
| Classification document UI | Public Preview | Previews page flip. |
| Agent Bricks IE brick (legacy) | Beta | Docs now label it legacy. Detected if present. |
| Genie Agents | GA | Renamed from Genie Spaces in July 2026. |

Two honest constraints. The document analysis agents are created in the workspace UI only, with no REST or Terraform path, so the app detects their endpoints rather than creating them. And where a preview is off, the pipeline runs on the GA functions alone and the capability panel says so. The show does not depend on a preview to function.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "No serverless SQL warehouse found" | Workspace only has Pro or Classic warehouses | Create a serverless SQL warehouse, then bind it (path A) or redeploy with `--var="warehouse_id=<id>"` (path B). AI Functions run on serverless only. |
| AI function calls fail as unavailable in this region | AI Functions are region-gated | Check the AI Functions region list in the Databricks docs and use a workspace in a listed region. There is no flag that works around this. |
| Bootstrap fails with PERMISSION_DENIED on the catalog | The app's service principal lacks catalog rights | Run the GRANT statement above, or retarget with `--var="catalog=<one-you-control>"`. |
| App deploys but will not start, or its URL errors | Startup failure inside the app container | Open the app's page and read Logs. Usual causes: a dependency in `requirements.txt` failed to install, or the command changed. The server must listen on `0.0.0.0:8000`. Fix, then redeploy. |
| `bundle deploy` says the app already exists | App was created outside the bundle | `databricks bundle deployment bind docflow docflow`, then deploy again. |

## Repo map

- `databricks.yml` is the bundle: app resource, bindings, variables.
- `app/` is the app: FastAPI backend, pipeline, corpus generator, static frontend.
- `docs/RUNBOOK.md` is the presenter script, beat by beat, with the reset checklist.
- `PLAN.md` is the build plan and architecture.
