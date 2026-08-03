# DocFlow — Agent Bricks Document Intelligence, personalized for every customer
**Plan v3 — 2026-07-31 (Gary). Status: prototype artboards built (local HTML) + three-persona gauntlet run; awaiting JVG direction call. No production code yet.**
v1 → v2 amendments from JVG: preview/beta features encouraged (not GA-only) · UI-based as much as possible · per-deployment LLM customization (industry + company name at setup) · visually stunning and fun for business settings.
v2 → v3: Imagineer / Human Eye / Contrarian gauntlet outcomes folded in (act structure, profile certification gate, content guardrails, honest two-number install promise, platform-facts data file, visual-system rules). Prototype: `prototype/*.html`, screenshots `prototype/shots/`.
Research basis: `/tmp/databricks-research-agentbricks-doc-demo.md` (live-verified 7/31).

---

## 1. The goal

> **An SA or customer admin goes from install to a running, visually stunning, left-to-right document-intelligence demo in under 15 minutes with zero notebooks — and during setup types an industry and company name, so the demo that appears is *their* demo: their document types, their extraction schemas, their story. The newest Agent Bricks experiences (Beta/Preview included) are the show floor; the app guides turning them on instead of hiding them.**

Success criteria:
1. Honest two-number install promise (v3): **≤15 min to a running demo on the always-available floor; a measured, published number (target ≤45 min) to the full preview show floor** including Previews-page flips and live brick creation. Zero notebooks, UI-first (CLI is the alternative). Gate: someone who is not the author executes the full path in a fresh workspace and the README publishes their timing.
2. **Personalization:** industry + company name (+ optional notes) → LLM against AI Gateway generates the entire demo profile: doc taxonomy, synthetic corpus, extraction schemas, judge rubric, Genie/KA sample questions, narrative copy. Multiple saved profiles per install — one deployment, many customers.
3. Preview-forward: demo script features Agent Bricks bricks + the new document-analysis UIs; app detects what's enabled and guides enabling the rest (Previews page walkthrough). Still degrades to an AI-Functions-only mode when a workspace can't get previews (region gaps) — the show must go on.
4. Runs 100% inside Databricks; three doc situations supported (all/some/no docs).
5. Looks and feels like something you'd proudly project in a boardroom: motion, polish, fun without gimmicks.

## 2. Two-surface experience (the "UI based" principle)

The demo deliberately plays across two surfaces:
- **The app** — the narrative canvas: animated left-to-right flow, review queue, payoff wall, story mode. Everything a customer watches.
- **The real Databricks product UIs** — where the magic is *made*: Agent Bricks creation flow (declare task + examples → auto-optimized agent), the Classification UI and Information Extraction UI (Public Preview), Genie, AI Gateway config. The app deep-links into each at the scripted moment and detects when the created object appears (poll serving endpoints / resources), so the SA can build a brick live in ~3 minutes mid-demo and watch the app light up with it.

Rule of thumb: **code and SQL are plumbing, never the pitch.** AI Functions still power parse/mask/fallbacks under the hood, but the story is told through product UIs and the app's canvas. (Story mode keeps a "how it works" flip-side per stage for technical audiences.)

## 3. The demo narrative (left → right)

**"Your document inbox is a firehose. Watch {Company}'s lakehouse sort it out."**

```
 INBOX             PARSE                LABEL                      LANES                          PAYOFF
 UC Volume     →   ai_parse_document →  Labeling agent        →   ┌ EXTRACT → typed Delta ┐  →   One chat box:
 ({Company}        layout/tables/       (Agent Bricks IE/          ├ AUDIT   → judge +     │      Supervisor routes to
  branded docs:    markdown out of      Classification UI,         │           review queue │      Genie (structured) or
  uploaded or      PDFs & scans —       fallback ai_classify):     ├ SECURE  → ai_mask +   │      Knowledge Assistant
  generated)       shown as overlay)    type + sensitivity         │           locked zone  │      (docs, w/ citations)
                                        → routing decision         └ ARCHIVE → (neither)   ┘      + cost & lineage board
```

Routing matrix is generated per customer profile and editable in the UI. The generic default (mixed back-office) demonstrates all lanes: invoices→extract; contracts→extract+audit; claims→both; HR/medical/bank→secure (extract on redacted copy); junk→archive ("sometimes neither").

**Act structure (v3 — the bookend).** The demo is a three-act trick, not a tour:
- **Act 1 · The wager:** cold-open by asking the finale question into the one-chat-box while the system holds zero docs; it honestly returns "no tables exist yet." State the promise. Announce the planted story ("we hid a Line 3 drift story in this synthetic corpus — let's see if the pipeline finds it").
- **Act 2 · The build:** corpus generation (narrated designer + title-card re-skin), pipeline runs, live brick creation in the product UI, re-score moment (confidence bars flip, one doc changes lanes — fallback vs brick on screen simultaneously), exec drop-zone beat ("hand me one of YOUR PDFs" — full-screen drop target, parses live, routes honestly).
- **Act 3 · The prestige:** re-ask the identical question; answer lands with wall-clock receipts from run_metrics (asked cold 9:41 → table live 9:44 → answered 9:51). Verify it once more in Genie's own UI (product surface, not our chrome). Close on the money board: **Caught $3,310 · Cost $0.61**.
- Ops: run-of-show beat rail with hotkeys, one-key clean reset between shows.

