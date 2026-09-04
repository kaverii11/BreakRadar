"""
Generates two independent trade feeds that should agree but don't:
  - trade_capture.csv   : the firm's own booking system (source of truth for intent)
  - counterparty_confirm.csv : what the counterparty/custodian actually confirms back

Real settlement operations reconcile exactly these two feeds every day. Breaks between
them are where operational risk (and $ exposure) lives.
"""
import csv
import random
from datetime import date, timedelta

random.seed(42)

INSTRUMENTS = [
    ("AAPL", "Equity", 189.50),
    ("MSFT", "Equity", 421.30),
    ("US10Y", "Bond", 98.75),
    ("EURUSD", "FX", 1.0850),
    ("GS-CDS-5Y", "Derivative", 102.10),
    ("TSLA", "Equity", 248.90),
    ("XAUUSD", "Commodity", 2380.00),
]

COUNTERPARTIES = ["JPMORGAN", "MORGAN STANLEY", "CITI", "BARCLAYS", "DEUTSCHE BANK", "UBS"]

N_TRADES = 300
BREAK_RATE = 0.18  # ~18% of trades will have some kind of break, realistic for a busy desk

BREAK_TYPES = [
    "PRICE_BREAK",
    "QUANTITY_BREAK",
    "MISSING_CONFIRM",
    "COUNTERPARTY_MISMATCH",
    "LATE_SETTLEMENT",
]


def random_trade_date():
    start = date(2026, 8, 1)
    offset = random.randint(0, 30)
    return start + timedelta(days=offset)


def gen_trade(trade_id):
    symbol, asset_class, base_price = random.choice(INSTRUMENTS)
    price = round(base_price * random.uniform(0.98, 1.02), 4)
    quantity = random.choice([100, 250, 500, 1000, 2500, 5000])
    counterparty = random.choice(COUNTERPARTIES)
    trade_date = random_trade_date()
    settlement_date = trade_date + timedelta(days=2)  # standard T+2
    notional = round(price * quantity, 2)

    return {
        "trade_id": f"TRD-{trade_id:05d}",
        "symbol": symbol,
        "asset_class": asset_class,
        "counterparty": counterparty,
        "quantity": quantity,
        "price": price,
        "notional": notional,
        "trade_date": trade_date.isoformat(),
        "settlement_date": settlement_date.isoformat(),
    }


def apply_break(confirm_row, break_type):
    if break_type == "PRICE_BREAK":
        # a bad tick or fat-finger on the confirm side, 0.5-3% off
        drift = random.uniform(0.005, 0.03) * random.choice([-1, 1])
        confirm_row["price"] = round(confirm_row["price"] * (1 + drift), 4)
        confirm_row["notional"] = round(confirm_row["price"] * confirm_row["quantity"], 2)
    elif break_type == "QUANTITY_BREAK":
        delta = random.choice([-50, -25, -10, 10, 25, 50, 100])
        confirm_row["quantity"] = max(1, confirm_row["quantity"] + delta)
        confirm_row["notional"] = round(confirm_row["price"] * confirm_row["quantity"], 2)
    elif break_type == "COUNTERPARTY_MISMATCH":
        others = [c for c in COUNTERPARTIES if c != confirm_row["counterparty"]]
        confirm_row["counterparty"] = random.choice(others)
    elif break_type == "LATE_SETTLEMENT":
        d = date.fromisoformat(confirm_row["settlement_date"])
        confirm_row["settlement_date"] = (d + timedelta(days=random.randint(1, 5))).isoformat()
    # MISSING_CONFIRM is handled by dropping the row entirely, not editing it
    return confirm_row


def main():
    trades = [gen_trade(i) for i in range(1, N_TRADES + 1)]

    confirms = []
    for t in trades:
        confirm_row = dict(t)
        if random.random() < BREAK_RATE:
            break_type = random.choice(BREAK_TYPES)
            if break_type == "MISSING_CONFIRM":
                continue  # counterparty never sent a confirm for this trade
            confirm_row = apply_break(confirm_row, break_type)
        confirms.append(confirm_row)

    fields = ["trade_id", "symbol", "asset_class", "counterparty", "quantity",
              "price", "notional", "trade_date", "settlement_date"]

    with open("../data/trade_capture.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(trades)

    with open("../data/counterparty_confirm.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(confirms)

    print(f"Generated {len(trades)} trades, {len(confirms)} confirms "
          f"({len(trades) - len(confirms)} missing confirms).")


if __name__ == "__main__":
    main()
