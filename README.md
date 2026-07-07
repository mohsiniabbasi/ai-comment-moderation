# AI Comment Moderation Console

A live web console that moderates the comments a **direct-to-consumer brand**
gets under a paid Facebook ad — the way a real support/social team would want it
done: **AI does the certain calls, a human sees everything ambiguous.**

Built for the Pivot Bureau portfolio (4th demo, same conventions as the Lead
Intelligence Dashboard, Document→Report Automation, Grant Agent and AI Inbox
Manager). Synthetic data only — no real people, no real Facebook Page.

## What it does

1. **Ingests** a realistic feed of ad comments — spam, abuse, genuine
   questions, angry complaints, praise, and deliberately *ambiguous* ones.
2. **Classifies** each comment (`spam` / `abuse` / `question` / `negative` /
   `positive`) with a **confidence score**, via a **real live LLM call**.
3. **Routes by SOP + confidence:**
   - high-confidence **spam / abuse** → **auto-hidden**
   - **questions** that match the **FAQ playbook** → **auto-replied**
   - **positive** comments → **auto-liked**
   - **complaints** → **always a human** (brand-safety policy)
   - anything **below the confidence threshold** → **Human Review Queue**
4. **Confidence-threshold slider** — raise it and more borderline items escalate
   to a human. Safety made tangible.
5. **Editable SOP** (toggle which categories may act automatically) + an
   **append-only audit log** of every action.

## Honesty (the important bit)

- **Classification is a real API call** — Gemini 2.5 Flash-Lite
  (`GEMINI_API_KEY`) or Claude Haiku (`ANTHROPIC_API_KEY`). With no key it runs a
  transparent **rule-based** engine, so the demo always works at zero cost.
- **Meta actions are Graph-API-shaped but simulated.** Every hide / delete /
  reply / like is emitted as the exact Graph API call — correct method,
  endpoint (`https://graph.facebook.com/v19.0/{comment-id}…`) and params — and
  logged in the audit trail, marked `SIMULATED`. No Page token or Facebook app
  review is needed to run it. Drop in a Page access token and the identical
  calls go live.

## Run it

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8021
# open http://localhost:8021
```

Optional live LLM:

```bash
# either one
export GEMINI_API_KEY=...        # gemini-2.5-flash-lite
export ANTHROPIC_API_KEY=...     # claude-haiku-4-5
```

## Layout

```
app/
  main.py        FastAPI endpoints (state / process / resolve / reset)
  agent.py       classifier — live LLM (Gemini/Claude) with rule-based fallback
  moderation.py  SOP routing + FAQ playbook + Graph-API-shaped adapter
  data.py        synthetic comment feed + in-memory state + SOP
  static/index.html   the console UI (vanilla JS)
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/state` | comments + analysis + disposition, queue, SOP, audit, KPIs |
| POST | `/api/process` | apply threshold / SOP edits, classify + route + auto-act |
| POST | `/api/queue/{id}/resolve` | human resolves a queued comment (reply/hide/dismiss) |
| POST | `/api/reset` | reset demo state |

*Demonstration build — synthetic data. Not a paid client engagement.*
