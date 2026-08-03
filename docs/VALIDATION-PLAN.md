# DocFlow validation plan

What has to be true before an SA takes this into a customer workspace, how each
claim gets proven, and what counts as evidence. Written so someone other than
the author can execute it.

**Principle:** a test that cannot fail proves nothing. Every capability below is
validated by first *breaking* it, confirming the app says so honestly, then
repairing it and confirming the app agrees.

Status legend: **[done]** proven already · **[partial]** proven in simulation
only · **[todo]** not yet run.

---

## L0 · Static and unit, no compute, seconds

| # | What | How | Pass criteria | Status |
|---|---|---|---|---|
| 0.1 | Python and JS parse | `ast.parse`, `new Function` on the SPA script | no syntax errors | done |
| 0.2 | Readiness failure injection | `app/test_readiness.py` | every check goes red under its own failure; all 9 always emitted; each failure carries a remedy | done, 16/16 |
| 0.3 | No dead remedies | test asserts advertised `fix_endpoint` exists as a route | zero dead buttons | done |
| 0.4 | Corpus determinism and content rules | `app/test_corpus.py` | 24 PDFs, byte-identical across runs, planted story exact, watermark on every page, fake PII canonical | done |
| 0.5 | SQL guard | attack corpus vs `guard_select` | 10 attacks blocked, 6 legitimate pass | done |
| 0.6 | Lane policy | `lane_for` truth table | 5 routing outcomes correct and deterministic | done |
| 0.7 | Error sanitiser | `_clean` on real platform errors | no host, account id, or request id reaches the UI | done |
| 0.8 | Config round trip | POST every field, GET it back | catalog, schema, volume, model, company, industry all persist | done (found: pydantic was dropping four fields) |

## L1 · API contract, local server with real credentials, minutes

| # | What | How | Pass criteria | Status |
|---|---|---|---|---|
| 1.1 | Every endpoint answers | curl each route on local uvicorn | 200 with expected shape; no 500 | done |
| 1.2 | Empty-state honesty | call data endpoints before any run | empty results, never fabricated rows | done |
| 1.3 | Compute discipline | call `/api/metrics`, `/api/readiness` with warehouse stopped | no warehouse is started; response says why | done (found: metrics used to auto-start it) |
| 1.4 | Run concurrency | POST `/api/go` twice quickly | second returns 409, one run only | partial, code path only |
| 1.5 | Ask routing | numbers question and wording question | routes to Genie and to the assistant respectively | done |
| 1.6 | Ask fallback | ask with the Genie space absent | answers via governed SQL, labelled honestly, never errors out | todo |

## L2 · Prerequisite fail-and-repair, real workspace, the core of this plan

For each check: break it, confirm red plus correct remedy, apply the remedy,
confirm green, confirm Go unlocks.

| # | Check | How to break it | Expected remedy | Status |
|---|---|---|---|---|
| 2.1 | Serverless warehouse | delete every serverless warehouse | button creates a 2X-Small, auto-stop 10 min | **done, real** |
| 2.2 | Target catalog | point config at a catalog that does not exist | button runs `CREATE CATALOG` and `CREATE SCHEMA` | **done, real** |
| 2.3 | Schema missing | catalog exists, schema does not | same button, creates schema only | partial, simulated |
| 2.4 | Catalog permission denied | revoke the app SP's grants on the catalog | red, with the exact GRANT statement to run | todo |
| 2.5 | Document volume | delete the volume or its folders | button recreates schema, volume, zone folders | todo |
| 2.6 | AI Functions | warehouse stopped, then absent | button starts and tests; when nothing exists to start it must say so and defer to 2.1 | **done, real (found: it reported false success)** |
| 2.7 | Knowledge Assistant | delete the assistant | button creates it and attaches the volume source | todo |
| 2.8 | Extraction agent | none present, no create API exists | link plus three numbered steps, marked optional | done, browser |
| 2.9 | Foundation models | simulate denial | red with a link to Serving, no false button | partial, simulated |
| 2.10 | Billed usage | read real system schema state | reports the platform's own answer; no button where the platform forbids it | **done, real** |
| 2.11 | Identity | simulate auth failure | red with restart instructions | partial, simulated |
| 2.12 | Go gate | leave one required check red | Go disabled and names the blocking check | done, browser |
| 2.13 | Dependency order | no warehouse present | dependent check shows "after Serverless SQL warehouse", not a dead button | todo, browser |

## L3 · Portability, the actual product promise