Scripted beats:
1. **Generate {Company}'s inbox** (or point at their volume) — docs pour into the canvas.
2. **Parse** — pull one doc open, show the layout overlay (tables found, structure recovered from a scan).
3. **Create the brick live** — deep-link to Agent Bricks IE / Classification UI, declare the task with a few labeled examples, come back; the app detects the new endpoint and swaps the lane from "fallback primitive" to "auto-optimized agent" with a visible quality/latency delta. *This is the Agent Bricks pitch in one moment.*
4. **Lanes run** — extraction diff view, judge findings with a human approve/override, redaction preview sliding a doc into the locked zone.
5. **Payoff** — ask the one chat box questions; Supervisor picks Genie for "total exposure by vendor this quarter?" and KA for "what does the Miller contract say about termination?" Cost/lineage board closes: every doc's journey + what it cost.

## 4. Per-customer demo designer (the new core feature)

Setup wizard asks: **industry**, **company name**, optional freetext ("they're a HVAC manufacturer, care about warranty claims and supplier quality docs"). Then a **designer agent** (user-picked FM endpoint via AI Gateway) generates a versioned **demo profile** (JSON in a table):

- Doc taxonomy (5–8 industry-true types: e.g. manufacturing → supplier invoices, POs, quality inspection reports, safety incident reports, warranty claims, MSDS sheets, shipping manifests, marketing junk)
- Per-type extraction schemas (fields that matter to that industry)
- Routing matrix + sensitivity rules
- Synthetic corpus briefs (content spec per doc; realistic vendors, part numbers, dates)
- Audit-judge rubric per lane (e.g. warranty claim: coverage window math, serial-number format, claim-vs-invoice cross-check)
- Genie + KA sample questions; story-mode copy in the customer's vocabulary; app title/accents ("{Company} Document Intelligence")

Corpus generator renders the docs to PDF in-app (reportlab) with the company name — **every generated doc carries a visible "SYNTHETIC DEMO DATA" watermark + footer**. Non-negotiable: fake invoices bearing a real company's name must be unmistakably fake at a glance. No logo scraping; name + palette accents only.

Profiles are first-class: save, duplicate, edit (taxonomy/matrix editors), switch instantly. An SA keeps "Acme Manufacturing", "Meridian Health", "generic back-office" side by side in one deployment. Profile switch re-skins narrative + regenerates or re-points the corpus.

**Profile certification gate (v3, from the Contrarian — mandatory).** A freshly generated profile is an unrehearsed 5-hop stochastic chain (designer LLM → synthetic PDFs → parse → extract → Genie NL2SQL). So: after generation, the app auto-runs the FULL pipeline on the new corpus AND executes every scripted question end-to-end. Demo mode stays locked until every check is green. The certification checklist is itself a visible surface ("the demo rehearses itself") and includes the content-guardrail checks. No profile presents to a customer uncertified.

**Designer content guardrails (v3 — non-negotiable, in the designer prompt + cert checks):** fictional people and vendor names from a curated fake-name pool; canonical fake PII values only; no narratives that imply the customer's actual record (incidents happen at fictional sites); company name and palette accents only, never logos; every generated page watermarked SYNTHETIC DEMO DATA.

## 5. Architecture

**Stack:** one Databricks App — React (Vite) SPA + FastAPI backend (serves static build + REST/SSE). Bound resources: serverless SQL warehouse, UC volume, serving endpoint(s), optional genie-space, optional brick endpoints. All DAB-expressible; also creatable via UI.

**Capability model (preview-forward, detect-and-guide):**
- **Show floor (Beta/Preview encouraged):** Agent Bricks Information Extraction brick, Classification/IE document UIs (Public Preview), Knowledge Assistant (GA), Supervisor (GA; API Beta) for the one-chat-box finale, ai_prep_search (Beta) if we add a RAG beat.
- **Plumbing (GA):** ai_parse_document, ai_mask, ai_extract/ai_classify/ai_query, Delta, UC governance.
- **Fallback mode:** where previews aren't available, lanes run on plumbing alone — demo still complete, story mode says so honestly.
- App maintains a **capability panel**: green = live, amber = one UI toggle away (deep-link + instructions), grey = unavailable in this region. Enabling previews is part of the guided setup, not a blocker buried in a README.

**Data model** (`{catalog}.{schema}`): `documents` (registry + per-stage status), `demo_profiles`, `routing_rules`, `extract_*` per type, `audit_findings`, `review_decisions`, `run_metrics` (latency + cost per doc). Volume: `inbox/ processed/ secure/ archive/ generated/`.

