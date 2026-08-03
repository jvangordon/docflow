# DocFlow Presenter Runbook

For the SA (or JVG) running DocFlow in front of customer executives. This is the show. Install is the README's job: workspace Git folder or `databricks bundle deploy -t demo`, then the first-run wizard. This document starts where the install ends, with the app open and a certified profile ready.

Written against PLAN v3 and certified reference run #38. Every number in this script comes from that run. Your run will produce its own numbers, and the rule is simple: say what is on the board, never what is in the script.

---

## 1. The cold read

DocFlow is a Databricks App that turns a pile of documents into governed tables and cited answers while the customer watches. It runs entirely in the customer's workspace, on their own serverless warehouse and under their Unity Catalog permissions. Nothing on screen is simulated. The canvas replays recorded pipeline events, and every dollar figure comes from the run_metrics table.

The demo is a wager, not a tour. Minute one, you ask the finale question and the system honestly answers that no tables exist yet. Ten minutes later you ask the identical question and it answers with wall-clock receipts. In between, the audience watches the machine get built. Documents are generated with a visible SYNTHETIC DEMO DATA watermark. A scanned page becomes structured layout in front of them. A judge catches a $2,140 warranty claim that failed 137 days after coverage ended, and a human decides what happens to it. A medical file is masked and moved behind a group grant before anyone reads it. Mid-show, you build an Agent Bricks agent in the real product UI, and the app visibly re-scores when it comes online.

What a VP should believe on the way out:

1. Scanned paper became queryable Delta tables using SQL functions that are GA today. No notebooks appeared at any point.
2. Building a document agent is a product UI task with a handful of labeled examples, and the quality delta is measurable on screen, 0.71 to 0.94 in the reference run.
3. Judgment stays human. The audit lane flags and a person confirms or overrides. The decision is written down with a name and a reason.
4. Sensitive documents are masked before extraction and locked behind Unity Catalog grants, not app logic.
5. The finale is verifiable in Genie, Databricks' own UI. The answer does not depend on demo chrome.
6. Cost stays on the board the whole time. The reference run caught $3,310 in bad claims and cost $0.61 to run.

You never overstate a release status (crib below), and you never say a number the board does not show. Above all, no uncertified profile goes in front of a customer. The app rehearses itself. Certification runs the full pipeline plus every scripted question end to end, and demo mode stays closed until every check is green.

### Status crib (never misstate one of these)

| Thing on screen | Status you say | Basis |
|---|---|---|
| ai_parse_document | GA, all three clouds | GCP release note 4/16/2026; AWS/Azure docs |
| ai_classify, ai_extract | GA | AI Functions docs; 7/15/2026 note (default-on for compliance workspaces) |
| ai_mask | Available AI Function; attach no badge | AI Functions docs |
| Agent Bricks Information Extraction brick | Beta, preview-gated per workspace | AWS Agent Bricks docs table |
| Classification UI, Information Extraction UI | Public Preview | Azure release notes, March 2026 |
| Knowledge Assistant | GA | KA GA blog (+10 regions) |
| Supervisor Agent | GA product, Beta API | Supervisor GA blog; API at ai-gateway/mlflow/v1/responses |
| Genie | GA; renamed Genie Agents 7/8/2026; PAYG after 7/31/2026 with 150 free DBUs/month | July 2026 release notes |
| ai_prep_search | Beta | AI Functions docs |
| AI Functions compute | Serverless only, never Pro or Classic warehouses | AI Functions docs |
| Restrict AI Functions via UC permissions | Public Preview 7/8/2026 | July 2026 release notes |
| Brick creation | UI only, no API or Terraform path; consumed as standard serving endpoints | Agent Bricks docs |

If asked whether "Document Intelligence" is GA: the platform capability was declared GA in the DAIS 2026 blog, and the Information Extraction brick itself still carries a Beta label in the docs. Say both halves.

---

## 2. Run of show

Rule zero: no uncertified profile in front of a customer. If today's profile shows anything but green, present the generic certified profile instead. A weaker skin beats a broken show.

The beat rail at the bottom of the canvas numbers the beats and carries the reset control at its right end. Rehearse with the rail until you can jump beats without looking down.

### 12-minute version (pre-staged brick)

