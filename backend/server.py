from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from reconciler import reconcile, summarize

app = FastAPI(title="BreakRadar")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BREAKS = reconcile("../data/trade_capture.csv", "../data/counterparty_confirm.csv")
BREAKS_BY_ID = {b["trade_id"]: b for b in BREAKS}


@app.get("/api/summary")
def get_summary():
    return summarize(BREAKS)


@app.get("/api/breaks")
def list_breaks(severity: str | None = None, status: str | None = None):
    results = BREAKS
    if severity:
        results = [b for b in results if b["severity"] == severity.upper()]
    if status:
        results = [b for b in results if b["status"] == status.upper()]

    severity_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    results = sorted(results, key=lambda b: (severity_rank[b["severity"]], -b["exposure_usd"]))
    return results


@app.get("/api/breaks/{trade_id}")
def get_break(trade_id: str):
    b = BREAKS_BY_ID.get(trade_id)
    if not b:
        raise HTTPException(status_code=404, detail="Trade not found")
    return b


@app.post("/api/breaks/{trade_id}/resolve")
def resolve_break(trade_id: str):
    b = BREAKS_BY_ID.get(trade_id)
    if not b:
        raise HTTPException(status_code=404, detail="Trade not found")
    b["status"] = "RESOLVED"
    return b
