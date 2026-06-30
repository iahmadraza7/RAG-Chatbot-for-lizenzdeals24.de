"""LZD24 Support — RAG chat backend (FastAPI, async).

POST /chat        -> product / FAQ questions answered strictly from retrieved context.
POST /chat/stream -> streaming SSE variant of /chat.
GET  /health      -> liveness probe.

Design constraints (do NOT relax):
  * Anti-hallucination: the model answers ONLY from retrieved CONTEXT.
  * PII segregation: this endpoint never asks for or processes personal data,
    order numbers, or payments. Quote/complaint handling lives elsewhere.
"""
from __future__ import annotations

import re
import math
import time
import json

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import config

app = FastAPI(title="LZD24 Support API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)

# A single shared async client (created on startup) for connection reuse.
_client: httpx.AsyncClient | None = None
_product_cache: tuple[float, list[dict]] = (0.0, [])
PRODUCT_CACHE_TTL = 300


@app.on_event("startup")
async def _startup() -> None:
    global _client
    _client = httpx.AsyncClient(timeout=30.0)


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _client:
        await _client.aclose()


# --- System prompt (strict, anti-hallucination) -----------------------------

SYSTEM_PROMPT = (
    "You are LZD24 Support, the assistant for lizenzdeals24.de, a software "
    "license shop. Answer ONLY using the CONTEXT provided. If the answer is "
    "not clearly in the context, say you don't have that information and "
    "suggest contacting support — do NOT guess or invent products, prices, "
    "keys, or policies. Reply in the requested answer language even if the "
    "context is in another language; keep official product names unchanged. "
    "Be concise and accurate. NEVER ask for or process personal data like "
    "names, emails, order numbers, or payment info in this chat."
)

# Polite, localized fallbacks for rate limits / outages.
FALLBACK = {
    "de": ("Es tut mir leid, im Moment ist der Service stark ausgelastet. "
           "Bitte versuchen Sie es später erneut oder nutzen Sie unser "
           "Kontaktformular."),
    "en": ("Sorry, the service is very busy right now. Please try again later "
           "or use our contact form."),
}
NO_CONTEXT = {
    "de": ("Dazu liegen mir leider keine Informationen vor. Bitte wenden Sie "
           "sich an unseren Support."),
    "en": ("Sorry, I don't have information on that. Please contact our "
           "support team."),
}


GREETING_REPLY = {
    "de": (
        "Hallo, ich bin Ginie - Ihr Lizenzassistent. "
        "Ich helfe Ihnen gerne bei Fragen zu Software-Lizenzen und Produkten."
    ),
    "en": (
        "Hello, I am Ginie - your license assistant. "
        "I can help with software license and product questions."
    ),
}

_GREETING_INTENT = re.compile(
    r"^\s*(hi|hello|hey|hallo|guten\s+(morgen|tag|abend)|servus|moin)\s*[!.?]*\s*$",
    re.IGNORECASE,
)


_CONTACT_INTENT = {
    "de": re.compile(
        r"\b(angebotsanfrage|angebot\s+(anfragen|bekommen|erhalten)|"
        r"kostenvoranschlag|reklamation|beschwerde|retoure|rückgabe|"
        r"widerruf|support\s+kontaktieren|kontakt\s+aufnehmen)\b",
        re.IGNORECASE,
    ),
    "en": re.compile(
        r"\b(quote\s+request|request\s+a\s+quote|get\s+a\s+quote|"
        r"complaint|return|refund|contact\s+support|contact\s+request)\b",
        re.IGNORECASE,
    ),
}


def contact_reply(lang: str) -> str:
    if lang == "en":
        text = (
            f"For quote requests, complaints, or personal support cases, "
            f"please contact {config.SUPPORT_EMAIL} directly. Please do not "
            f"enter personal data in this chat."
        )
        if config.WHATSAPP_URL:
            text += f" For urgent support, you can also use WhatsApp: {config.WHATSAPP_URL}"
        return text

    text = (
        f"Für Angebotsanfragen, Reklamationen oder persönliche Anliegen "
        f"schreiben Sie bitte direkt an {config.SUPPORT_EMAIL}. Bitte geben "
        f"Sie hier im Chat keine persönlichen Daten ein."
    )
    if config.WHATSAPP_URL:
        text += f" Für dringenden Support können Sie auch WhatsApp nutzen: {config.WHATSAPP_URL}"
    return text


def is_contact_intent(text: str, lang: str) -> bool:
    return bool(_CONTACT_INTENT[lang].search(text))


def is_greeting(text: str) -> bool:
    return bool(_GREETING_INTENT.search(text))


def _provider_error(resp: httpx.Response) -> str:
    try:
        return resp.json().get("error", {}).get("message") or resp.text
    except ValueError:
        return resp.text


# --- Request / response models ----------------------------------------------

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    lang: str | None = Field(default=None, description="'de' or 'en'; auto-detected if omitted")


class Source(BaseModel):
    id: str
    name: str
    similarity: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]