| Start | Length | Beat |
|---|---|---|
| 0:00 | 1:00 | 1. Cold open wager |
| 1:00 | 1:30 | 2. Generate the corpus |
| 2:30 | 2:30 | 3. Pipeline run |
| 5:00 | 1:30 | 4. Audit review, the $2,140 claim |
| 6:30 | 0:45 | 5. Secure zone |
| 7:15 | 1:45 | 6+7. Brick swap (pre-staged) and re-score |
| 9:00 | 2:00 | 9. The prestige |
| 11:00 | 1:00 | 10. Money board, stop talking |

Cut from this version: the designer walkthrough, live brick creation, the drop zone, and the Knowledge Assistant question. If an exec volunteers a PDF unprompted, take it and steal the time from beat 3.

### 25-minute version (live brick creation)

| Start | Length | Beat |
|---|---|---|
| 0:00 | 1:30 | 1. Cold open wager |
| 1:30 | 3:00 | 2. Designer profile and corpus generation |
| 4:30 | 3:30 | 3. Pipeline run |
| 8:00 | 2:30 | 4. Audit review, the $2,140 claim |
| 10:30 | 1:30 | 5. Secure zone |
| 12:00 | 3:30 | 6. Live brick creation in the product UI |
| 15:30 | 1:30 | 7. Re-score delta |
| 17:00 | 2:30 | 8. Exec drop zone |
| 19:30 | 3:00 | 9. The prestige, plus the contract question |
| 22:30 | 1:30 | 10. Money board close |
| 24:00 | 1:00 | Buffer. You will need it. |

---

### Beat 1 · Cold open wager

**You click:** Open on the Ask page, not the canvas. Type the finale question exactly: "What's our total warranty exposure from Line 3 units this quarter?"

**On screen:** The empty state. The chat answers that no tables exist yet. Inbox count is zero behind it.

**You say:**
> "Before I show you a single pixel of demo, I want to ask the question you actually came here with."
> "It says no tables exist yet. That's true. Nothing is staged behind this screen. Hold that question in your head, because in about ten minutes I'm going to ask it again, word for word."

**If it breaks:** The only failure here is a non-empty answer, which means you skipped the reset. Own it in one sentence ("this workspace already ran this morning, so you're seeing a spoiler") and reset from the rail; it costs 20 seconds. Prevention is the T-10 checklist, not talent. If a skeptic says it's staged, agree to let them re-ask the question in their own words at the end, then make sure you use the certified wording first.

---

### Beat 2 · Generate the corpus

**You click:** 25-minute version: show the setup screen first. The company and industry fields are already filled, along with the context note. Point at the profile output and the routing matrix, then at the corpus plan. Then to the canvas and press "+ Generate {Company} docs" on the inbox station. 12-minute version: skip setup, press generate, narrate over the 20 to 40 seconds it takes.

**On screen:** Documents pour into the inbox and the count climbs. The station notes that generated docs carry the SYNTHETIC DEMO DATA watermark. On the setup screen, the corpus plan openly lists the planted traps.

**You say:**
> "The app is about to write {Company}'s inbox for itself: supplier invoices, warranty claims, quality inspections, safety incidents, and some junk mail, because real inboxes have junk."
> "Look at any page. SYNTHETIC DEMO DATA, printed across the face. The vendors and the people are fictional, and the ID numbers are canonical fakes. Your name is the only true word on the paper."
> "And I'll confess to one thing up front. We buried a story in this stack. Somewhere on Line 3, quality has been drifting, and a couple of warranty claims in here are past their window. I am not going to point the system at any of it. Watch whether it surfaces on its own."

**If it breaks:** Generation is a live LLM call and can run slow. Fill with the watermark and guardrails talk; it is written to cover the wait. If the seed call fails outright, re-point at the last certified corpus already sitting in the volume and say so plainly: "we'll use the batch this profile rehearsed with." Never regenerate twice in front of the room.

---

### Beat 3 · Pipeline run

**You click:** Run pipeline. While parse is working, click the WC-2214 token as it crosses the belt to open its journey drawer. Let the drawer sit open while lanes fill.

**On screen:** The parse station scans with the beam animation and shows the orange box around a recovered table, cost line reading about $0.90 per thousand pages. The label station flips chips (Warranty Claim, confidence 0.97) with the fallback engine labeled underneath. Lanes fill left to right: EXTRACT with typed tables, AUDIT with a waiting count, SECURE, ARCHIVE. The journey drawer shows one document's whole life: parsed 3 pages and 2 tables, labeled, 14 fields extracted, flagged for audit.