**Models:** dynamically listed FM endpoints (49 live in JVG's workspace incl. Claude Opus 5, GPT-5.6, Gemini 3.6 — never hardcoded). Designer/judge/generator model user-selectable; AI Gateway page tells the governance story (one door, tracking, rate limits, guardrails, UC-permissioned AI Functions).

**Maintenance architecture (v3, from the Contrarian):** every product name, GA/Beta/Preview status, deep-link URL, and narrative product claim lives in ONE data file (`platform_facts.json`, versioned, loaded at runtime) — when Databricks renames something (Genie Spaces → Genie Agents happened mid-July), one file changes, not scattered copy. **Animation-truth rule:** the canvas replays recorded run_metrics events with real timestamps; it never simulates activity that didn't happen. Measured end-to-end corpus timing is a P1 exit criterion.

## 6. Visual bar ("stunning and fun, business-appropriate")

- **Motion as meaning:** documents are physical objects flowing the canvas; lane hand-offs, parse "unfolding", redaction "sealing" into the locked zone — animation communicates state, never decorates idly.
- **Databricks brand system** (standing rule): #FF3621 / #1B3139 / #EEEDE9, Lava gradient accents; light + dark; dark is the projector default.
- **Demo mode:** full-screen canvas, big type, presenter hotkeys (release batch, slow-mo a single doc, jump to beat), calm idle state so it looks alive on a booth screen.
- **Fun, tastefully:** doc-type iconography, satisfying completion ticks, live counters, one earned flourish when a batch clears. No confetti cannons in a compliance meeting.
- Design pass with the app-ui-ux-designer / app-review-council skills before P5; screenshot-verified.
- **Visual-system rules locked by the Human Eye pass (v3):** type floor ~13px for load-bearing info in the build (routing chips, rail detail, attributions); red does one job per screen (brand/primary + alarm; secure lane is blue, generate actions are neutral); one primary CTA per screen; no ellipsis truncation on demo surfaces — copy is written to fit; topology (belts/branches) must be the most legible layer on the canvas; no decorative element may be the brightest object on screen.

## 7. Setup UX

**Install (UI-first):** README with screenshots — workspace Git folder (repo URL) → Apps → Create custom app → pick source folder → bind warehouse/volume/endpoint on the create screen → open app. CLI alternative: `databricks bundle deploy -t demo` (one command, creates schema/volume/bindings too). Marketplace = future option (Public Preview, partner-shaped, closed-source containers — parked).

**Prereqs (honest list):** serverless SQL in an AI Functions region · can create an app + CREATE SCHEMA on a catalog · (encouraged) workspace admin able to flip Agent Bricks previews — the app's capability panel walks through it.

**First-run wizard:** env probe (1-row ai_classify + endpoint list) → catalog/schema → **industry + company name → designer agent builds the profile** → docs (generate / upload / point at volume) → model picks → capability panel → go. Re-runnable; no notebooks anywhere.

## 8. Risks & mitigations
| Risk | Mitigation |
|---|---|
| Preview gating varies by workspace/region | Capability panel + fallback mode; enabling previews is a scripted UI step |
| Real company name on fake docs | Mandatory SYNTHETIC DEMO DATA watermark; no logos; name only |
| Designer-agent output quality varies | Profile is editable + versioned; ship 3 curated reference profiles as quality anchors; regenerate per-section |
| Brick creation mid-demo takes >3 min (optimization time) | Script supports pre-staged brick; live creation is the encore variant; detection poll makes either work |
| App auth/env details not fully public-documented | Verify injected vars + app-SP permissions live at P0 in JVG's workspace |
| Model churn | Dynamic endpoint listing everywhere |
| Cost honesty | run_metrics board + README note (~$1/1k pages parse + per-token calls) |

## 9. Build phases (on JVG go)
- **P0** Skeleton: bundle + app shell + brand system + deploy to JVG workspace; verify auth/ingest/deep-link patterns; capability detection working.
- **P1** Pipeline core + flow canvas (generic profile): intake → parse → label → route, live statuses.
- **P2** Lanes: extract→Delta, judge + review queue, secure zone.
- **P3** Demo designer: profile generation, corpus generator + watermarking, profile switcher.
- **P4** Payoff: Genie binding, KA + Supervisor one-chat-box, cost/lineage board; brick-detection swap + re-score moment; bookend receipts; profile certification gate.
- **P5** Polish + hardening: demo mode + run-of-show ops, design-council pass, README/SA runbook, independent fresh-workspace timing test (two-number promise), multi-model red-team, E2E dry run. **Story mode ships here and is scope-gated: it builds only once a second user (an SA other than JVG) is named — until then the demo narrative lives in the runbook.**

## 10. Standing calls (JVG can override)
1. Default profile = mixed back-office; industry profiles via designer agent (that's now the headline feature).
2. Genie + KA + Supervisor one-chat-box finale in scope — it's the closer.
3. Working name "DocFlow" — rename welcome.
4. Repo home TBD (GitHub org/visibility) before distribution.
5. Watermark rule on generated docs — treating as non-negotiable unless JVG objects with an alternative safeguard.
6. **The Contrarian's unanswered question (JVG's to answer): who is the second user?** Which SA besides you will run this with a real customer in the next 60 days? If the honest answer is "nobody yet," we build the two-surface core (canvas + designer) for your own meetings first and defer the SA-distribution apparatus (story mode, install screenshots doc) until that person exists. Repo home + maintainer should be decided before P0 either way.
