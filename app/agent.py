"""The classifier: read one comment -> category + confidence + reason.

Two backends behind one interface (same pattern as the other Pivot Bureau
demos):
  * A LIVE LLM call when a key is set — Gemini 2.5 Flash-Lite (GEMINI_API_KEY)
    or Claude Haiku (ANTHROPIC_API_KEY). One structured-JSON call returns the
    category, a calibrated 0..1 confidence and a short reason.
  * A deterministic rule-based engine otherwise, so the demo ALWAYS runs with
    zero keys and zero cost. The rules are transparent and produce a realistic
    spread — including LOW confidence on the deliberately ambiguous comments,
    which is what makes the confidence-threshold slider meaningful.

The classifier NEVER hides, deletes or replies to anything. It only produces a
label + confidence. What happens next is decided by the SOP + threshold in
moderation.py, and low-confidence / policy-flagged items go to a human. That
human-in-the-loop step is the whole point.
"""
from __future__ import annotations

import json
import os
import re

CATEGORIES = ["spam", "abuse", "question", "negative", "positive"]

# ── Rule-based backend ──────────────────────────────────────────────────────
# (keyword, weight) signals per category.
_SIGNALS: dict[str, list[tuple[str, float]]] = {
    "spam": [
        ("dm me", 2.0), ("work from home", 2.0), ("/day", 2.0), ("per day", 1.5),
        ("make £", 1.5), ("make $", 1.5), ("link in bio", 2.0), ("bit.ly", 2.0),
        ("http", 1.5), ("www.", 1.2), ("half price", 1.5), ("free gift", 1.8),
        ("claim", 1.2), ("selected", 1.2), ("congratulations", 1.5),
        ("💰", 1.5), ("get started", 1.0), ("my page", 1.5), ("investment", 1.2),
    ],
    "abuse": [
        ("clown", 1.8), ("scammer", 1.8), ("scam", 1.4), ("garbage", 1.2),
        ("idiot", 2.0), ("rubbish", 1.0), ("the lot of you", 1.5),
        ("you're all", 1.2), ("🤡", 1.5), ("shut up", 1.5), ("pathetic", 1.4),
    ],
    "negative": [
        ("disappointed", 1.6), ("waste", 1.6), ("broke me out", 1.8),
        ("still waiting", 1.6), ("refund", 1.4), ("no reply", 1.4),
        ("terrible", 1.6), ("awful", 1.6), ("worst", 1.6), ("never arrived", 1.8),
        ("hasn't updated", 1.4), ("sort it out", 1.4), ("angry", 1.4),
    ],
    "positive": [
        ("obsessed", 1.8), ("love", 1.4), ("best", 1.2), ("amazing", 1.5),
        ("glow", 1.0), ("worth every penny", 1.8), ("never looked better", 1.8),
        ("recommend", 1.4), ("repurchas", 1.6), ("😍", 1.2), ("✨", 0.8),
        ("lovely", 1.0), ("brilliant", 1.4),
        # weak "hype" emoji — enough to lean positive, but the emoji-only
        # penalty keeps confidence low so they still reach a human
        ("🔥", 0.6), ("👏", 0.6), ("🙌", 0.6), ("💛", 0.6), ("👀", 0.4),
    ],
}
_QUESTION_LEAD = re.compile(
    r"^\s*(do|does|is|are|how|what|when|where|which|can|could|will|would|should|any)\b",
    re.I,
)
_EMOJI_ONLY = re.compile(r"^[\W\d_]+$")   # no letters at all (emoji/punct only)
_SARCASM = ["🙄", "sure it", "yeah right", "supposedly"]


