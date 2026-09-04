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
  because it means settlement itself is in doubt, not just the price.
- **Auto-resolve tier**: breaks under the LOW threshold clear automatically instead of
  queuing a human — the same confidence-threshold pattern used in
  [OptiSolve](https://github.com/kaverii11/Optisolve)'s ticket auto-resolve tier, applied
  here to trade breaks instead of support tickets.
- **Dashboard** (`frontend/index.html`): open breaks ranked by severity then exposure,
  filterable, with per-break resolve — the "transparency into key risk indicators" a real
  Ops desk needs at a glance.

## Run it

```bash
cd backend
pip install -r requirements.txt
python generate_data.py      # writes data/trade_capture.csv + data/counterparty_confirm.csv
uvicorn server:app --port 8420
```

Then open `frontend/index.html` in a browser.

## What's synthetic vs. real

The trade/confirm data is generated (`generate_data.py`), not live market data — there's
no exchange or custodian feed a student project can legitimately plug into. The break
types, severity logic, and reconciliation matching are real engineering, built to mirror
how an Ops desk actually prioritizes its break queue.
