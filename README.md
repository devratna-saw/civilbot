# CivilBot

A free-to-run chatbot for everyone, with a Civil/Structural-engineering mode that
grounds its numeric answers in a real calculation engine instead of guessing.

- **General mode** — a normal helpful assistant, for any topic.
- **Learn mode** — a tutor for civil engineering students: explains *why* a formula
  gives the number it does, using the same engine as Professional mode.
- **Professional mode** — for engineers checking real designs. Every numeric result
  (bending moment, deflection, required section depth, buckling load) comes from
  `backend/app/structural_engine.py`, not from the language model — the model is
  required to call the calculation tool rather than estimate.
- **PDF upload** — extracts spans, loads, dimensions and material grades from an
  uploaded spec/calc-sheet PDF (heuristic, regex-based) and feeds them into the chat
  as context so you can ask "does this section pass?" about your own document.
- **Standalone Simulator panel** — beam, column, and truss calculators usable without
  the chatbot at all (truss geometry is easier to enter as JSON/a form than in chat),
  each with an auto-generated loading/shear/moment or force diagram (see below).
- **Images inline in chat** — asking about a beam in chat (e.g. "explain this beam with
  a diagram") automatically attaches its loading/shear/moment diagram to the reply, so
  text and image both show up together. Asking for a non-technical picture ("show me a
  suspension bridge") routes to the AI image tool instead — the model is told never to
  use that one for engineering numbers, only calculate_beam's own diagram counts there.
- **Engineering diagrams** — `backend/app/diagrams.py` renders loading/shear-force/
  bending-moment diagrams and colour-coded truss force diagrams straight from the
  structural_engine's own numbers (matplotlib) — free and exact, not AI-generated.
- **AI image generation** — a separate "Generate an image" panel using
  [Pollinations.ai](https://pollinations.ai)'s free, keyless endpoint
  (`backend/app/image_gen.py`). Illustrative only (not engineering-accurate), and
  since it's a shared public service it occasionally returns a "busy, try again"
  error under load — that's the trade-off for zero cost/zero signup. Gemini's own
  image models (`gemini-*-image`, "nano banana") are wired for later: they showed
  in the model catalog but have a **free-tier quota of zero** on this project —
  swapping to them once you enable billing is a one-file change in `image_gen.py`.

## Architecture (kept deliberately small so it runs free)

- `backend/` — FastAPI app. One process serves the JSON API *and* the static
  frontend, so it deploys as a single free web service.
  - `structural_engine.py` — closed-form statics: beam bending/shear/deflection,
    truss method-of-joints (statically determinate only), Euler column buckling.
  - `pdf_parser.py` — text/table extraction + regex-based parameter detection.
  - `gemini_client.py` — wraps the Gemini free-tier API with function-calling
    wired to the engine.
  - `session_store.py` — in-memory per-session chat state (fine for a small
    pilot; resets on server restart — swap for Redis/SQLite if this needs to
    survive restarts or scale past a single process).
- `frontend/` — plain HTML/CSS/JS, no build step, so there's nothing to compile
  in CI or on Render.

This is **not** a general-purpose FEA solver — the truss solver only handles
statically determinate trusses via classical statics, and beam/column formulas
cover the standard textbook cases. That's an intentional scope choice to keep
this both explainable to students and cheap enough to run for free.

## 1. Get a free Gemini API key

Go to <https://aistudio.google.com/apikey>, sign in with a Google account, and
create a free API key. Do not share this key or commit it to git.

## 2. Run locally

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY=your-key-here
uvicorn app.main:app --reload --port 8000
```

Open <http://localhost:8000> — the backend also serves the frontend.

## 3. Deploy free on Render

1. Push this project to a GitHub repo (Render deploys from git).
2. On <https://render.com>, sign up (free), click **New > Blueprint**, and point
   it at your repo — it will read `render.yaml` and set up the service.
   (Alternatively: **New > Web Service**, build command
   `pip install -r backend/requirements.txt`, start command
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT --app-dir backend`.)
3. In the service's **Environment** tab, add `GEMINI_API_KEY` with your key
   from step 1 (enter it directly in Render's dashboard — never put real keys
   in files you commit).
4. Deploy. Render's free web service tier handles a handful of concurrent
   users fine for a pilot; it sleeps after ~15 minutes of no traffic and wakes
   on the next request (a few seconds' delay on the first message after idle).

### Concurrency note

`MAX_CONCURRENT_CHATS` (default 5) caps how many chat requests hit Gemini at
once, so a burst of users queues briefly instead of all hitting a free-tier
rate limit simultaneously. Raise it only if you've confirmed your Gemini quota
supports more.

## Known limitations (v1)

- Chat history lives in memory per server process — restarting the server
  clears active conversations.
- PDF parameter extraction is regex-based; it will miss or misread values in
  scanned/handwritten drawings or unusual formatting. It's meant to speed up
  data entry, not to replace reading the document.
- The truss calculator only accepts statically determinate trusses; an
  indeterminate or unstable input returns an explanatory error rather than a
  (possibly wrong) number.
- No auth/accounts yet — anyone with the URL can use it. Fine for a small
  pilot; add an access gate before sharing the link widely.