# --- Language detection (lightweight heuristic) ------------------------------

_DE_HINTS = {
    "der", "die", "das", "und", "ich", "ist", "nicht", "mit", "für", "ein",
    "eine", "wie", "was", "kann", "gibt", "haben", "kaufen", "kosten", "preis",
    "lizenz", "wie viel", "wieviel", "günstig", "verfügbar", "welche", "wo",
}


def detect_lang(text: str) -> str:
    """Return 'de' or 'en'. German is the shop default, so ties go to 'de'."""
    lowered = text.lower()
    if re.search(r"[äöüß]", lowered):
        return "de"
    words = set(re.findall(r"[a-zäöüß]+", lowered))
    de_hits = len(words & _DE_HINTS)
    en_hits = len(words & {
        "the", "and", "is", "are", "do", "does", "how", "what", "can", "i",
        "you", "price", "cost", "buy", "license", "available", "which", "where",
    })
    if en_hits > de_hits:
        return "en"
    return "de"


# --- Gemini calls ------------------------------------------------------------

async def embed_query(text: str) -> list[float]:
    api_key = config.require_gemini()
    url = (f"{config.GEMINI_BASE}/models/{config.GEMINI_EMBED_MODEL}"
           f":embedContent?key={api_key}")
    payload = {
        "model": f"models/{config.GEMINI_EMBED_MODEL}",
        "content": {"parts": [{"text": text}]},
        "taskType": "RETRIEVAL_QUERY",
        "outputDimensionality": config.EMBED_DIM,
    }
    assert _client is not None
    resp = await _client.post(url, json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Gemini embedding failed ({resp.status_code}): {_provider_error(resp)}"
        )
    resp.raise_for_status()
    return resp.json()["embedding"]["values"]


class RateLimited(Exception):
    """Raised when Gemini returns 429 so the endpoint can fall back politely."""


def build_generation_payload(message: str, context: str, lang: str) -> dict:
    answer_language = "German" if lang == "de" else "English"
    user_turn = (
        f"CONTEXT:\n{context}\n\n"
        f"ANSWER LANGUAGE: {answer_language}\n"
        f"USER QUESTION:\n{message}"
    )
    return {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_turn}]}],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.9,
            "maxOutputTokens": 600,
        },
    }


async def generate_answer(message: str, context: str, lang: str) -> str:
    api_key = config.require_gemini()
    url = (f"{config.GEMINI_BASE}/models/{config.GEMINI_CHAT_MODEL}"
           f":generateContent?key={api_key}")
    payload = build_generation_payload(message, context, lang)
    assert _client is not None
    resp = await _client.post(url, json=payload)
    if resp.status_code == 429:
        raise RateLimited()
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Gemini generation failed ({resp.status_code}): {_provider_error(resp)}"
        )
    resp.raise_for_status()
    data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        # Safety block or empty completion -> treat as "no answer".
        return NO_CONTEXT[lang]
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    return text or NO_CONTEXT[lang]


# --- Supabase retrieval ------------------------------------------------------

def _parse_vector(value: object) -> list[float]:
    if isinstance(value, list):
        return [float(x) for x in value]
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            value = value[1:-1]
        if not value:
            return []
        return [float(x) for x in value.split(",")]
    return []


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


async def _load_products() -> list[dict]:
    """Load product embeddings from Supabase and cache them briefly.

    The catalog is small (~250 products), so exact in-process cosine search is
    more predictable than an approximate ivfflat index that may need manual
    rebuilding after ingestion.
    """
    global _product_cache
    cached_at, cached_rows = _product_cache
    now = time.time()
    if cached_rows and now - cached_at < PRODUCT_CACHE_TTL:
        return cached_rows

    sb_url, sb_key = config.require_supabase()
    url = f"{sb_url}/rest/v1/products?select=id,name,content,metadata,embedding&limit=1000"
    assert _client is not None
    resp = await _client.get(url, headers=config.supabase_headers(sb_key))
    resp.raise_for_status()

    rows = []
    for row in resp.json() or []:
        embedding = _parse_vector(row.get("embedding"))
        if len(embedding) == config.EMBED_DIM:
            row["embedding"] = embedding
            rows.append(row)
    _product_cache = (now, rows)
    return rows

async def search_products(embedding: list[float], top_k: int) -> list[dict]:
    rows = await _load_products()
    scored = []
    for row in rows:
        similarity = _cosine_similarity(embedding, row["embedding"])
        scored.append({
            "id": row["id"],
            "name": row.get("name") or "",
            "content": row.get("content") or "",
            "metadata": row.get("metadata") or {},
            "similarity": similarity,
        })
    scored.sort(key=lambda item: item["similarity"], reverse=True)
    return scored[:top_k]


