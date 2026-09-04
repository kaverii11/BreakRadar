# BreakRadar

A daily trade-break reconciliation engine: matches a firm's own trade-capture blotter
against the counterparty's confirmation feed, classifies every disagreement into a break
type, scores it by $ notional exposure at risk, auto-resolves what's within tolerance,
and escalates the rest to a dashboard ranked by severity.

This is the reconciliation/exception-management workflow that sits at the center of a
trading-firm Operations desk: every trade needs its two independent records to agree
before it can settle safely, and someone (or something) has to catch it when they don't.

## Why this shape

- **Break classification** (`backend/reconciler.py`): five break types — price break,
  quantity break, missing confirm, counterparty mismatch, late settlement — checked in a
  fixed priority order so a trade only gets one root-cause label, not several overlapping
  ones.
- **Severity scoring**: tiered by $ exposure (`LOW < $500 < MEDIUM < $25K < HIGH < $250K <
  CRITICAL`), with a severity floor for break types that carry risk beyond their dollar
  size — a missing confirm or wrong counterparty is escalated regardless of notional,
  because it means settlement itself is in doubt, not just the price. Tolerance is also
  scaled per asset class (FX tightened, bonds loosened) — see the asset-class note below.
- **Auto-resolve tier**: breaks under the LOW threshold clear automatically instead of
  queuing a human — the same confidence-threshold pattern used in
  [OptiSolve](https://github.com/kaverii11/Optisolve)'s ticket auto-resolve tier, applied
  here to trade breaks instead of support tickets.
- **Escalation queue, as an explicit workflow, not just a severity label**: any break
  that's CRITICAL, or that's a missing-confirm / counterparty-mismatch regardless of
  size, is tagged `escalated: true` with a generated `escalation_reason` string — a
  one-to-one match for "escalating outstanding exceptions/issues to relevant
  stakeholders." Surfaced as its own tab in the dashboard, not buried in the main table.
- **Audit trail for every auto-resolution** (`backend/audit.py`, `data/audit_log.jsonl`):
  timestamp, the exact rule that fired, and the $ exposure it cleared at. Nothing gets
  auto-closed without a traceable, reconstructable reason — the actual substance behind
  "controls and procedures" / "compliance and adherence with existing regulations" in an
  Ops context, not just a policy statement.
- **Key risk indicators, not just a table**: total open exposure, escalated count, breaks
  by type, and aging (oldest open break, average age) are computed in `summarize()` and
  shown as their own KRI panels — a $200 break open 3 days is a worse signal than a $200
  break open 3 hours, which a flat table can't show.
- **AI-generated explanations** (`backend/explain.py`): for each break, an LLM (Groq,
  same provider as OptiSolve) turns the already-computed deterministic verdict into a
  one-line analyst-readable sentence. The model never decides severity or escalation —
  it only explains a decision the rule engine already made, so a bad LLM response can
  make a row harder to read but can't silently change what gets escalated or resolved.
  Falls back to a template built from the same fields if `GROQ_API_KEY` isn't set, so the
  project still runs and demos correctly without a key.
- **Dashboard** (`frontend/index.html`): three tabs — the full break queue, a dedicated
  escalation queue, and the auto-resolve audit log — ranked by severity then exposure,
  filterable, with per-break resolve and live explanations.

### Asset-class handling

Trades are tagged with an asset class (Equity, FX, Bond, Derivative, Commodity), and
break tolerance is scaled per class — tightened 2x for FX (fast settlement, thin margin
for error) and loosened 1.5x for bonds (day-count/accrued-interest noise is normal). This
is a directional acknowledgment that break tolerance isn't uniform across products, not a
full asset-class model — a real desk would tune this per product and per counterparty
relationship far more precisely than a single multiplier.

## Run it

```bash
cd backend
pip install -r requirements.txt
python generate_data.py      # writes data/trade_capture.csv + data/counterparty_confirm.csv
export GROQ_API_KEY=...      # optional — enables real LLM explanations, else template fallback
uvicorn server:app --port 8420
```

Then open `frontend/index.html` in a browser.

## What's synthetic vs. real

The trade/confirm data is generated (`generate_data.py`), not live market data — there's
no exchange or custodian feed a student project can legitimately plug into. The break
types, severity logic, and reconciliation matching are real engineering, built to mirror
how an Ops desk actually prioritizes its break queue.
