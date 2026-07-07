"""Synthetic DTC Facebook ad-comment feed + in-memory state.

Everything here is fabricated sample data — no real people, no real Facebook
Page, no real ad. The demo ships a realistic spread of comments a direct-to-
consumer brand actually gets under a paid ad (spam, abuse, genuine questions,
angry complaints, praise, and deliberately ambiguous ones) so the AI
classification, the confidence-threshold routing, the human review queue, the
(simulated) Graph-API actions and the audit log all have something to act on.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone

# ── The fictional brand + ad the comments sit under ─────────────────────────
BRAND = {
    "page_name": "Lumen Skincare",
    "page_id": "178904452",                       # fake Page id (Graph-shaped)
    "ad_headline": "Summer Glow Serum — 20% off this week",
    "ad_copy": (
        "Our best-selling vitamin C + hyaluronic serum for a brighter, "
        "hydrated glow. Vegan, cruelty-free, made in the UK. £28 £22.40 today."
    ),
}

# ── The synthetic comment feed ──────────────────────────────────────────────
# Comment ids follow the Graph shape "<page_post>_<comment>" so the adapter
# endpoints read like the real thing.
_PID = BRAND["page_id"]


def _cid(n: int) -> str:
    return f"{_PID}_{100200 + n}"


_SEED_COMMENTS: list[dict] = [
    # — praise —
    {"id": _cid(1), "author": "Hannah Pryce", "avatar": "HP",
     "received": "2026-07-07T08:04:00Z", "likes": 12,
     "text": "Obsessed with this serum 😍 my skin has never looked better, worth every penny!"},
    {"id": _cid(2), "author": "Yusuf Karim", "avatar": "YK",
     "received": "2026-07-07T08:11:00Z", "likes": 4,
     "text": "Repurchased three times now. The glow is real ✨ highly recommend."},

    # — genuine questions (some FAQ-answerable, some not) —
    {"id": _cid(3), "author": "Chloe Bennett", "avatar": "CB",
     "received": "2026-07-07T08:19:00Z", "likes": 1,
     "text": "Do you ship to Ireland? 🇮🇪 and how long does delivery take?"},
    {"id": _cid(4), "author": "Marcus Hale", "avatar": "MH",
     "received": "2026-07-07T08:26:00Z", "likes": 0,
     "text": "how much is it after the discount??"},
    {"id": _cid(5), "author": "Deborah Ellis", "avatar": "DE",
     "received": "2026-07-07T08:33:00Z", "likes": 2,
     "text": "What's your return policy if it doesn't work for me?"},
    {"id": _cid(6), "author": "Ravi Menon", "avatar": "RM",
     "received": "2026-07-07T08:40:00Z", "likes": 3,
     "text": "Is this suitable for very sensitive, eczema-prone skin? I react to most vitamin C serums."},

    # — complaints (negative; brand-safety says a human always sees these) —
    {"id": _cid(7), "author": "Sophie Grant", "avatar": "SG",
     "received": "2026-07-07T08:47:00Z", "likes": 6,
     "text": "Ordered 12 days ago, tracking still hasn't updated and no reply to my emails. Really disappointed."},
    {"id": _cid(8), "author": "Adam Foster", "avatar": "AF",
     "received": "2026-07-07T08:52:00Z", "likes": 2,
     "text": "Broke me out badly within a week. Waste of £28 honestly."},
    {"id": _cid(9), "author": "Nadia Rahman", "avatar": "NR",
     "received": "2026-07-07T09:01:00Z", "likes": 9,
     "text": "Still waiting on a refund from THREE WEEKS ago. Sort it out please."},

    # — spam / promo —
    {"id": _cid(10), "author": "Crypto Wealth", "avatar": "CW",
     "received": "2026-07-07T09:08:00Z", "likes": 0,
     "text": "Make £500/day working from home 💰💰 DM me now to get started!!"},
    {"id": _cid(11), "author": "Glow Deals UK", "avatar": "GD",
     "received": "2026-07-07T09:14:00Z", "likes": 0,
     "text": "Get the SAME serum for half price on my page 👉 link in bio 🔥"},
    {"id": _cid(12), "author": "Rewards Team", "avatar": "RT",
     "received": "2026-07-07T09:20:00Z", "likes": 0,
     "text": "🎁 CONGRATULATIONS! You've been selected for a free gift. Claim now: bit.ly/claim-reward"},

    # — abuse / harassment —
    {"id": _cid(13), "author": "Gary T", "avatar": "GT",
     "received": "2026-07-07T09:27:00Z", "likes": 1,
     "text": "This is absolute garbage and you're all clowns 🤡 scammers the lot of you."},

    # — deliberately ambiguous (the stars of the threshold story) —
    {"id": _cid(14), "author": "Elena Marsh", "avatar": "EM",
     "received": "2026-07-07T09:33:00Z", "likes": 0,
     "text": "lol sure it 'works' 🙄"},
    {"id": _cid(15), "author": "Tomasz W", "avatar": "TW",
     "received": "2026-07-07T09:39:00Z", "likes": 0,
     "text": "🔥🔥🔥"},
    {"id": _cid(16), "author": "Priya Anand", "avatar": "PA",
     "received": "2026-07-07T09:45:00Z", "likes": 1,
     "text": "not sure it's worth the price tbh but the packaging is lovely"},
    {"id": _cid(17), "author": "Karen Doyle", "avatar": "KD",
     "received": "2026-07-07T09:51:00Z", "likes": 5,
     "text": "is this the same formula as the one that got recalled last year??"},
    {"id": _cid(18), "author": "Sam Obi", "avatar": "SO",
     "received": "2026-07-07T09:57:00Z", "likes": 0,
     "text": "👏"},
]

# ── Default SOP (moderation policy) — editable in the console ────────────────
# Per category: what action the SOP prescribes, and whether it may run
# automatically (True) or must always go to a human (False).
_DEFAULT_SOP = {
    "threshold": 0.75,
    "rules": {
        "spam":     {"action": "hide",  "auto": True,
                     "label": "Hide spam & promotional comments"},
        "abuse":    {"action": "hide",  "auto": True,
                     "label": "Hide abusive / harassing comments"},
        "question": {"action": "reply", "auto": True,
                     "label": "Reply to questions from the FAQ playbook"},
        "negative": {"action": "reply", "auto": False,
                     "label": "Always route complaints to a human"},
        "positive": {"action": "like",  "auto": True,
                     "label": "Like positive comments"},
    },
}

# ── Runtime state (in-memory; reset on restart or via /api/reset) ───────────
# analyses: comment_id -> classification {category, confidence, reason, engine}
# disp:     comment_id -> disposition {status, route, action, reason, ...}
# executed: comment_id -> last committed action ("hide"/"reply"/... /"queued"/"resolved")
# audit:    append-only list of {ts, comment_id, actor, action, detail, graph?}
# sop:      the editable moderation policy above
_state: dict = {}


def reset_state() -> None:
    _state["comments"] = copy.deepcopy(_SEED_COMMENTS)
    _state["analyses"] = {}
    _state["disp"] = {}
    _state["executed"] = {}
    _state["audit"] = []
    _state["sop"] = copy.deepcopy(_DEFAULT_SOP)


def _ensure() -> None:
    if not _state:
        reset_state()


def list_comments() -> list[dict]:
    _ensure()
    return _state["comments"]


def get_comment(cid: str) -> dict | None:
    _ensure()
    return next((c for c in _state["comments"] if c["id"] == cid), None)


def get_analysis(cid: str) -> dict | None:
    _ensure()
    return _state["analyses"].get(cid)


def set_analysis(cid: str, analysis: dict) -> None:
    _ensure()
    _state["analyses"][cid] = analysis


def get_disp(cid: str) -> dict:
    _ensure()
    return _state["disp"].get(cid, {})


def set_disp(cid: str, disp: dict) -> None:
    _ensure()
    _state["disp"][cid] = disp


def get_executed(cid: str) -> str | None:
    _ensure()
    return _state["executed"].get(cid)


def set_executed(cid: str, action: str) -> None:
    _ensure()
    _state["executed"][cid] = action


def sop() -> dict:
    _ensure()
    return _state["sop"]


def audit_log() -> list[dict]:
    _ensure()
    return _state["audit"]


def add_audit(cid: str, actor: str, action: str, detail: str, graph: dict | None = None) -> None:
    _ensure()
    _state["audit"].insert(0, {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "comment_id": cid,
        "actor": actor,          # "ai" | "operator"
        "action": action,
        "detail": detail,
        "graph": graph,          # simulated Graph-API call, or None
    })