**You say:**
> "This page was a scan a minute ago. ai_parse_document handed back its layout as data, and that orange box is the table it found. That is a GA SQL function running on the warehouse you already own."
> "Now watch the label chip. Warranty claim, confidence 0.97. A label here is a routing decision, and this document just earned itself an audit."
> "Four lanes, four levels of trust. The two interesting ones are audit, where a judge reads before money moves, and secure, where masking happens before anything else touches the file. And archive, because some mail is just mail."

**If it breaks:** First statement after an idle period can crawl while the serverless warehouse wakes; the T-10 probe exists to prevent this. If a document errors, the drawer shows the error honestly; narrate it as the audit trail working and pick the hero doc WC-2214, which certification already proved. If the whole run dies, do not restart in silence: the certification run's recorded data is still in the tables, so jump to beat 4 on that data and tell the room what you did. Weaker show, not a dead one.

---

### Beat 4 · Audit review, the $2,140 claim

**You click:** AUDIT lane, "Review queue". Select WC-2214. Walk the judge findings, then the extracted-fields-versus-source panel. Click "Confirm · route to claims."

**On screen:** The queue shows three waiting. The card: Warranty Claim at 0.97, claimed $2,140, Miller Tooling. Finding one shows the math: 2023-11-02 plus 24 months is 2025-11-02, failure 2026-03-18, 137 days past term, cross-checked against invoice INV-88213. The source snippet from the actual page sits below with the load-bearing phrases highlighted. Confirming raises a receipt with your name and reason.

**You say:**
> "Here's one the judge flagged. A warranty claim for $2,140. Purchased November 2023 with a 24-month term, so coverage ended November 2025. The unit failed in March 2026. That is 137 days past the window, and this claim was on its way to being paid."
> "The system doesn't pay it and doesn't reject it. It shows a person the math and the source page, and the person decides. When I click confirm, that decision is written down with my name and my reason, timestamped."
> To the room: "Would your AP team have caught that one on a Tuesday afternoon?"

**If it breaks:** Judge prose varies between runs; the arithmetic block does not, because it is computed from extracted fields. Read the math, not the prose. If the queue is unexpectedly empty, open the decided list and replay a decision, receipts and all. Do not re-run the judge live to force a finding.

---

### Beat 5 · Secure zone

**You click:** Back to the canvas. Click the SECURE lane item, the HR medical accommodation file.

**On screen:** The masked preview, nine entities obscured, the lane noting "sealed" into the locked path and "Grants: hr_admins only."

**You say:**
> "This file is an HR medical accommodation, and nobody in this room should be reading it. Nine entities were masked by ai_mask before extraction ever ran, and the original moved to a path that only hr_admins can open. Unity Catalog enforces that grant. The app couldn't show you the original if I asked it to."

**If it breaks:** Do not zoom past the preview hunting for a perfect mask; certification verified masking on this corpus. If you spot a missed entity anyway, say the honest line, "and that miss is exactly what the review lane is for," and move. Never linger.

---

### Beat 6 · Brick creation in the product UI

12-minute version: use the pre-staged brick. Show the Agent Bricks screen with the already-built agent for 30 seconds, then trigger detection and go straight to beat 7. The lines below still work, compressed.

**You click:** The amber capability pill, which deep-links to the Agent Bricks Information Extraction UI in the second tab. In the product UI: name the agent, describe the task in plain English, attach the labeled examples, create. Then return to the app tab and let it poll. Total budget three and a half minutes, hard stop.

**On screen:** The real Databricks product surface, not the app. Back on the canvas, the pipeline keeps flowing with the engine labeled as the fallback, "ai_query structured output." When the endpoint appears, the label station flips to "Agent Bricks · Info Extraction" with a live dot and the endpoint name.

**You say:**
> "Everything so far ran on the fallback path, plain SQL functions, and it worked. Now I'll hire the specialist."
> "This is Agent Bricks, the actual product screen. I describe the task in English and hand it a few labeled examples. Databricks builds and tunes the agent behind a serving endpoint. No training job, no GPU conversation."
> "While it optimizes, look left. The pipeline is still flowing on the fallback. Production behaves the same way: the floor never stops because you're upgrading one station."

**If it breaks:** Optimization can exceed the window; this is a known risk, not a surprise. At the hard stop, say "the brick keeps optimizing after I stop watching it, so here's one I built before you walked in," and point the app at the pre-staged endpoint. Detection lights up either way. If this workspace has not enabled the preview, the capability panel walkthrough of the Previews page is itself a scripted moment; if you cannot flip it, stay on the fallback and say the honest line: "this workspace runs the GA path, which is exactly what the fallback is for." Never fake the flip.