def _classify_rules(text: str) -> dict:
    t = text.lower()
    scores = {c: 0.0 for c in CATEGORIES}
    for cat, sigs in _SIGNALS.items():
        for kw, w in sigs:
            if kw in t:
                scores[cat] += w
    # structural question signal
    if "?" in text or _QUESTION_LEAD.match(text):
        scores["question"] += 1.6

    best = max(scores, key=scores.get)
    top = scores[best]
    ordered = sorted(scores.values(), reverse=True)
    second = ordered[1] if len(ordered) > 1 else 0.0

    if top == 0.0:
        # nothing fired — genuinely ambiguous
        category = "question" if "?" in text else "negative"
        confidence = 0.42
    else:
        margin = top - second
        confidence = 0.55 + 0.11 * top + 0.12 * margin

    # ── ambiguity penalties: pull confidence down for the tricky ones ──
    words = re.findall(r"[a-z']+", t)
    if _EMOJI_ONLY.search(text.strip()) or len(words) <= 2:
        confidence = min(confidence, 0.55)          # emoji-only / ultra-terse
    if any(m in t for m in _SARCASM) or ("'" in text and len(words) <= 5):
        confidence = min(confidence, 0.52)          # sarcasm / scare-quotes
    # mixed positive AND negative signal present -> conflicted
    if scores["positive"] > 0 and scores["negative"] > 0:
        confidence -= 0.15
    if "not sure" in t or "tbh" in t:
        confidence -= 0.08

    confidence = round(max(0.30, min(confidence, 0.97)), 2)
    return {
        "category": category if top == 0.0 else best,
        "confidence": confidence,
        "reason": _rule_reason(category if top == 0.0 else best, confidence, scores),
        "engine": "rules",
    }


def _rule_reason(category: str, confidence: float, scores: dict) -> str:
    if confidence < 0.6:
        return f"Weak / conflicting signals — leaning '{category}' but low confidence."
    return f"Matched '{category}' signals ({confidence:.0%} confidence)."


# ── LLM backends (optional, live) ───────────────────────────────────────────
_SYS = (
    "You moderate comments left on a UK direct-to-consumer skincare brand's paid "
    "Facebook ad. Classify ONE comment into exactly one category and give a "
    "calibrated confidence. Be deliberately LOW-confidence (below 0.6) when a "
    "comment is sarcastic, emoji-only, mixed, or otherwise genuinely ambiguous — "
    "those should reach a human. Respond with ONLY a JSON object, no prose:\n"
    '{"category": one of ["spam","abuse","question","negative","positive"], '
    '"confidence": 0..1, "reason": short string}\n'
    "Definitions: spam = promotion/scams/off-topic selling; abuse = insults or "
    "harassment; question = a genuine query about the product/order; negative = "
    "an unhappy customer or complaint; positive = praise."
)


def _llm_gemini(text: str) -> dict:
    from google import genai  # lazy import; demo runs without the dep
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    model = os.environ.get("MODERATION_GEMINI_MODEL", "gemini-2.5-flash-lite")
    resp = client.models.generate_content(
        model=model,
        contents=f"{_SYS}\n\nComment:\n{text}",
    )
    raw = resp.text or ""
    return _finish(text, raw, f"llm:{model}")


def _llm_claude(text: str) -> dict:
    import anthropic  # lazy import
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    model = os.environ.get("MODERATION_MODEL", "claude-haiku-4-5-20251001")
    msg = client.messages.create(
        model=model, max_tokens=300, system=_SYS,
        messages=[{"role": "user", "content": f"Comment:\n{text}"}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return _finish(text, raw, f"llm:{model}")


def _finish(text: str, raw: str, engine: str) -> dict:
    parsed = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
    cat = parsed.get("category")
    if cat not in CATEGORIES:
        raise ValueError(f"bad category {cat!r}")
    conf = round(max(0.0, min(float(parsed.get("confidence", 0.5)), 1.0)), 2)
    return {
        "category": cat,
        "confidence": conf,
        "reason": (parsed.get("reason") or "").strip()[:160] or "Classified by LLM.",
        "engine": engine,
    }


def engine_name() -> str:
    if os.environ.get("GEMINI_API_KEY"):
        return "llm:gemini"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "llm:claude"
    return "rules"


def classify(comment: dict) -> dict:
    """Return the classification for one comment.

    Prefers a live LLM when a key is present; any error falls back to the
    rule-based engine so the demo can never hard-fail in front of a client.
    """
    text = comment.get("text", "")
    if os.environ.get("GEMINI_API_KEY"):
        try:
            return _llm_gemini(text)
        except Exception:  # noqa: BLE001 — never let the demo break
            pass
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return _llm_claude(text)
        except Exception:  # noqa: BLE001
            pass
    return _classify_rules(text)