The app claims to install into *any* workspace. That is only proven somewhere
it has never run.

| # | What | How | Pass criteria | Status |
|---|---|---|---|---|
| 3.1 | Cold install | fresh workspace, no catalog, no warehouse, no agents | clone, deploy, open, four answers, Go, documents flowing | todo |
| 3.2 | App service principal permissions | the whole L2 sequence executed *as the app*, not as an admin user | every fix button works with only the app's own grants | **todo, highest value** |
| 3.3 | Second SA, same workspace | two installs side by side | name collisions avoided, neither breaks the other | todo |
| 3.4 | Idempotent rerun | press Go twice | adopts existing assets, no duplicates, no errors | partial |
| 3.5 | Teardown | remove agents, tables, volumes, Genie space | workspace returns to its prior state | todo, not built |
| 3.6 | Restart resilience | restart the app mid-run | state reports honestly rather than showing a half-run as complete | todo, known weakness |

## L4 · Demo rehearsal, browser, SA point of view

| # | What | Pass criteria | Status |
|---|---|---|---|
| 4.1 | Full walkthrough, all seven screens | no error boxes, no dashes where numbers belong, no empty hero | done, 4 passes |
| 4.2 | Numbers reconcile across pages | caught figure identical on Flow, Genie answer, and Claims | done |
| 4.3 | Coverage arithmetic | day counts verified by hand against source dates | done |
| 4.4 | Answer quality | Genie shows SQL and headers; assistant cites a document and page | done |
| 4.5 | Live run visible | log streams above the fold while the run works | done, found and fixed |
| 4.6 | Customer documents path | point at a real volume of customer PDFs | inventoried, gaps generated, never modified | **todo, never tested** |
| 4.7 | Industry variation | run as Insurance and as Healthcare | vocabulary, questions and both use-case pages change coherently | **todo, never tested** |

## L5 · Non-functional

| # | What | Pass criteria | Status |
|---|---|---|---|
| 5.1 | Time to ready | under 4 minutes from Go | done, 113 to 144s across 4 runs |
| 5.2 | Per-section timings | published and reproducible | done |
| 5.3 | Idle cost | nothing runs after a demo | done, warehouse auto-stops, app stops |
| 5.4 | Cost honesty | estimate labelled as estimate unless billed usage is readable | done |
| 5.5 | Secrets and identifiers | no host, account id, token, or request id in any UI string | done, sanitiser added |
| 5.6 | Deployable hygiene | only shippable files sync | done, 11 files, 372K |

## L6 · Content honesty, the reputational risk

| # | What | Pass criteria | Status |
|---|---|---|---|
| 6.1 | No fabricated numbers | every figure traceable to an API response | done |
| 6.2 | Synthetic documents unmistakable | watermark on every generated page, fictional vendors and people, canonical fake PII | done |
| 6.3 | Customer files untouched | read-only, copied not modified | asserted, **todo to prove** |
| 6.4 | Product names and statuses accurate | matches current Databricks docs at demo time | needs re-verification each cycle |
| 6.5 | No capability claimed that is not wired | UI never implies an agent exists when it does not | done, was violated twice and corrected |

---

---

## Execution log

**Phase A · L2 remainder, live workspace — 13/13 passed.**
Volume deleted, went red, repaired by the app. Schema missing, went red, created.
Knowledge Assistant deleted, went red, recreated by its own button. Ask fell back
to governed SQL and said so. Customer PDFs verified byte-identical after use.
*Found:* recreating the assistant mints a new endpoint id, which leaves the
deployed app's bound resource stale. Re-granted and rebound.

**L4.7 · industry variation — FAILED, then diagnosed.**
Insurance, Healthcare and Manufacturing all produced the same generic tagline
with no vocabulary and no page titles, because company research needs a warehouse
and none existed. The run correctly continued, but the personalisation claim
disappeared with only a log warning. *Fixed:* the theme now records whether it
was researched or generic, and the operations pages say "generic wording" when it
was not personalised. Re-test still owed once a warehouse exists.

**L3.2 · app service principal, cold workspace — the decisive test.**
Readiness read correctly (4 of 6 required, legend visible, dependency shown as
"after Serverless SQL warehouse" with no dead button), Go stayed disabled naming
both blockers, and the empty pages agreed with each other. Then the key result:
**the app's service principal was not authorised to create a SQL warehouse.**
Everything validated before this point had been validated with admin rights.
*Fixed:* granted the service principal the cluster-creation entitlement, rewrote
the failure so the instruction leads and the platform's wording sits behind a
disclosure, sanitised host and account identifiers out of user-facing errors,
replaced developer env-var language on the Claims page, and added the exact
admin steps to the warehouse check.