---

### Beat 7 · Re-score delta

**You click:** Re-score on the label station.

**On screen:** Confidence bars flip. The delta line reads "re-scored 12 docs · confidence 0.71 → 0.94" in the reference run, and one document visibly changes lanes. Fallback and brick attributions are on screen at the same time.

**You say:**
> "The app just detected the new endpoint and re-scored the same documents. Confidence moved from 0.71 to 0.94, and one document changed lanes because the specialist read it correctly."
> "That is the Agent Bricks pitch in one screen. I described the task, and the platform built an agent that beats the baseline I wrote by hand. Swapping it in was a dropdown, not an integration project."

**If it breaks:** If the delta on this run is small, say the truth: the baseline was already strong on a small corpus, and the point is that the swap cost nothing. Quote the certified run's delta as "our rehearsal run moved 0.71 to 0.94" only if the board is showing its own numbers too. Never invent a delta.

---

### Beat 8 · Exec drop zone (25-minute version)

**You click:** Open the drop zone from the inbox station. Full-screen drop target.

**On screen:** Their PDF parses live with the same overlay, then gets labeled and routed wherever it honestly belongs.

**You say:**
> "Enough of my paperwork. Give me one of yours. Any PDF on your laptop. Boring is fine, scanned is even better. It lands in this workspace's volume and it never leaves."
> "I haven't seen this document and neither has the pipeline. It routes honestly. If it comes out labeled archive, that's the truthful answer, and you got to watch the system decline to be impressive."

**If it breaks:** No volunteer, no beat; skip without comment. Before parsing anything sensitive, say where it lands and let them decide. Files over 500 pages or 100MB hit the documented parse limits; ask for a smaller one and quote the limit as a fact, not an apology. Whatever they give you gets deleted in the post-show scrub, and you may say so out loud.

---

### Beat 9 · The prestige

**You click:** Back to the Ask page. Re-ask the finale question with the certified wording, character for character. Then click "Ask this in Genie's own UI" and run it once more on the product surface. In the 25-minute version, follow with the contract question: "What does the Miller Tooling contract say about late delivery penalties?"

**On screen:** Supervisor routes to GENIE. The answer: $41,720 of exposure across 19 claims, with 3 claims outside their window sitting in audit, $3,310, highlighted. The generated SQL is visible. Under it, the receipts line: asked cold at 9:41:03 and refused, first doc parsed 9:41:31, table live 9:44:12, answered 9:51:40. Then Genie's own UI, same tables, same answer. The contract question routes to Knowledge Assistant and returns with page-level citations to CT-1088.

**You say:**
> "Same question as minute one, word for word."
> "There it is. $41,720 of open exposure on Line 3 this quarter. And there's our buried story: three claims past their window, $3,310, sitting in the audit queue waiting for a person."
> "Look at the receipts. Asked at 9:41, and the system refused because nothing existed. Table live at 9:44. Answered at 9:51. Ten minutes from unanswerable to answered, wall clock, not video editing."
> "And don't take my app's word for it." Click. "This is Genie, Databricks' own UI, reading the same governed tables. Same question, same answer. My chrome is nowhere in sight."
> For the contract question: "This one can't come from a table, so the Supervisor hands it to Knowledge Assistant, and the answer comes back with citations to the page it read. Click one and the contract opens."

**If it breaks:** Genie certifies against exact wording; paraphrases are where NL2SQL wobbles, so use the script and let skeptics paraphrase afterward, framed as "let's see how it does off-script." If the Genie tab is slow, stay on the receipts, which are the actual proof, and open Genie while you talk. If app and Genie disagree, refresh Genie; both read the same table, and stale cache is the only honest explanation.

---

### Beat 10 · Money board close

**You click:** The payoff board, full screen.

**On screen:** CAUGHT vs COST. $3,310 caught in audit. $0.61 pipeline cost. The strip below: 47 docs processed, average seconds per doc, every hop recorded in run_metrics.

**You say:**
> "Two numbers to leave on. This run caught $3,310 in claims that should not be paid. It cost 61 cents to run, and every fraction of that is itemized in run_metrics, per document, per stage."
> "I'm not going to extrapolate your ROI on a slide. Your volume, your math."

Then stop talking. Leave the board up through Q&A.

