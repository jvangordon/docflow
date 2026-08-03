# DocFlow

A pile of PDFs goes in. Governed tables and cited answers come out, on screen, while the
customer watches.

DocFlow is a Databricks App that demos Agent Bricks document intelligence in your own
workspace. It provisions what it needs, writes its own synthetic document inbox, runs the
documents through four different handling lanes, and ends on two pages a business user
would actually use. Nothing is mocked. The flow on screen is the run that just happened.

Everything happens inside the workspace. No notebooks to babysit, no pre-work.

## Install

Both paths end in the same place. Pick whichever suits the workspace you are in.

### A. From Git, no command line

Best in a customer workspace, or on any machine without the Databricks CLI.

1. In the workspace sidebar: **Workspace**, **Create**, **Git folder**, paste
   `https://github.com/jvangordon/docflow`, **Create**. It needs no credentials.
2. Open `setup_databricks.py` inside the clone and press **Run all**.

The notebook runs as **you**, which is the point. It creates the app, deploys the code
straight out of the Git folder, then grants the app the two rights it needs to provision
the workspace for itself. It finishes by printing a link.

To update later: press **Pull** in the Git folder, then run the notebook again.

### B. One command, if you have the CLI

```bash
git clone https://github.com/jvangordon/docflow && cd docflow && python3 install.py
```

Same three things, and it prints the app URL when it finishes. `--profile` picks a
non-default CLI profile, `--catalog` retargets off `workspace`.

## Running it

Open the app. Three moves.

1. **Set up this workspace.** The readiness panel runs nine checks against the live
   workspace: identity, warehouse, catalog, schema, volume, serving endpoints, AI
   Functions, Knowledge Assistant, billing. Anything red gets a button that fixes it over
   the API, or exact instructions when the platform has no API for it. Press the button
   and watch them go green.
2. **Name the customer and their industry.** Two fields. An LLM on AI Gateway researches
   the company and writes the demo around it: the document mix, the lane names, the
   questions worth asking, the accent color.
3. **Go.** One button. Roughly two minutes, and you watch it happen.

Go is gated on readiness. If a check is red, the button says so rather than failing
halfway through in front of an audience.

## What it shows

The hero is the documents moving. A pile arrives, text classification sorts it, and the
lanes fan out from there — four different ways to handle a document, on one screen:

1. **Information Extraction.** Invoices and claims get parsed with `ai_parse_document`,
   then extracted into typed Delta tables. When an Information Extraction agent endpoint
   exists in the workspace, the app swaps it in and shows the confidence delta against the
   fallback.
2. **Knowledge Assistant.** Documents whose value is their words feed a real Knowledge
   Assistant agent, created by the app, so questions come back with page citations.
3. **Both lanes at once.** A warranty claim lands in a table for its numbers and stays
   askable for its words. Same file, both treatments.
4. **Secure filing only, no AI.** A sensitive file gets masked, then moves to a volume path
   behind a Unity Catalog grant. Nothing reads it. The lane that does nothing is the one
   compliance asks about.

Routing is deterministic: policy decides the lane, the agent recommends one, and
disagreements are shown rather than hidden. An audit judge sits on the extraction lane and
flags claims that fail their own arithmetic.

Then two pages built on the results — a claims view and a supplier view — plus a Genie
space over the extracted fields, so the same questions can be asked in Databricks after
the demo ends.

## Prerequisites

The app provisions most of this itself, given the two grants the installer applies. What it
cannot conjure:

- A workspace in a region where AI Functions are available.
- Permission to create a Databricks App.
- Serverless SQL. AI Functions do not run on Pro or Classic warehouses.

Free Edition works, and is what this was built and tested against. Its limits are real
though: one workspace, three apps, a single 2X-Small warehouse, and apps stop themselves
after 24 hours.

## What it costs

Parsing is billed per page. On US East list pricing that is roughly $0.70 to $1.05 per
thousand pages of simple text, up to about $6 per thousand for complex pages. Labeling,
extraction, judging, and answers are per-token calls on the endpoints you picked. The app
computes each run's cost from its own numbers and shows it, so the demo quotes its own bill
instead of a slide. The reference run processed 24 documents for well under a dollar.

## Platform status

Verified 2026-08-03. The runtime copy is `app/static-staging/platform_facts.json`; if that
file and this table disagree, the file wins because it is maintained.

| Piece | Status |
|---|---|
| `ai_parse_document`, `ai_classify`, `ai_extract`, `ai_query` | GA |
| `ai_mask` | Public Preview |
| Databricks Apps | GA |
| Knowledge Assistant | GA, creatable over the SDK |
| Supervisor Agent | GA, SDK management Beta |
| Genie | GA |
| Information Extraction agent | Public Preview, **no create API** |

One honest constraint worth knowing before you present. The Information Extraction agent
has no REST or SDK create path, so the app detects an existing endpoint rather than
building one. Where it is absent, the extraction lane runs on GA AI Functions alone and the
capability panel says exactly that. The demo never depends on a preview to function.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Readiness cannot create a warehouse | The app's identity lacks cluster creation | Re-run the installer, or an admin ticks **Allow cluster creation** on the app's service principal under Settings, Identity and access |
| Readiness cannot create a schema | The app's identity lacks catalog rights | Grant `USE CATALOG` and `CREATE SCHEMA` on the catalog to the app's service principal |
| AI functions fail as unavailable in this region | AI Functions are region-gated | Use a workspace in a listed region. No flag works around this |
| App deploys but the URL errors | Startup failure in the container | Read Logs on the app's page. Usually a dependency in `requirements.txt`, or the server not listening on `0.0.0.0:8000` |
| First statement is very slow | Cold warehouse | Press Go once before the audience arrives. The runbook covers the warm-up |

## Repo map

- `setup_databricks.py` — the zero-CLI installer notebook, run from a Git folder
- `install.py` — the one-command installer
- `app/` — FastAPI backend, pipeline, corpus generator, single-page frontend
- `guide/walkthrough.html` — visual walkthrough, cold workspace to documents processing
- `docs/RUNBOOK.md` — presenter script, beat by beat, with the reset checklist
- `docs/VALIDATION-PLAN.md` — how this was tested, and what is still open
- `databricks.yml` — asset bundle, for teams that deploy that way
