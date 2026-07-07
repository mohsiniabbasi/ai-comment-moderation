"""AI Comment Moderation Console — FastAPI backend.

Endpoints:
  GET  /                       -> the console UI
  GET  /api/state              -> everything the UI needs (comments + analysis +
                                  disposition, queue, SOP, audit, KPIs, engine)
  POST /api/process            -> apply threshold / SOP edits, (re)classify and
                                  route every comment, run auto-actions
  POST /api/queue/{id}/resolve -> a human resolves a queued comment
  POST /api/reset              -> reset demo state

Classification is a live LLM call when a key is set (Gemini / Claude), else a
rule-based fallback. The Meta actions run through a Graph-API-shaped adapter
(simulated). The agent never acts on its own below the threshold — those go to
a human. See moderation.py.
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import agent, data, moderation

app = FastAPI(title="AI Comment Moderation Console", version="1.0")

_STATIC = os.path.join(os.path.dirname(__file__), "static")

_STATUS_LABEL = {
    "auto_hidden": "Auto-hidden",
    "auto_replied": "Auto-replied",
    "auto_liked": "Auto-liked",
    "queued": "Human review",
    "resolved_hidden": "Resolved · hidden",
    "resolved_deleted": "Resolved · deleted",
    "resolved_replied": "Resolved · replied",
    "resolved_dismissed": "Resolved · left up",
}


def _analysis_for(comment: dict) -> dict:
    cached = data.get_analysis(comment["id"])
    if cached is None:
        cached = agent.classify(comment)
        data.set_analysis(comment["id"], cached)
    return cached


# ── core: (re)classify + route + run auto-actions ───────────────────────────
def _process() -> None:
    sop = data.sop()
    threshold = sop["threshold"]
    for c in data.list_comments():
        cid = c["id"]
        if data.get_disp(cid).get("status", "").startswith("resolved"):
            continue  # human decisions are terminal
        analysis = _analysis_for(c)
        decision = moderation.route(c, analysis, threshold, sop)
        prev = data.get_executed(cid)

        if decision["route"] == "auto":
            action = decision["action"]
            if prev != action:  # only fire the Graph call on a change
                gcall = moderation.execute(action, cid, decision.get("payload"))
                data.add_audit(cid, "ai", f"auto_{action}", decision["reason"], graph=gcall)
                data.set_executed(cid, action)
            status = {"hide": "auto_hidden", "reply": "auto_replied",
                      "like": "auto_liked"}[action]
        else:
            if prev and prev != "queued":
                data.add_audit(cid, "ai", "escalated",
                               "Re-evaluated: escalated to the Human Review Queue "
                               "after a policy / threshold change.")
            data.set_executed(cid, "queued")
            status = "queued"

        data.set_disp(cid, {"status": status, **decision})


def _snapshot() -> dict:
    comments = []
    for c in data.list_comments():
        disp = data.get_disp(c["id"])
        comments.append({
            **c,
            "analysis": _analysis_for(c),
            "disposition": disp,
            "status_label": _STATUS_LABEL.get(disp.get("status", ""), "Pending"),
        })
    queue = [c for c in comments if c["disposition"].get("status") == "queued"]
    processed = any(c["disposition"] for c in comments)
    kpi = {
        "total": len(comments),
        "auto": sum(1 for c in comments
                    if str(c["disposition"].get("status", "")).startswith("auto_")),
        "queue": len(queue),
        "resolved": sum(1 for c in comments
                        if str(c["disposition"].get("status", "")).startswith("resolved")),
        "actions": len(data.audit_log()),
    }
    return {
        "brand": data.BRAND,
        "comments": comments,
        "queue": queue,
        "sop": data.sop(),
        "faq": moderation.FAQ,
        "audit": data.audit_log(),
        "kpi": kpi,
        "engine": agent.engine_name(),
        "processed": processed,
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(_STATIC, "index.html"))


@app.get("/api/state")
def state() -> dict:
    return _snapshot()


class ProcessBody(BaseModel):
    threshold: float | None = None
    rules: dict | None = None   # {category: {"auto": bool}} toggles


@app.post("/api/process")
def process(body: ProcessBody | None = None) -> dict:
    sop = data.sop()
    if body:
        if body.threshold is not None:
            sop["threshold"] = round(max(0.0, min(body.threshold, 1.0)), 2)
        if body.rules:
            for cat, patch in body.rules.items():
                if cat in sop["rules"] and "auto" in patch:
                    sop["rules"][cat]["auto"] = bool(patch["auto"])
    _process()
    return _snapshot()


class ResolveBody(BaseModel):
    action: str                 # "hide" | "delete" | "reply" | "dismiss"
    message: str | None = None


@app.post("/api/queue/{comment_id}/resolve")
def resolve(comment_id: str, body: ResolveBody) -> dict:
    comment = data.get_comment(comment_id)
    if not comment:
        raise HTTPException(404, "comment not found")
    if body.action not in ("hide", "delete", "reply", "dismiss"):
        raise HTTPException(400, "action must be hide, delete, reply or dismiss")

    who = comment["author"]
    if body.action == "hide":
        g = moderation.graph_hide(comment_id)
        data.add_audit(comment_id, "operator", "hide", f"Human hid the comment from {who}.", graph=g)
        status = "resolved_hidden"
    elif body.action == "delete":
        g = moderation.graph_delete(comment_id)
        data.add_audit(comment_id, "operator", "delete", f"Human deleted the comment from {who}.", graph=g)
        status = "resolved_deleted"
    elif body.action == "reply":
        msg = (body.message or "").strip()
        if not msg:
            raise HTTPException(400, "reply needs a message")
        g = moderation.graph_reply(comment_id, msg)
        data.add_audit(comment_id, "operator", "reply",
                       f"Human replied to {who}: “{msg[:70]}{'…' if len(msg) > 70 else ''}”", graph=g)
        status = "resolved_replied"
    else:  # dismiss
        data.add_audit(comment_id, "operator", "dismiss",
                       f"Human reviewed {who}'s comment and left it up (no action).")
        status = "resolved_dismissed"

    data.set_executed(comment_id, "resolved")
    disp = data.get_disp(comment_id)
    data.set_disp(comment_id, {**disp, "status": status, "resolution": body.action})
    return _snapshot()


@app.post("/api/reset")
def reset() -> dict:
    data.reset_state()
    return _snapshot()


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