**If it breaks:** Your run's numbers will differ from #38. Say the board's numbers. If someone calls the caught figure savings theater, agree with the premise and redirect: the corpus is synthetic, the catch is real logic, the cost is real metering, and the ratio is what scales. Hand them the per-page price and let them do their own multiplication.

---

## 3. Q&A ammo

Twelve questions executives actually ask. Two or three honest sentences each, grounded in the research brief. The load-bearing claim and its source are marked; do not improvise past them.

**1. "What does this cost at our volume?"**
Parsing is priced per page, roughly $0.70 to $1.05 per thousand pages at low complexity, and the extraction and judge calls are per-token on models you choose. The board's $0.61 is this run's metered total, itemized per document in run_metrics, so the unit economics are inspectable rather than estimated. One line item to know: Genie moves to pay-as-you-go on August 1 with 150 free DBUs a month.
Load-bearing: per-page parse pricing → AI Functions pricing page. Genie PAYG → July 2026 release notes (7/8, 7/15, 7/21).

**2. "How accurate is the extraction?"**
Every label carries a confidence score, and the pipeline's answer to imperfection is routing: low confidence goes to a human queue instead of straight through. The Agent Bricks brick exists to raise that ceiling; you hand it labeled examples in the UI and the platform optimizes the agent, which is the 0.71 to 0.94 move in the demo. The honest answer for your documents is to measure on your corpus before anything routes unattended, which is what the review lane is for.
Load-bearing: brick built and auto-optimized from declared task plus examples → Agent Bricks docs (docs.databricks.com generative-ai/agent-bricks).

**3. "How do you stop it from hallucinating answers?"**
The finale never asks a model to remember facts. Genie writes SQL you can read on screen and runs it against Delta tables, so the answer is a query result, and Knowledge Assistant returns citations to the pages it read. Where a model does reason, in the audit lane, its findings show their arithmetic and a person confirms before anything moves.
Load-bearing: Knowledge Assistant produces cited Q&A over documents → KA GA blog.

**4. "How is PII handled?"**
Documents labeled sensitive are masked with ai_mask before extraction, and originals move to a volume path readable only by the granted group, hr_admins in the demo, enforced by Unity Catalog. Access to the AI functions themselves can now be restricted with UC permissions, in Public Preview since July 8. And nothing you watched today contained real PII; the corpus is synthetic and watermarked.
Load-bearing: ai_mask entity obfuscation → AI Functions docs. UC restriction on AI Functions, Public Preview 7/8/2026 → July 2026 release notes.

**5. "Is this GA or a science project?"**
The pipeline you watched runs end to end on GA pieces: ai_parse_document, ai_classify, ai_extract, Knowledge Assistant, and the Supervisor Agent. Three pieces are earlier: the Information Extraction brick and the Supervisor API are Beta, and the point-and-click document UIs are Public Preview. The app marks each status on screen and falls back to the GA path wherever a preview is off, so nothing you saw depends on a preview to function.
Load-bearing: parse GA → ai_parse_document docs page and GCP release note 4/16/2026; brick Beta and KA/Supervisor GA → AWS Agent Bricks docs; doc UIs Public Preview → Azure release notes March 2026.

**6. "Does our data leave the platform?"**
Everything you watched lives in your workspace: the files in a Unity Catalog volume, the tables and decision records in your own catalog. Model calls go through Foundation Model endpoints on Databricks, governed by AI Gateway, not to an outside API you would contract separately. When your colleague dropped a PDF in, it went to a Unity Catalog volume in this workspace and nowhere else.
Load-bearing: app runs in-workspace against bound workspace resources (warehouse, volume, serving endpoints) → Databricks Apps resources docs.

**7. "Which model is this using, and who picked it?"**
Every model here is an endpoint chosen from a list the app reads live from the workspace, 49 of them in ours, Claude Opus 5 and GPT-5.6 among them. The judge ran on Claude Opus 5 because we picked it at setup, and swapping it is a dropdown. AI Gateway sits in front as the single governed door, so tracking and rate limits hold no matter which model is behind it.
Load-bearing: those models live on Foundation Model APIs as of July 2026 (Opus 5 GA 7/24, GPT-5.6 GA 7/9, Gemini 3.6 Flash 7/21) → July 2026 FM release notes.

**8. "What happens when the model you built on retires?"**
Retirements are real and scheduled: Gemini 3 Pro left on July 16, and Claude Sonnet 4 is slated for October 9. That is why nothing in this app hardcodes a model id; endpoints are listed dynamically and every model choice is a setting. When a retirement lands you select a successor and rerun, and no code changes.
Load-bearing: retirement dates → July 2026 FM API release notes.

