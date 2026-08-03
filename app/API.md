# DocFlow frontend ↔ backend contract (deployed app)

Frontend files live in `static/` (index.html = flow canvas, chat.html = ask page, alt.html = runner-up design). Same-origin fetch, no auth headers needed (app handles identity server-side).

## Endpoints
- `POST /api/bootstrap` → `{statements, errors[]}` (idempotent DDL)
- `GET /api/capabilities` → `{ai_functions: bool, warehouse, endpoints:{foundation:int, custom:[names]}, brick_detected: bool, volume}`
- `POST /api/seed` body `{company, seed}` → `{uploaded, types:{...}, watermark}` (generates synthetic corpus → volume inbox; ~20-40s)
- `POST /api/run` → `{started:true}` | 409 if active. Kicks the real pipeline (parse→label→route→extract→audit→secure) in background; total 1-4 min.
- `GET /api/state` → poll every 1.5-2s:
```json
{"run_id":1, "phase":"parse|label|route|extract|audit|secure|done|error|idle|ingest",
 "docs": {"WC-2214": {"doc_id","filename","stage","doc_type","confidence","route":["extract","audit"],"detail"}},
 "log": [{"t":12.3,"doc":"WC-2214","stage":"labeled","detail":"type: warranty_claim (ai_classify)"}],
 "money": {"caught_usd":3310.0, "cost_usd":0.61}, "elapsed_s": 84.2, "error":""}
```
- `GET /api/tables/extract_warranty_claims|extract_supplier_invoices|audit_findings` → `{table, rows:[[...]]}`
- `POST /api/ask` body `{question}` → `{sql, rows:[[...]], engine}` or `{error}`

## Frontend obligations
- Stage/lane visuals must render from `/api/state` (docs' stage + route + log) — the canvas replays recorded truth, never simulates.
- Money board binds to `state.money` (caught_usd / cost_usd), formatted $.
- Buttons: Generate docs → POST /api/seed; Run pipeline → POST /api/run; chat input → POST /api/ask (render sql + rows table).
- Capability pills bind to /api/capabilities (brick_detected=false → show fallback engine label "ai_query structured"; amber pill "Agent Bricks IE: enable preview").
- Empty states matter: phase=idle & no docs → cold-open state ("no tables exist yet" in chat; inbox 0 with Generate CTA).
- Keep all live-verified product names/badges exactly as the design artboards had them.
