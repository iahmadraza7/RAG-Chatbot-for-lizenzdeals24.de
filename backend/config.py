"""Shared configuration & small helpers for the LZD24 RAG chatbot.

Loads everything from environment variables (via a local `.env` in dev).
Both `ingest.py` and `main.py` import from here so endpoints, model names and
the embedding contract stay in exactly one place.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"), override=True)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _require(name: str) -> str:
    val = _env(name)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill it in."
        )
    return val


# --- Shopware ---------------------------------------------------------------
STORE_API_URL = _env("STORE_API_URL").rstrip("/")
STORE_API_KEY = _env("STORE_API_KEY")

# --- Gemini -----------------------------------------------------------------
GEMINI_API_KEY = _env("GEMINI_API_KEY")
GEMINI_CHAT_MODEL = _env("GEMINI_CHAT_MODEL", "gemini-2.5-flash-lite")
GEMINI_EMBED_MODEL = _env("GEMINI_EMBED_MODEL", "gemini-embedding-001")
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Keep in sync with the vector column in db/schema.sql.
EMBED_DIM = int(_env("GEMINI_EMBED_DIM", "768"))

# --- Supabase ---------------------------------------------------------------
SUPABASE_URL = _env("SUPABASE_URL").rstrip("/")
SUPABASE_KEY = _env("SUPABASE_KEY")

# --- Retrieval tuning -------------------------------------------------------
TOP_K = int(_env("TOP_K", "5"))
MIN_SIMILARITY = float(_env("MIN_SIMILARITY", "0.45"))
# Optional override for production. If omitted, the configured MIN_SIMILARITY is
# used directly so lowering the threshold actually takes effect.
EFFECTIVE_MIN_SIMILARITY = float(_env("MIN_EFFECTIVE_SIMILARITY", str(MIN_SIMILARITY)))

# --- Support routing --------------------------------------------------------
SUPPORT_EMAIL = _env("SUPPORT_EMAIL", "support@lizenzdeals24.de")
WHATSAPP_URL = _env("WHATSAPP_URL")
WHATSAPP_NUMBER = _env("WHATSAPP_NUMBER")
EMAIL_API_KEY = _env("EMAIL_API_KEY")
EMAIL_FROM = _env("EMAIL_FROM", f"LizenzDeals24 <{SUPPORT_EMAIL}>")

# --- CORS -------------------------------------------------------------------
ALLOWED_ORIGINS = [
    o.strip()
    for o in _env(
        "ALLOWED_ORIGINS",
        "https://lizenzdeals24.de,https://www.lizenzdeals24.de",
    ).split(",")
    if o.strip()
]


def require_gemini() -> str:
    return _require("GEMINI_API_KEY")


def require_supabase() -> tuple[str, str]:
    return _require("SUPABASE_URL").rstrip("/"), _require("SUPABASE_KEY")


def require_store() -> tuple[str, str]:
    return _require("STORE_API_URL").rstrip("/"), _require("STORE_API_KEY")


def require_email_api_key() -> str:
    return _require("EMAIL_API_KEY")


def supabase_headers(key: str) -> dict[str, str]:
    """Standard PostgREST auth headers using the service-role key."""
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def vector_literal(embedding: list[float]) -> str:
    """pgvector wants its input as the text literal `[1,2,3]`.

    Passing it as a JSON string through PostgREST is the most reliable way to
    insert/compare vectors regardless of client serialization quirks.
    """
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"
