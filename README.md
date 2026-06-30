# LZD24 Support — RAG Chatbot for lizenzdeals24.de

A production-grade Retrieval-Augmented-Generation chatbot for a Shopware 6
software-license shop. It answers **product & FAQ questions in German and
English**, strictly from the shop's own catalog, and is built to **decline
rather than hallucinate**.

```
Shopware Store API ──ingest.py──► Supabase (pgvector)
                                        ▲
Browser widget ──► FastAPI /chat ───────┘──► Gemini (embed + Flash-Lite)
```

- **Backend:** Python FastAPI (async) — deploy to Render / Hugging Face Spaces free tier.
- **Vector DB:** Supabase Postgres + `pgvector`.
- **LLM:** Google Gemini free tier — `gemini-2.5-flash-lite` (chat) + `gemini-embedding-001` (768-dim embeddings).
- **Widget:** single embeddable, dependency-free `widget.js` (Google-Tag-Manager friendly).
- **All secrets via `.env`** — nothing is hardcoded.

---

## Repository layout

```
itsnow24/
├─ backend/
│  ├─ main.py            FastAPI app — POST /chat, GET /health
│  ├─ ingest.py          Shopware → embeddings → Supabase (idempotent)
│  ├─ config.py          Env loading + shared helpers
│  ├─ requirements.txt
│  ├─ .env.example       Copy to .env and fill in
│  ├─ db/schema.sql      Tables, ivfflat index, match_products() RPC
│  ├─ render.yaml        Render.com blueprint
│  └─ Dockerfile         For Hugging Face Spaces / containers
├─ widget/
│  ├─ widget.js          The embeddable chat widget (all logic + styles)
│  └─ widget.html        Minimal one-tag embed example
├─ index.html            Standalone staging demo page (loads the widget)
└─ README.md
```

---

## 1. Prerequisites