async def log_unanswered(question: str, lang: str, top_score: float | None) -> None:
    """Best-effort logging of low-confidence questions. Never breaks the reply."""
    try:
        sb_url, sb_key = config.require_supabase()
        url = f"{sb_url}/rest/v1/unanswered"
        headers = config.supabase_headers(sb_key)
        headers["Prefer"] = "return=minimal"
        assert _client is not None
        await _client.post(url, headers=headers, json={
            "question": question[:2000],
            "lang": lang,
            "top_score": top_score,
        })
    except Exception:
        pass  # logging must not affect the user-facing response


async def prepare_context(message: str, lang: str) -> tuple[str | None, list[dict], float | None]:
    """Embed and retrieve with the same anti-hallucination gate used by /chat."""
    embedding = await embed_query(message)
    matches = await search_products(embedding, config.TOP_K)
    top_score = matches[0]["similarity"] if matches else None
    good = [m for m in matches if m.get("similarity", 0) >= config.MIN_SIMILARITY]
    if not good:
        await log_unanswered(message, lang, top_score)
        return None, [], top_score
    context = "\n\n---\n\n".join(m["content"] for m in good)
    return context, good, top_score


def build_sources(matches: list[dict]) -> list[Source]:
    return [
        Source(id=m["id"], name=m.get("name") or m.get("metadata", {}).get("name", ""),
               similarity=round(float(m.get("similarity", 0)), 4))
        for m in matches
    ]


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# --- Routes ------------------------------------------------------------------

@app.get("/")
async def root() -> dict:
    return {
        "status": "ok",
        "health": "/health",
        "docs": "/docs",
        "chat": "POST /chat",
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    message = req.message.strip()
    lang = req.lang if req.lang in ("de", "en") else detect_lang(message)

    if is_greeting(message):
        return ChatResponse(answer=GREETING_REPLY[lang], sources=[])

    if is_contact_intent(message, lang):
        return ChatResponse(answer=contact_reply(lang), sources=[])

    # 1. Embed + retrieve.
    try:
        context, good, _top_score = await prepare_context(message, lang)
    except RuntimeError:
        return ChatResponse(answer=FALLBACK[lang], sources=[])
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 429:
            return ChatResponse(answer=FALLBACK[lang], sources=[])
        raise

    # 2. No confident match -> log the gap and decline (no LLM guess needed).
    if context is None:
        return ChatResponse(answer=NO_CONTEXT[lang], sources=[])

    # 3. Build CONTEXT from the good matches and ask the LLM.
    try:
        answer = await generate_answer(message, context, lang)
    except RateLimited:
        return ChatResponse(answer=FALLBACK[lang], sources=[])
    except RuntimeError:
        return ChatResponse(answer=FALLBACK[lang], sources=[])
    except httpx.HTTPError:
        return ChatResponse(answer=FALLBACK[lang], sources=[])

    return ChatResponse(answer=answer, sources=build_sources(good))


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    message = req.message.strip()
    lang = req.lang if req.lang in ("de", "en") else detect_lang(message)

    async def events():
        if is_greeting(message):
            yield sse("answer", {"answer": GREETING_REPLY[lang], "sources": []})
            yield sse("done", {})
            return

        if is_contact_intent(message, lang):
            yield sse("answer", {"answer": contact_reply(lang), "sources": []})
            yield sse("done", {})
            return

        try:
            context, good, _top_score = await prepare_context(message, lang)
        except (RuntimeError, httpx.HTTPStatusError):
            yield sse("error", {"answer": FALLBACK[lang], "sources": []})
            yield sse("done", {})
            return

        if context is None:
            yield sse("answer", {"answer": NO_CONTEXT[lang], "sources": []})
            yield sse("done", {})
            return

        sources = [s.model_dump() for s in build_sources(good)]
        api_key = config.require_gemini()
        url = (f"{config.GEMINI_BASE}/models/{config.GEMINI_CHAT_MODEL}"
               f":streamGenerateContent?alt=sse&key={api_key}")
        payload = build_generation_payload(message, context, lang)

        assert _client is not None
        try:
            sent_token = False
            async with _client.stream("POST", url, json=payload, timeout=60.0) as resp:
                if resp.status_code == 429:
                    yield sse("error", {"answer": FALLBACK[lang], "sources": []})
                    yield sse("done", {})
                    return
                if resp.status_code >= 400:
                    yield sse("error", {"answer": FALLBACK[lang], "sources": []})
                    yield sse("done", {})
                    return

                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw:
                        continue
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    candidates = data.get("candidates") or []
                    if not candidates:
                        continue
                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        token = part.get("text")
                        if token:
                            sent_token = True
                            yield sse("token", {"text": token})

            if sent_token:
                yield sse("sources", {"sources": sources})
            else:
                yield sse("answer", {"answer": NO_CONTEXT[lang], "sources": []})
            yield sse("done", {})
        except httpx.HTTPError:
            yield sse("error", {"answer": FALLBACK[lang], "sources": []})
            yield sse("done", {})

    return StreamingResponse(events(), media_type="text/event-stream")
