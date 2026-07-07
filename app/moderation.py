"""SOP engine + Graph-API-shaped Meta adapter.

Two honest halves, stated plainly in the case study:

  1. ROUTING — a pure function of (classification, confidence, threshold, SOP).
     High-confidence spam/abuse are auto-hidden; FAQ-answerable questions get an
     auto-reply; positives get a like; complaints ALWAYS go to a human; and
     anything below the confidence threshold escalates to the Human Review
     Queue. Raising the threshold pushes more borderline items to humans — that
     is the safety dial.

  2. ACTIONS — every hide / delete / reply / like is expressed as a
     Graph-API-shaped call (correct method, endpoint and params for the real
     Meta Graph API). In the demo they are SIMULATED (no Page token, no app
     review needed to run it). Drop in a Page access token and point the
     adapter at graph.facebook.com and the exact same calls go live.
"""
from __future__ import annotations

GRAPH_VERSION = "v19.0"

# ── FAQ playbook — the only thing that lets a question be auto-answered ──────
# Each entry: trigger keywords -> the approved public reply. A question with no
# match is escalated to a human even at high confidence (we won't guess).
FAQ: list[dict] = [
    {"keys": ["ship", "shipping", "deliver", "delivery", "ireland", "post", "arrive"],
     "answer": "Hi! We ship across the UK & Ireland in 2–3 working days (free over £30). "
               "You'll get a tracking link by email as soon as it's dispatched. 💛"},
    {"keys": ["return", "refund", "money back", "policy", "send it back"],
     "answer": "Happy to help! We offer a 30-day money-back guarantee — if it's not right "
               "for you, email hello@lumenskincare.example and we'll sort a full refund."},
    {"keys": ["how much", "price", "cost", "expensive", "discount", "£"],
     "answer": "The Summer Glow Serum is £28, and it's 20% off this week at £22.40. "
               "The offer ends Sunday. 🌿"},
    {"keys": ["cruelty", "vegan", "tested on animals", "leaping bunny"],
     "answer": "Yes — every product is 100% vegan and cruelty-free (Leaping Bunny certified). 🐰"},
    {"keys": ["how long", "results", "see a difference", "weeks", "work"],
     "answer": "Most customers notice a brighter, more hydrated glow within 4–6 weeks of "
               "daily use. Consistency is key!"},
]


def match_faq(text: str) -> str | None:
    t = text.lower()
    for entry in FAQ:
        if any(k in t for k in entry["keys"]):
            return entry["answer"]
    return None


# ── Suggested human drafts (prefilled in the queue, human approves/edits) ────
def suggested_reply(category: str, comment: dict) -> str:
    name = (comment.get("author") or "there").split()[0]
    faq = match_faq(comment.get("text", ""))
    if faq:
        return faq
    if category == "negative":
        return (f"Hi {name}, I'm really sorry to hear this — that's not the experience we "
                "want you to have. I've flagged your order to our team; could you drop us a "
                "DM with your order number so we can put it right today?")
    return ""


# ── The SOP routing decision (pure, no side effects) ─────────────────────────
def route(comment: dict, analysis: dict, threshold: float, sop: dict) -> dict:
    """Decide what SHOULD happen to one comment. No Graph calls here."""
    cat = analysis["category"]
    conf = analysis["confidence"]
    rule = sop["rules"][cat]
    action = rule["action"]

    # complaints (and any category flagged auto=False) always see a human
    if not rule["auto"]:
        return _queue(cat, f"SOP: all '{cat}' comments are routed to a human.",
                      suggested_reply(cat, comment))

    # below the confidence threshold -> escalate
    if conf < threshold:
        return _queue(cat, f"Confidence {conf:.0%} is below the {threshold:.0%} threshold "
                           "— escalated for a human decision.",
                      suggested_reply(cat, comment))

    # a question can only be auto-answered if the FAQ covers it
    if cat == "question":
        faq = match_faq(comment.get("text", ""))
        if not faq:
            return _queue(cat, "No FAQ match — a human should answer this one.",
                          suggested_reply(cat, comment))
        return _auto("reply", faq, cat,
                     f"Question at {conf:.0%} confidence, matched the FAQ playbook.")

    if action == "hide":
        return _auto("hide", None, cat,
                     f"{cat.title()} at {conf:.0%} confidence — above threshold, auto-hidden.")
    if action == "like":
        return _auto("like", None, cat,
                     f"Positive at {conf:.0%} confidence — auto-liked.")
    # any other prescribed reply action
    return _auto("reply", suggested_reply(cat, comment), cat,
                 f"{cat.title()} at {conf:.0%} confidence — auto-replied.")


def _auto(action: str, payload: str | None, category: str, reason: str) -> dict:
    return {"route": "auto", "action": action, "payload": payload,
            "category": category, "reason": reason}


def _queue(category: str, reason: str, draft: str) -> dict:
    return {"route": "queue", "action": None, "payload": None,
            "category": category, "reason": reason, "draft": draft}


# ── Graph-API-shaped adapter (SIMULATED) ─────────────────────────────────────
def _call(method: str, path: str, params: dict | None) -> dict:
    return {
        "method": method,
        "endpoint": f"https://graph.facebook.com/{GRAPH_VERSION}/{path}",
        "params": params or {},
        "simulated": True,
        "note": "Would execute against the live Page with a Page access token.",
    }


def graph_hide(comment_id: str) -> dict:
    # Real Graph API: POST /{comment-id} with is_hidden=true
    return _call("POST", comment_id, {"is_hidden": True})


def graph_unhide(comment_id: str) -> dict:
    return _call("POST", comment_id, {"is_hidden": False})


def graph_delete(comment_id: str) -> dict:
    return _call("DELETE", comment_id, None)


def graph_reply(comment_id: str, message: str) -> dict:
    return _call("POST", f"{comment_id}/comments", {"message": message})


def graph_like(comment_id: str) -> dict:
    return _call("POST", f"{comment_id}/likes", None)


def execute(action: str, comment_id: str, payload: str | None) -> dict:
    """Run the (simulated) Graph call for an auto-action; return the call record."""
    if action == "hide":
        return graph_hide(comment_id)
    if action == "delete":
        return graph_delete(comment_id)
    if action == "reply":
        return graph_reply(comment_id, payload or "")
    if action == "like":
        return graph_like(comment_id)
    raise ValueError(f"unknown action {action!r}")