- Python 3.10+
- A free [Supabase](https://supabase.com) project
- A free [Google AI Studio](https://aistudio.google.com/app/apikey) (Gemini) API key
- A Shopware 6 **sales-channel access key** (`sw-access-key`) for the Store API

---

## 2. Database setup (one time)

In the **Supabase dashboard → SQL Editor**, paste and run
[`backend/db/schema.sql`](backend/db/schema.sql). This:

- enables `pgvector`,
- creates `products` (with a `vector(768)` column) and `unanswered`,
- creates the cosine `ivfflat` index,
- creates the `match_products(query_embedding, match_count)` RPC used by the API.

It is safe to re-run.

---

## 3. Configure secrets

```bash
cd backend
cp .env.example .env       # Windows: copy .env.example .env
```

Edit `.env`:

| Variable          | What it is                                                            |
|-------------------|-----------------------------------------------------------------------|
| `STORE_API_URL`   | Shop base URL, no trailing slash (e.g. `https://lizenzdeals24.de`)     |
| `STORE_API_KEY`   | Shopware sales-channel access key (`sw-access-key`)                    |
| `GEMINI_API_KEY`  | Google AI Studio key                                                   |
| `SUPABASE_URL`    | `https://<ref>.supabase.co`                                            |
| `SUPABASE_KEY`    | Supabase **service_role** key (server-side only — never in the browser)|
| `ALLOWED_ORIGINS` | Comma-separated CORS origins (shop + staging page)                     |

> **Security:** the `service_role` key bypasses Row Level Security. It lives
> only on the backend. The widget talks to **your** API, never to Supabase or
> Gemini directly, so no secret ever reaches the browser.

---

## 4. Install & run the ingestion

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate    # Windows
# or: python3 -m venv .venv && source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt

# Preview what will be embedded (no API calls to Gemini/Supabase writes):
python ingest.py --dry-run

# Full run — fetches all ~188 products, embeds, upserts:
python ingest.py
```

`ingest.py` paginates the Store API (100/page), builds one German text chunk per
product (name, manufacturer, categories, grouped properties, description, price),
embeds it with `gemini-embedding-001` at 768 dimensions, and **upserts** by Shopware product id — so
re-running refreshes data instead of duplicating it. It backs off automatically
on Gemini `429` rate limits.

---

## 5. Run the backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

- Health check: <http://localhost:8000/health>
- API docs (Swagger): <http://localhost:8000/docs>
- Streaming chat: `POST /chat/stream` (`text/event-stream`)

Quick test:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Habt ihr Microsoft Office Lizenzen?"}'
```

Response shape:

```json
{ "answer": "…", "sources": [ { "id": "…", "name": "…", "similarity": 0.81 } ] }
```

### How it stays accurate

1. Detects language (DE/EN) unless `lang` is supplied.
2. Embeds the question and exact-searches the **top 5** products from the
   cached Supabase catalog.
3. If the best match is below `MIN_SIMILARITY` (default `0.64`), it **declines**
   and logs the question to the `unanswered` table — no LLM guess.
4. Otherwise it passes only the retrieved chunks as `CONTEXT` to Flash-Lite under
   a strict anti-hallucination system prompt.
5. Gemini `429`/errors → if a confident catalog match exists, it answers from
   stored product metadata (name/price) instead of guessing; otherwise it uses
   the polite localized fallback ("Bitte versuchen Sie es später erneut …").

**PII segregation:** `/chat` is product/FAQ only. It never asks for or stores
names, emails, order numbers, or payment data. Quote/complaint intent is routed
to the configured support email without sending personal data to the LLM.

---

## 6. Embed the widget

The widget is a single script. Add it to any page (or a **Google Tag Manager**
Custom HTML tag):

```html
<script>
  window.LZD24_CONFIG = {
    backendUrl: "https://your-api-host/chat",   // your deployed FastAPI /chat
    defaultLang: "de",
    avatarUrl: "https://lizenzdeals24.de/media/f8/33/c3/1782816369/Support%20Chatbot%20Icon%20Mensch.png?ts=1782816369",
    agentAvatarUrl: "",
    useAgentAvatar: false,
    primaryColor: "#1d4ed8",
    primaryColorDark: "#0f1e3d",
    accentColor: "#2563eb",
    offsetBottom: 112,
    offsetRight: 20,
    greetingDE: "Wir sind online für Sie",
    greetingEN: "We are online for you",
    quickRepliesDE: [
      { icon: "🔑", text: "Lizenzschlüssel nicht erhalten" },
      { icon: "⚠", text: "Lizenzschlüssel funktioniert nicht" },
      { icon: "💻", text: "Hilfe bei Installation" },
      { icon: "🧾", text: "Hilfe mit Rechnung" },
      { icon: "💬", text: "Beratung" }
    ]
  };
</script>
<script src="https://your-cdn/widget.js" defer></script>
```

All tunables (avatar, greetings, colors, backend URL, DE/EN default, quick
replies and launcher offsets) live in the `CONFIG` object at the top of
[`widget/widget.js`](widget/widget.js) and can be overridden via
`window.LZD24_CONFIG` **without touching the logic**. The widget shows a floating
bubble, greeting popup card, DE/EN toggle, quick replies, streaming typing
updates, and the disclaimer *"Bitte keine persönlichen Daten eingeben."*

Make sure the page's origin is listed in `ALLOWED_ORIGINS` on the backend.

---

## 7. Try the staging demo

Open [`index.html`](index.html) in a browser (or serve it):

```bash
# from the project root
python -m http.server 5500
# then visit http://localhost:5500/  (add it to ALLOWED_ORIGINS)
```

Suggested acceptance tests:

| Type        | Example                                              | Expected |
|-------------|------------------------------------------------------|----------|
| 🇩🇪 German   | „Habt ihr Microsoft Office Lizenzen und was kosten die?“ | Answers from catalog, in German |
| 🇬🇧 English  | "Do you sell Windows 11 licenses? How much?"         | Answers from catalog, in English |
| ⚠️ Out-of-scope | „Wie ist das Wetter morgen?“                      | **Declines**, points to support — no invented facts |

---

## 8. Deploy the backend (free tier)

**Render** — push the repo, *New → Blueprint*, pick
[`backend/render.yaml`](backend/render.yaml), then set the secret env vars in the
dashboard.

**Hugging Face Spaces** — create a *Docker* Space, push the `backend/` folder
(it contains the [`Dockerfile`](backend/Dockerfile)), and add the secrets under
*Settings → Variables and secrets*. Spaces serves on port 7860 (handled by the
Dockerfile).

After deploying, set the widget's `backendUrl` to the deployed `/chat` URL and
add the shop + staging origins to `ALLOWED_ORIGINS`.

## 9. Shopware storefront integration package

This repo includes two live-embed options:

- `build/Lzd24Chatbot.zip` — installable Shopware plugin package with settings
  for backend URL, bot name, avatar URL, greetings, colors, support email and
  WhatsApp URL.
- `deploy/gtm-custom-html.html` — Google Tag Manager Custom HTML fallback.

See [`deploy/live-deploy-checklist.md`](deploy/live-deploy-checklist.md) for the
step-by-step go-live checklist.

---

## Notes & limits

- Free Gemini tier has per-minute request limits; ingestion paces itself and the
  API degrades gracefully on `429`.
- Re-run `python ingest.py` whenever the catalog changes (e.g. via a daily cron).
- The `unanswered` table is your content-gap backlog — review it periodically.