**9. "Who maintains this after you leave?"**
The pipeline is SQL functions writing Delta tables, maintained like any other warehouse workload, with no notebooks or jobs to babysit. The brick is a managed serving endpoint; Databricks operates it, and your team owns the labeled examples that define it. The app itself ships as a bundle, so an update is one redeploy command.
Load-bearing: AI Functions run as managed SQL on serverless compute → AI Functions docs; apps are first-class bundle resources (CLI 0.273+) → Databricks bundles resources docs.

**10. "How long from this demo to production on our documents?"**
The plumbing is not the long pole; these are the same GA functions you would run in production, pointed at your volume instead of a synthetic one. The real work is decisions: your document types, your extraction fields, your routing rules, and who reviews what, which is exactly the shape of the profile editor you saw. One planning fact: bricks are created in the UI today, with no API or Terraform path, so treat brick creation as a per-workspace admin step.
Load-bearing: no programmatic brick creation; bricks consumed as standard serving endpoints → Agent Bricks docs.

**11. "Can it handle our scanned paper?"**
ai_parse_document takes PDFs, images, Word, and PowerPoint as binary and returns structured output: pages, elements, recovered tables, and markdown text. Current limits are 500 pages and 100MB per file, which covers nearly all business documents, and bigger files get split. The orange overlay you watched was that output drawn on screen, not an OCR slide.
Load-bearing: input formats, VARIANT output schema v2.0, 500-page and 100MB limits → ai_parse_document docs page.

**12. "Why this and not a point extraction vendor?"**
An extraction vendor hands you output that still needs a home and a governance story. Here the landing zone is the product: extracted fields arrive as Delta tables under the same Unity Catalog permissions and lineage as the rest of your data. That is the only reason the ten-minute question worked, because Genie could query tables that had existed for six minutes without any integration between the document system and the analytics estate.
Load-bearing: extraction lands as governed Delta tables queryable by Genie in the same platform → AI Functions docs and Databricks Apps resources docs (bound warehouse, tables, genie-space).

---

## 4. Reset checklist between shows

Do not reset the moment the room empties. The completed run in the tables is your backup data if the next show's pipeline dies. Scrub immediately, reset at T-10.

### Immediately after the room empties (2 minutes)

- [ ] Privacy scrub, non-negotiable: delete any exec drop-zone file from the volume (inbox and processed copies), then delete its rows from the documents and extract tables and from run_metrics. The next audience must never see the last audience's paper.
- [ ] Close any browser tab showing the previous customer's name or profile.
- [ ] Note anything that wobbled (slow beat, odd label, Genie phrasing) while it is fresh.

### T-10 before the next audience (5 minutes)

- [ ] Switch to this customer's profile. Confirm the certification badge is green. Uncertified means you present the generic certified profile instead, no exceptions.
- [ ] Decide the brick variant now. Live-creation show: remove the brick endpoint created last show so the name is free, and confirm the pre-staged fallback endpoint still exists as your escape hatch. Pre-staged show: confirm the app detects the endpoint (label station shows the live dot).
- [ ] One-key reset from the beat rail. This clears documents, extract tables, findings, decisions, and the money board, and returns the run counter.
- [ ] Verify the cold open: inbox reads zero, and the Ask page returns the no-tables-exist answer to the finale question. This is the wager; if it is not empty, the show has no act one.
- [ ] Warm the warehouse: run the capability probe (the one-row ai_classify) so beat 3 does not eat a cold start.
- [ ] Check capability pills: green for what is live, amber only where you intend the Previews-page walkthrough. No grey pill in the script path.
- [ ] Confirm the Genie space opens in its own tab and points at the demo schema.

### Stage the room (2 minutes)

- [ ] Tabs in order: canvas, Agent Bricks UI, Genie, Ask page. Nothing else open.
- [ ] Put the app in demo mode: full screen, dark theme for the projector. macOS notifications off. iMessage and Slack closed, not just muted.
- [ ] Beat rail at beat 1. Clicker or hotkeys tested from where you will stand.
- [ ] Say the finale question out loud once, exact wording. It is the first and last thing the room hears, and it has to be identical both times.

---

*Companion documents: README (install, the two-number promise), PLAN.md (architecture and phasing), platform_facts.json (statuses and deep links; if this runbook and that file disagree, the file wins because it is maintained).*