**L3.2 re-test after the entitlement grant — PASSED, full self-repair.**
Cold workspace, no warehouse. One press of "Create one" provisioned a serverless
warehouse in 57s, the dependent check went green on its own, Go unlocked at
6 of 6 required, and the run completed in 133.5s with company research
personalising both operations pages. No console visit, no manual SQL.
*Presentation defects found and fixed:* a finished step kept its in-progress
marker (steps now update their own line instead of appending a second), the run
log header stayed on "working" after Ready (full re-render on completion), and
a raw internal field surfaced as "created true".

**L4.7 re-run with a warehouse — PASSED after a prompt fix.**
Vocabulary overlap between Insurance, Healthcare and Manufacturing measured at
0%, and all three sets of questions were distinct. One miss: every industry
returned the same page titles, because the prompt itself suggested the words
"claims operations" and "supplier operations". After rewriting it to demand
industry-specific wording: Insurance gives "Loss Run Review Desk" and
"Vendor Invoice Audit Queue", Healthcare gives "Prior Authorization Review Desk"
and "Provider Invoice Reconciliation".

**Trap suite, backend — 14/14.**
Five hostile questions through the ask box, including a DROP TABLE instruction
and a cross-catalog read of main.hr.salaries, were all refused with the claims
table intact afterwards. An unanswerable question produced an honest refusal
rather than an invented figure. A company name containing script tags and quotes
stored safely and still generated 24 documents; an invalid accent colour was
rejected. Two simultaneous presses of go were accepted exactly once. A malformed
PDF parsed without stopping the run.

**Known limitation surfaced during trapping.** Two runs against the same catalog
and schema at the same time, from different app instances, will collide: the
extract tables are rebuilt wholesale each run. Two SAs demoing into one workspace
need separate schemas. This is L3.3 and remains unaddressed.

**Trap gauntlet, browser, presenting as an SA — 11 traps, 6 impressive,
4 acceptable, 1 embarrassing.**

Survived without help: a double press of go (second refused, one run only), a
hard refresh mid-run (full recovery, run state is server side), page-hopping
during a run, and a re-run that was byte-for-byte idempotent. The three
adversarial questions produced the best available outcomes: a calm refusal of a
DROP TABLE instruction, an honest "there is no employee data in this schema",
and a supplier total that reconciled with the Suppliers page exactly.

The embarrassing one, and the most valuable finding of the whole exercise:
**the app offered suggested questions its own data could not answer.** After a
logistics run it proposed asking about demurrage charges by port and carrier;
clicking it returned "no available columns or data related to demurrage". A
presenter following the app's own suggestion hit a dead end on stage.
*Fixed:* the research prompt now receives the real column list and is required
to write questions answerable from it. Re-tested across Logistics and Insurance:
six suggestions, zero dead ends.

Also fixed from the gauntlet: the Flow board showed the previous run's finished
results under a live header for the first 35 seconds of a new run (state is now
cleared when go starts); results pages carried no provenance, so an old run and
a fresh one looked identical (each now states which run and what time, or says
plainly that the data came from an earlier session); and the Claims total was a
penny off Genie's because rows were rounded before summing (now summed exactly
and shown with cents).

**Honest gap confirmed by the gauntlet:** personalisation is real in the
vocabulary, questions and page titles, but the documents themselves are the same
back-office pack every time. The log used to call them "themed PDFs"; it now says
they are named for the customer, which is what is actually true. Generating
genuinely industry-specific document content remains unbuilt.

## Execution order

1. **L2 remainder** (2.3 to 2.7, 2.13) — the prerequisite promise, half proven.
2. **L3.2 app-service-principal run** — the single highest-value gap: everything
   proven so far was proven with admin rights, and an SA's app will not have them.
3. **L4.6 and 4.7** — customer documents and a second industry, both untested and
   both core claims.
4. **L3.1 cold install** in a second workspace — the portability claim.
5. **L3.5 teardown** — not built yet; decide whether to build or drop the claim.

## Known gaps to state plainly

- Run state lives in app memory; an app restart empties the boards until Go runs again.
- Teardown is described in the UI but not implemented.
- The corpus is a manufacturing pack themed by company name; genuinely
  industry-specific document *content* is not yet generated.
- Everything proven to date was proven in one Free Edition workspace, by an
  admin identity. Neither condition matches an SA in the field.
