"""
Core break-detection and risk-scoring logic.

Matches trade_capture (our booking) against counterparty_confirm (their ack) by trade_id,
classifies any disagreement into a break type, and assigns a severity tier based on
$ notional exposure at risk plus break type — mirroring how a real Ops desk prioritizes
its queue: a $50 quantity break on 100 shares of AAPL is not the same risk as a $2M
notional mismatch on a CDS.
"""
import csv
from datetime import date

# Severity thresholds, tuned to notional $ at risk. Anything under LOW_TOLERANCE is
# auto-resolved (same logic OptiSolve used for its auto-resolve confidence tier) —
# not every break needs a human; only the ones that matter.
LOW_TOLERANCE = 500        # below this, auto-resolve (rounding/FX-noise level)
MEDIUM_THRESHOLD = 25_000
HIGH_THRESHOLD = 250_000
# above HIGH_THRESHOLD -> CRITICAL, which is also the escalation floor (see below)

# Some break types carry risk beyond pure $ notional (a missing confirm means we don't
# even know if the trade will settle) so they get a severity floor regardless of size.
SEVERITY_FLOOR = {
    "MISSING_CONFIRM": "HIGH",
    "COUNTERPARTY_MISMATCH": "HIGH",
}

# Break types that always go to the Ops escalation queue regardless of $ size, because
# the risk isn't really about notional — it's that settlement itself is uncertain.
ALWAYS_ESCALATE_TYPES = {"MISSING_CONFIRM", "COUNTERPARTY_MISMATCH"}

SEVERITY_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

# Directional acknowledgment that break tolerance isn't really uniform across products —
# FX settles fast (T+1/T+2, thin margin for error) so breaks there are tightened; bonds
# carry natural day-count/accrued-interest noise so they're loosened. This is not a full
# per-asset-class model (see README "What's synthetic vs. real").
ASSET_CLASS_TOLERANCE_MULTIPLIER = {
    "FX": 0.5,
    "Equity": 1.0,
    "Derivative": 1.0,
    "Commodity": 1.0,
    "Bond": 1.5,
}


def load_csv(path):
    with open(path) as f:
        return {row["trade_id"]: row for row in csv.DictReader(f)}


def notional_at_risk(captured, confirmed, break_type):
    if break_type == "MISSING_CONFIRM":
        return float(captured["notional"])
    if confirmed is None:
        return float(captured["notional"])
    return abs(float(captured["notional"]) - float(confirmed["notional"]))


def severity_for(exposure, break_type, asset_class):
    multiplier = ASSET_CLASS_TOLERANCE_MULTIPLIER.get(asset_class, 1.0)
    low = LOW_TOLERANCE * multiplier
    medium = MEDIUM_THRESHOLD * multiplier
    high = HIGH_THRESHOLD * multiplier

    if exposure < low and break_type not in SEVERITY_FLOOR:
        tier = "LOW"
    elif exposure >= high:
        tier = "CRITICAL"
    elif exposure >= medium:
        tier = "HIGH"
    else:
        tier = "MEDIUM"

    floor = SEVERITY_FLOOR.get(break_type)
    if floor and SEVERITY_ORDER.index(floor) > SEVERITY_ORDER.index(tier):
        tier = floor
    return tier


def escalation_reason(break_type, severity, exposure, asset_class):
    """Returns a reason string if this break should go to the Ops escalation queue,
    else None. This is the same deterministic logic that produced the severity —
    just surfaced as an explicit workflow tag with a human-readable justification,
    instead of leaving 'escalate' implicit in a severity label."""
    if break_type in ALWAYS_ESCALATE_TYPES:
        return (f"{break_type.replace('_', ' ').title()} on a ${exposure:,.0f} "
                f"{asset_class} trade — settlement itself is uncertain, "
                f"escalating regardless of size.")
    if severity == "CRITICAL":
        return (f"${exposure:,.0f} notional at risk from a {break_type.replace('_', ' ').lower()} "
                f"exceeds the ${HIGH_THRESHOLD:,.0f} escalation floor for {asset_class} trades.")
    return None


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


def aging_days(trade_date_str, as_of=None):
    as_of = as_of or date.today()
    trade_dt = date.fromisoformat(trade_date_str)
    return max(0, (as_of - trade_dt).days)


def reconcile(capture_path, confirm_path, as_of=None):
    captures = load_csv(capture_path)
    confirms = load_csv(confirm_path)

    breaks = []
    for trade_id, captured in captures.items():
        confirmed = confirms.get(trade_id)
        result = classify_break(captured, confirmed)
        if result is None:
            continue

        break_type, exposure = result
        asset_class = captured["asset_class"]
        severity = severity_for(exposure, break_type, asset_class)
        auto_resolved = severity == "LOW"
        reason = None if auto_resolved else escalation_reason(break_type, severity, exposure, asset_class)

        multiplier = ASSET_CLASS_TOLERANCE_MULTIPLIER.get(asset_class, 1.0)
        rule_fired = (f"exposure ${exposure:,.2f} < LOW_TOLERANCE "
                      f"${LOW_TOLERANCE * multiplier:,.2f} ({asset_class} x{multiplier})")

        breaks.append({
            "trade_id": trade_id,
            "symbol": captured["symbol"],
            "asset_class": asset_class,
            "counterparty": captured["counterparty"],
            "break_type": break_type,
            "severity": severity,
            "exposure_usd": round(exposure, 2),
            "status": "AUTO_RESOLVED" if auto_resolved else "OPEN",
            "escalated": reason is not None,
            "escalation_reason": reason,
            "auto_resolve_rule": rule_fired if auto_resolved else None,
            "trade_date": captured["trade_date"],
            "settlement_date": captured["settlement_date"],
            "aging_days": aging_days(captured["trade_date"], as_of),
            "captured": captured,
            "confirmed": confirmed,
        })

    return breaks


def summarize(breaks):
    open_breaks = [b for b in breaks if b["status"] == "OPEN"]
    by_severity = {s: 0 for s in SEVERITY_ORDER}
    exposure_by_severity = {s: 0.0 for s in SEVERITY_ORDER}
    by_type = {}
    for b in open_breaks:
        by_severity[b["severity"]] += 1
        exposure_by_severity[b["severity"]] += b["exposure_usd"]
        by_type[b["break_type"]] = by_type.get(b["break_type"], 0) + 1

    aging_values = [b["aging_days"] for b in open_breaks]
    escalated = [b for b in open_breaks if b["escalated"]]

    return {
        "total_breaks": len(breaks),
        "open_breaks": len(open_breaks),
        "auto_resolved": len(breaks) - len(open_breaks),
        "escalated_count": len(escalated),
        "total_exposure_usd": round(sum(b["exposure_usd"] for b in open_breaks), 2),
        "by_severity": by_severity,
        "exposure_by_severity": {k: round(v, 2) for k, v in exposure_by_severity.items()},
        "by_type": by_type,
        "oldest_open_days": max(aging_values) if aging_values else 0,
        "avg_open_days": round(sum(aging_values) / len(aging_values), 1) if aging_values else 0,
    }


if __name__ == "__main__":
    breaks = reconcile("../data/trade_capture.csv", "../data/counterparty_confirm.csv")
    summary = summarize(breaks)
    print(summary)
