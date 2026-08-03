# DocFlow, end to end in a cold workspace

Install, clear the prerequisite checks, configure the demo, and process
documents. Written for a workspace with nothing in it.

Your workspace is in exactly that state right now: no app, no warehouse, no
schema, no agents.

---

## Step 1 · Install the app

Two commands. The first creates the app and its identity, the second uploads the
code and starts it.

```bash
cd ~/projects/agentbricks-doc-demo && databricks apps create docflow
```

```bash
cd ~/projects/agentbricks-doc-demo && databricks sync app /Workspace/Users/jvangordon@gmail.com/docflow-app --full && databricks apps deploy docflow --source-code-path /Workspace/Users/jvangordon@gmail.com/docflow-app
```

Creating the app takes a few minutes because Databricks provisions compute for
it. When it finishes you get the URL.

## Step 2 · The one admin step

A brand new app gets a brand new service principal with no rights to anything.
Two grants let it fix the rest by itself. Run this once:

```bash
cd ~/projects/agentbricks-doc-demo && ./.venv/bin/python docs/grant_app.py
```

That script does two things and prints what it did:

- gives the app's identity the **Allow cluster creation** entitlement, so the
  warehouse fix button works
- grants **USE CATALOG** and **CREATE SCHEMA** on the `workspace` catalog, so the
  catalog fix button works

If you skip this step the app still runs and still tells you the truth. The
checks simply cannot self-repair, and the readiness panel shows you the manual
steps instead.

## Step 3 · Open the app and read the checks

Open the URL. You land on **Start**. The right side is the readiness panel and it
should be unhappy, which is the point.

Expect roughly this:

| Check | State | Why |
|---|---|---|
| App identity resolves | pass | the app can authenticate |
| **Serverless SQL warehouse** | **fails, required** | nothing exists yet |
| **Catalog workspace.docflow** | **fails, required** | schema was never created |
| **Document volume writable** | **fails, required** | volume lives inside that schema |
| Foundation models reachable | pass | 49 pay per token endpoints |
| **Knowledge Assistant** | absent, optional | created on go, or now with a button |
| Information Extraction agent | absent, optional | no create API exists, steps shown |
| **Document Intelligence functions** | not tested, required | waits for a warehouse |
| Billed usage | informational | Databricks manages this schema |

Two things to notice before you touch anything:

- **Go is disabled**, and the sentence beside it names the blocking checks.
- The Document Intelligence check shows a greyed **"after Serverless SQL
  warehouse"** instead of a button, because testing it needs compute that does
  not exist yet. The app will not offer you a control that cannot work.

The legend under the heading explains the symbols: ✓ passing, ! blocks go,
? not tested yet, ○ optional and not present.

## Step 4 · Press the fixes, top down

Order matters, and the panel enforces it.

**1. Serverless SQL warehouse → "Create one"**
Creates a 2X-Small serverless warehouse that stops itself after 10 idle minutes.
Takes about a minute. Watch two things happen: the check turns green, and the
Document Intelligence check below it stops saying "after Serverless SQL
warehouse" and validates itself, because now there is something to test on.

**2. Catalog workspace.docflow → "Create schema"**
Creates the schema the run writes into.

**3. Document volume writable → "Create volume"**
Creates the volume and its inbox, processed, secure, archive and generated
folders.

**4. Knowledge Assistant → "Create now"** *(optional)*
You can skip this. Go creates the assistant anyway. Pressing it early just means
the document index starts sooner, so cited answers are ready earlier.

If any fix fails, the message leads with what to do about it, and the platform's
own wording sits behind a **"what Databricks reported"** disclosure.

Press **Re-check** when you are done. You want **6 of 6 required**.

## Step 5 · Configure the demo

Left side, four answers:

1. **Customer name** — appears on every page and inside every generated document
2. **Industry** — drives the vocabulary, the suggested questions, and the titles
   of both operations pages
3. **Catalog and schema** — where everything the run creates will live
4. **Documents** — leave as *No customer documents* to generate everything, or
   pick a volume of the customer's own PDFs and the run will inventory them and
   generate only what is missing

Press **Save**. It flashes *Saved ✓*.

Try something other than Manufacturing if you want to see the personalisation
work. Insurance produces "Loss Run Review" and vocabulary like subrogation and
loss run. Logistics produces "Freight Claims Recovery Desk".

**Go is now enabled.** Its message changes to say setup can be re-run safely.

## Step 6 · Press Go and watch

The run log takes over the right side and streams with real timings. About two
minutes:

| At | Step |
|---|---|
| ~0s | serverless warehouse confirmed |
| ~8s | schema, volume, tables |
| ~16s | company research, via a model on the AI Gateway |
| ~34s | documents generated, watermarked, into their own folder |
| ~35s | Knowledge Assistant created, indexing starts in the background |
| ~36s to ~120s | documents processed: parse, classify, route, extract, audit, secure |
| ~120s | Genie space created over the extracted tables |
| ~120s | **Ready** |

Switch to **Flow** while it runs. Documents move from the inbox through the
classifier into four lanes. Click any document to see its routing decision
record, including the sentence explaining why it went where it went.

## Step 7 · The payoff

**Ask** — one box, two engines. A question about numbers goes to Genie over the
extracted tables and comes back with the SQL it ran. A question about wording
goes to the Knowledge Assistant and comes back citing a document and page. The
suggestions under the box are generated for your industry and are guaranteed
answerable from the data this run produced.

**Claims** and **Suppliers** — the two operations screens, titled for the
industry you chose, built on the governed tables the run created.

**Built** — everything the run made, with per section timings.

## Step 8 · Stand it down

Nothing bills while idle: the warehouse stops itself after 10 minutes and
Databricks stops the app 24 hours after deploy. To stop immediately:

```bash
databricks apps stop docflow && databricks warehouses list -o json | python3 -c "import json,sys,subprocess; [subprocess.run(['databricks','warehouses','stop',w['id']]) for w in json.load(sys.stdin)]"
```

---

## If something goes wrong

**A fix button fails with a permissions message.** The app identity is missing a
grant. Re-run step 2, or follow the numbered steps shown under the check.

**Go stays disabled.** Read the sentence beside it. It names the exact checks
that are blocking, and every one of them is above it in the panel.

**The run stops partway.** The log marks the failing step and shows what the
platform said. Fix it and press Go again; the run adopts anything that already
exists rather than duplicating it.

**Pages show numbers from an earlier run.** Every results page states which run
its figures came from, or says plainly that they came from an earlier session.
