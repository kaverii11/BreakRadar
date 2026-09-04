"""
Plain-English explanation for each flagged break, for an analyst scanning the queue.

The severity engine already computed the reasoning (break type, exposure, why it's
escalated or not) — the LLM's only job is translating that already-deterministic
verdict into a readable sentence. It is never asked to decide severity or exposure
itself, so a bad LLM response can make the queue harder to read but can't silently
change what actually gets escalated or auto-resolved.

Set GROQ_API_KEY to call the real model (same provider used in OptiSolve). Without a
key, falls back to a template built from the same fields — the project still runs and
demos correctly, it just loses the natural-language phrasing.
"""
import os
import requests

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"

_cache = {}


def _template_explanation(b):
    if b["escalated"]:
        return f"Escalated: {b['escalation_reason']}"
    if b["status"] == "AUTO_RESOLVED":
        return f"Auto-resolved: {b['auto_resolve_rule']}."
    return (f"{b['break_type'].replace('_', ' ').title()} on {b['symbol']} "
            f"({b['counterparty']}) — ${b['exposure_usd']:,.0f} at risk, "
            f"{b['severity']} severity.")


def explain_break(b):
    if b["trade_id"] in _cache:
        return _cache[b["trade_id"]]

    if not GROQ_API_KEY:
        result = _template_explanation(b)
        _cache[b["trade_id"]] = result
        return result

    prompt = (
        "You are annotating a trade-break reconciliation queue for an Operations analyst. "
        "Given this already-computed break verdict, write ONE short plain-English sentence "
        "(max 25 words) explaining it. Do not change or second-guess the severity or "
        "escalation decision, just explain it clearly.\n\n"
        f"trade_id: {b['trade_id']}\n"
        f"break_type: {b['break_type']}\n"
        f"asset_class: {b['asset_class']}\n"
        f"exposure_usd: {b['exposure_usd']}\n"
        f"severity: {b['severity']}\n"
        f"escalated: {b['escalated']}\n"
        f"escalation_reason: {b['escalation_reason']}\n"
        f"status: {b['status']}\n"
        f"auto_resolve_rule: {b['auto_resolve_rule']}\n"
    )

    try:
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 60,
            },
            timeout=10,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        result = text if text else _template_explanation(b)
    except Exception:
        result = _template_explanation(b)

    _cache[b["trade_id"]] = result
    return result
