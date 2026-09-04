"""
Core break-detection and risk-scoring logic.

Matches trade_capture (our booking) against counterparty_confirm (their ack) by trade_id,
classifies any disagreement into a break type, and assigns a severity tier based on
$ notional exposure at risk plus break type — mirroring how a real Ops desk prioritizes
its queue: a $50 quantity break on 100 shares of AAPL is not the same risk as a $2M
notional mismatch on a CDS.
"""
import csv
from datetime import date, datetime

# Severity thresholds, tuned to notional $ at risk. Anything under LOW_TOLERANCE is
# auto-resolved (same logic OptiSolve used for its auto-resolve confidence tier) —
# not every break needs a human; only the ones that matter.
LOW_TOLERANCE = 500        # below this, auto-resolve (rounding/FX-noise level)
MEDIUM_THRESHOLD = 25_000
HIGH_THRESHOLD = 250_000
# above HIGH_THRESHOLD -> CRITICAL

# Some break types carry risk beyond pure $ notional (a missing confirm means we don't
# even know if the trade will settle) so they get a severity floor regardless of size.
SEVERITY_FLOOR = {
    "MISSING_CONFIRM": "HIGH",
    "COUNTERPARTY_MISMATCH": "HIGH",
}

SEVERITY_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def load_csv(path):
    with open(path) as f:
        return {row["trade_id"]: row for row in csv.DictReader(f)}


def notional_at_risk(captured, confirmed, break_type):
    if break_type == "MISSING_CONFIRM":
        return float(captured["notional"])
    if confirmed is None:
        return float(captured["notional"])
    return abs(float(captured["notional"]) - float(confirmed["notional"]))


def severity_for(exposure, break_type):
    if exposure < LOW_TOLERANCE and break_type not in SEVERITY_FLOOR:
        return "LOW"
    tier = "LOW"
    if exposure >= HIGH_THRESHOLD:
        tier = "CRITICAL"
    elif exposure >= MEDIUM_THRESHOLD:
        tier = "HIGH"
    elif exposure >= LOW_TOLERANCE:
        tier = "MEDIUM"

    floor = SEVERITY_FLOOR.get(break_type)
    if floor and SEVERITY_ORDER.index(floor) > SEVERITY_ORDER.index(tier):
        return floor
    return tier


def classify_break(captured, confirmed):
    """Returns (break_type, exposure) or None if the trade matches cleanly."""
    if confirmed is None:
        exposure = notional_at_risk(captured, None, "MISSING_CONFIRM")
        return "MISSING_CONFIRM", exposure

    if captured["counterparty"] != confirmed["counterparty"]:
        exposure = notional_at_risk(captured, confirmed, "COUNTERPARTY_MISMATCH")
        return "COUNTERPARTY_MISMATCH", exposure

    if captured["settlement_date"] != confirmed["settlement_date"]:
        exposure = notional_at_risk(captured, confirmed, "LATE_SETTLEMENT")
        return "LATE_SETTLEMENT", exposure

    if abs(float(captured["price"]) - float(confirmed["price"])) > 1e-6:
        exposure = notional_at_risk(captured, confirmed, "PRICE_BREAK")
        return "PRICE_BREAK", exposure

    if int(captured["quantity"]) != int(confirmed["quantity"]):
        exposure = notional_at_risk(captured, confirmed, "QUANTITY_BREAK")
        return "QUANTITY_BREAK", exposure

    return None


def reconcile(capture_path, confirm_path):
    captures = load_csv(capture_path)
    confirms = load_csv(confirm_path)

    breaks = []
    for trade_id, captured in captures.items():
        confirmed = confirms.get(trade_id)
        result = classify_break(captured, confirmed)
        if result is None:
            continue

        break_type, exposure = result
        severity = severity_for(exposure, break_type)
        auto_resolved = severity == "LOW"

        breaks.append({
            "trade_id": trade_id,
            "symbol": captured["symbol"],
            "counterparty": captured["counterparty"],
            "break_type": break_type,
            "severity": severity,
            "exposure_usd": round(exposure, 2),
            "status": "AUTO_RESOLVED" if auto_resolved else "OPEN",
            "trade_date": captured["trade_date"],
            "settlement_date": captured["settlement_date"],
            "captured": captured,
            "confirmed": confirmed,
        })

    return breaks


def summarize(breaks):
    open_breaks = [b for b in breaks if b["status"] == "OPEN"]
    by_severity = {s: 0 for s in SEVERITY_ORDER}
    exposure_by_severity = {s: 0.0 for s in SEVERITY_ORDER}
    for b in open_breaks:
        by_severity[b["severity"]] += 1
        exposure_by_severity[b["severity"]] += b["exposure_usd"]

    return {
        "total_breaks": len(breaks),
        "open_breaks": len(open_breaks),
        "auto_resolved": len(breaks) - len(open_breaks),
        "total_exposure_usd": round(sum(b["exposure_usd"] for b in open_breaks), 2),
        "by_severity": by_severity,
        "exposure_by_severity": {k: round(v, 2) for k, v in exposure_by_severity.items()},
    }


if __name__ == "__main__":
    breaks = reconcile("../data/trade_capture.csv", "../data/counterparty_confirm.csv")
    summary = summarize(breaks)
    print(summary)
