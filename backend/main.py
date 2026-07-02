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
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
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
    "Be concise and accurate, but include the complete useful answer from the "
    "available context. When a customer asks about a product, include the "
    "product name, price, Artikelnummer/article number, and product link when "
    "those fields are present in CONTEXT. Answer confidently from CONTEXT; only "
    "say you do not have the information when CONTEXT genuinely does not "
    "contain it. Never translate, localize, shorten, or rewrite URLs. Copy "
    "every URL exactly as it appears after 'Link:' in CONTEXT. "
    "NEVER ask for or process personal data like "
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
        r"kostenvoranschlag|reklamation|beschwerde|"
        r"support\s+kontaktieren|kontakt\s+aufnehmen|"
        r"lizenzschlüssel\s+nicht\s+erhalten)\b",
        re.IGNORECASE,
    ),
    "en": re.compile(
        r"\b(quote\s+request|request\s+a\s+quote|get\s+a\s+quote|"
        r"complaint|contact\s+support|contact\s+request|"
        r"license\s+key\s+not\s+received)\b",
        re.IGNORECASE,
    ),
}

_PRICE_INTENT = re.compile(
    r"\b(kostet|kosten|preis|wieviel|wie\s+viel|price|cost|how\s+much|"
    r"expensive|cheap|cheapest|less\s+expensive|günstig|guenstig|billig|preiswert)\b",
    re.IGNORECASE,
)

_CHEAP_INTENT = re.compile(
    r"\b(cheap|cheapest|less\s+expensive|lowest\s+price|günstig|guenstig|"
    r"günstigste|guenstigste|billig|preiswert)\b",
    re.IGNORECASE,
)

_INFO_INTENT = re.compile(
    r"\b(what\s+is|what\s+are|tell\s+me\s+about|explain|was\s+ist|was\s+sind|"
    r"erklaer|erklär|informationen|info\s+zu)\b",
    re.IGNORECASE,
)

_SHOP_HINT = re.compile(
    r"\b(windows|office|microsoft|server|sql|exchange|adobe|lexware|"
    r"bitdefender|mcafee|kaspersky|eset|antivirus|lizenz|lizenzschlüssel|"
    r"lizenzschluessel|software|produkt|artikelnummer|installation|"
    r"rechnung|license|key|product|invoice|install)\b",
    re.IGNORECASE,
)

_OBVIOUS_OUT_OF_SCOPE = re.compile(
    r"\b(wetter|weather|hauptstadt|capital|präsident|praesident|president|"
    r"fußball|fussball|football|news|nachrichten|recipe|rezept|bitcoin|"
    r"crypto|aktien|stock\s+price)\b",
    re.IGNORECASE,
)


_SHORT_NON_PRODUCT = re.compile(r"^[a-zäöüß\s'.!?-]{1,12}$", re.IGNORECASE)

_SUPPORT_PATTERNS = {
    "en": [
        ("key_not_received", r"license\s+key\s+not\s+received|key\s+not\s+received|not\s+received"),
        ("key_not_working", r"license\s+key\s+does\s+not\s+work|key\s+does\s+not\s+work|activation|activate|activating|doesn'?t\s+work"),
        ("installation", r"help\s+with\s+installation|installation|install"),
        ("invoice", r"help\s+with\s+invoice|invoice|bill|billing|rechnung"),
        ("consultation", r"consultation|license\s+advice|quote\s+request|request\s+a\s+quote|get\s+a\s+quote"),
        ("policy", r"cancel|cancellation|withdraw|withdrawal|revocation|digital\s+(goods|product|ware)|return|refund"),
        ("complaint", r"complaint|contact\s+support|contact\s+request"),
    ],
    "de": [
        ("key_not_received", r"lizenzschlüssel\s+nicht\s+erhalten|lizenzschluessel\s+nicht\s+erhalten|key\s+nicht\s+erhalten|nicht\s+erhalten"),
        ("key_not_working", r"lizenzschlüssel\s+funktioniert\s+nicht|lizenzschluessel\s+funktioniert\s+nicht|aktivierung|aktivier\w*|funktioniert\s+nicht"),
        ("installation", r"hilfe\s+bei\s+installation|installation|installieren"),
        ("invoice", r"hilfe\s+mit\s+rechnung|rechnung|zahlung"),
        ("consultation", r"beratung|lizenzberatung|angebotsanfrage|angebot\s+(anfragen|bekommen|erhalten)|kostenvoranschlag"),
        ("policy", r"widerruf|stornieren|kündigen|kuendigen|retoure|rückgabe|rueckgabe|rückerstattung|rueckerstattung|digitale\s+ware"),
        ("complaint", r"reklamation|beschwerde|support\s+kontaktieren|kontakt\s+aufnehmen"),
    ],
}

_DIRECT_SUPPORT_INTENTS = {"key_not_received", "complaint"}
_FAQ_PREFERRED_INTENTS = {"key_not_working", "installation", "invoice", "policy"}


def support_intent(text: str, lang: str | None = None) -> str | None:
    lowered = text.lower()
    ordered_langs = [lang] if lang in ("de", "en") else []
    ordered_langs.extend(candidate for candidate in ("de", "en") if candidate not in ordered_langs)
    for candidate_lang in ordered_langs:
        for intent, pattern in _SUPPORT_PATTERNS[candidate_lang]:
            if re.search(pattern, lowered, re.IGNORECASE):
                return intent
    return None


def whatsapp_support_link() -> str:
    if config.WHATSAPP_URL:
        return config.WHATSAPP_URL
    number = re.sub(r"\D+", "", config.WHATSAPP_NUMBER or "")
    return f"https://wa.me/{number}" if number else ""


def contact_reply(lang: str, intent: str | None = None) -> str:
    if lang == "en":
        replies = {
            "key_not_received": (
                "If your license key has not arrived, please check your spam/junk folder first. "
                f"If it is still missing, contact {config.SUPPORT_EMAIL}. Please do not enter order "
                "numbers, email addresses, or license keys in this chat."
            ),
            "key_not_working": (
                "For activation problems, please check that the product version matches your license "
                "and copy the key without extra spaces. If it still does not work, contact "
                f"{config.SUPPORT_EMAIL}. Please do not post license keys or order data here."
            ),
            "installation": (
                "I can help with installation questions. Please write the product name and the step "
                "where you are stuck, without personal data or license keys. For direct support, "
                f"contact {config.SUPPORT_EMAIL}."
            ),
            "invoice": (
                f"For invoice or billing questions, please contact {config.SUPPORT_EMAIL}. "
                "Please do not enter invoice numbers, order numbers, or personal data in this chat."
            ),
            "consultation": (
                "For license advice or a quote, you can ask a product question here, or contact "
                f"{config.SUPPORT_EMAIL} for a personal offer. Please do not enter personal data "
                "in this chat."
            ),
            "complaint": (
                f"For complaints, returns, or personal support cases, please contact {config.SUPPORT_EMAIL}. "
                "Please do not enter personal data in this chat."
            ),
        }
        text = replies.get(intent) or (
            f"For quote requests, complaints, or personal support cases, please contact "
            f"{config.SUPPORT_EMAIL} directly. Please do not enter personal data in this chat."
        )
        wa_link = whatsapp_support_link()
        if wa_link:
            text += f" For urgent support, you can also use WhatsApp: {wa_link}"
        return text

    replies = {
        "key_not_received": (
            "Wenn Ihr Lizenzschlüssel noch nicht angekommen ist, prüfen Sie bitte zuerst den Spam-/Junk-Ordner. "
            f"Falls er weiterhin fehlt, kontaktieren Sie {config.SUPPORT_EMAIL}. Bitte geben Sie hier keine "
            "Bestellnummern, E-Mail-Adressen oder Lizenzschlüssel ein."
        ),
        "key_not_working": (
            "Bei Aktivierungsproblemen prüfen Sie bitte zuerst, ob Produktversion und Lizenz zusammenpassen "
            f"und ob der Schlüssel ohne Leerzeichen kopiert wurde. Falls es weiter nicht funktioniert, "
            f"kontaktieren Sie {config.SUPPORT_EMAIL}. Bitte posten Sie hier keine Lizenzschlüssel."
        ),
        "installation": (
            "Ich helfe gern bei Installationsfragen. Schreiben Sie bitte den Produktnamen und bei welchem "
            f"Schritt ein Fehler auftritt, ohne persönliche Daten oder Lizenzschlüssel. Für direkten Support: "
            f"{config.SUPPORT_EMAIL}."
        ),
        "invoice": (
            f"Für Fragen zu Rechnung oder Zahlung kontaktieren Sie bitte {config.SUPPORT_EMAIL}. "
            "Bitte geben Sie hier keine Rechnungsnummern, Bestellnummern oder persönlichen Daten ein."
        ),
        "consultation": (
            "Für Lizenzberatung oder ein Angebot können Sie hier eine Produktfrage stellen oder "
            f"{config.SUPPORT_EMAIL} für ein persönliches Angebot kontaktieren. Bitte geben Sie hier "
            "keine persönlichen Daten ein."
        ),
        "complaint": (
            f"Für Reklamationen, Rückgaben oder persönliche Anliegen kontaktieren Sie bitte {config.SUPPORT_EMAIL}. "
            "Bitte geben Sie hier keine persönlichen Daten ein."
        ),
    }
    text = replies.get(intent) or (
        f"Für Angebotsanfragen, Reklamationen oder persönliche Anliegen schreiben Sie bitte direkt an "
        f"{config.SUPPORT_EMAIL}. Bitte geben Sie hier im Chat keine persönlichen Daten ein."
    )
    wa_link = whatsapp_support_link()
    if wa_link:
        text += f" Für dringenden Support können Sie auch WhatsApp nutzen: {wa_link}"
    return text


def is_contact_intent(text: str, lang: str) -> bool:
    intent = support_intent(text, lang)
    return (
        bool(_CONTACT_INTENT["de"].search(text))
        or bool(_CONTACT_INTENT["en"].search(text))
        or intent in _DIRECT_SUPPORT_INTENTS
    )


def is_greeting(text: str) -> bool:
    return bool(_GREETING_INTENT.search(text))


def is_too_short_for_product_search(text: str) -> bool:
    """Avoid embedding vague fragments like 'I do' into unrelated products."""
    stripped = text.strip()
    if _PRICE_INTENT.search(stripped):
        return False
    return bool(_SHORT_NON_PRODUCT.match(stripped)) and len(re.findall(r"[a-zäöüß]+", stripped.lower())) <= 3


def is_obvious_out_of_scope(text: str) -> bool:
    return bool(_OBVIOUS_OUT_OF_SCOPE.search(text)) and not bool(_SHOP_HINT.search(text))


def _match_price(match: dict) -> str:
    metadata = match.get("metadata") or {}
    price = metadata.get("price")
    if isinstance(price, str) and price.strip():
        return price.strip()
    content = match.get("content") or ""
    found = re.search(r"^Preis:\s*(.+)$", content, re.MULTILINE)
    return found.group(1).strip() if found else ""


def _localized_price(price: str, lang: str) -> str:
    if lang != "de":
        return price
    return re.sub(r"(\d+)\.(\d{2})", r"\1,\2", price)


def _price_number(price: str) -> float | None:
    match = re.search(r"(\d+(?:[.,]\d{1,2})?)", price or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _description(match: dict) -> str:
    content = match.get("content") or ""
    found = re.search(r"Beschreibung:\s*(.+?)(?:\nPreis:|\n[A-ZÄÖÜ][^:\n]{1,30}:|$)", content, re.DOTALL)
    text = found.group(1).strip() if found else content.strip()
    text = re.sub(r"\s+", " ", text)
    name = match.get("name") or ""
    if name and text.lower().startswith(name.lower()):
        text = text[len(name):].strip(" .:-")
    sentences = re.split(r"(?<=[.!?])\s+", text)
    compact = " ".join(sentences[:2]).strip()
    return compact[:520].rstrip()


def _content_field(match: dict, label: str) -> str:
    content = match.get("content") or ""
    found = re.search(rf"^\s*-?\s*{re.escape(label)}:\s*(.+)$", content, re.MULTILINE)
    return found.group(1).strip() if found else ""


def catalog_items(matches: list[dict]) -> list[dict]:
    items = []
    seen = set()
    for match in matches:
        metadata = match.get("metadata") or {}
        if metadata.get("type") == "faq":
            continue
        name = match.get("name") or metadata.get("name") or ""
        price = _match_price(match)
        if not name:
            continue
        key = (name.casefold(), price.casefold())
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "name": name,
            "price": price,
            "price_number": _price_number(price),
            "description": _description(match),
            "vendor": _content_field(match, "Hersteller"),
            "category": _content_field(match, "Kategorie"),
            "delivery": _content_field(match, "Versandart"),
            "product_type": _content_field(match, "Produktart"),
            "feature": _content_field(match, "Eigenschaft"),
            "product_number": metadata.get("product_number") or _content_field(match, "Artikelnummer"),
            "product_url": metadata.get("product_url") or metadata.get("url") or _content_field(match, "Link"),
        })
    return items


def product_detail_suffix(item: dict, lang: str) -> str:
    parts = []
    if item.get("product_number"):
        label = "Article number" if lang == "en" else "Artikelnummer"
        parts.append(f"{label}: {item['product_number']}")
    if item.get("product_url"):
        parts.append(f"Link: {item['product_url']}")
    return (" " + " ".join(parts)) if parts else ""


def product_line(item: dict, lang: str) -> str:
    price = _localized_price(item["price"], lang) if item["price"] else ""
    line = item["name"]
    if price:
        line += f": {price}"
    return line + product_detail_suffix(item, lang)


def catalog_info_answer(item: dict, lang: str) -> str:
    price = _localized_price(item["price"], lang) if item["price"] else ""
    if lang == "en":
        details = []
        if item["vendor"]:
            details.append(f"manufacturer: {item['vendor']}")
        if item["product_type"]:
            details.append(f"product type: {item['product_type']}")
        if item["feature"]:
            details.append(f"area: {item['feature']}")
        if item["category"]:
            details.append(f"category: {item['category']}")
        if item["delivery"]:
            details.append(f"delivery: {item['delivery']}")
        answer = f"{item['name']} is listed in the catalog"
        answer += " with " + ", ".join(details) if details else ""
        answer += "."
        if price:
            answer += f" Current catalog price: {price}."
        return answer + product_detail_suffix(item, lang)

    answer = f"{item['name']}: {item['description']}" if item["description"] else item["name"]
    if price:
        answer += f" Aktueller Katalogpreis: {price}."
    return answer + product_detail_suffix(item, lang)


def catalog_fallback_answer(message: str, matches: list[dict], lang: str) -> str | None:
    """Answer from retrieved catalog metadata only when Gemini is unavailable."""
    items = catalog_items(matches)
    if not items:
        return None

    if _CHEAP_INTENT.search(message):
        priced = [item for item in items if item["price_number"] is not None]
        if priced:
            priced.sort(key=lambda item: item["price_number"])
            best = priced[0]
            price = _localized_price(best["price"], lang)
            if lang == "en":
                lines = [f"The lowest-priced matching option I found is {best['name']} for {price}.{product_detail_suffix(best, lang)}"]
                if len(priced) > 1:
                    lines.append("Other matching options:")
            else:
                lines = [f"Die günstigste passende Option ist {best['name']} für {price}.{product_detail_suffix(best, lang)}"]
                if len(priced) > 1:
                    lines.append("Weitere passende Optionen:")
            for item in priced[1:3]:
                lines.append(f"- {product_line(item, lang)}")
            return "\n".join(lines)

    is_price_question = bool(_PRICE_INTENT.search(message))
    if is_price_question and items[0]["price"]:
        name = items[0]["name"]
        price = _localized_price(items[0]["price"], lang)
        if lang == "en":
            return f"{name} costs {price}.{product_detail_suffix(items[0], lang)}"
        return f"{name} kostet {price}.{product_detail_suffix(items[0], lang)}"

    if _INFO_INTENT.search(message):
        item = items[0]
        return catalog_info_answer(item, lang)

    if lang == "en":
        lines = ["I found these matching products in the catalog:"]
    else:
        lines = ["Ich habe diese passenden Produkte im Katalog gefunden:"]
    for item in items[:3]:
        lines.append(f"- {product_line(item, lang)}")
    return "\n".join(lines)


def faq_matches(matches: list[dict]) -> list[dict]:
    return [m for m in matches if (m.get("metadata") or {}).get("type") == "faq"]


def _faq_title(match: dict) -> str:
    metadata = match.get("metadata") or {}
    return metadata.get("title") or metadata.get("name") or match.get("name") or "FAQ"


def _faq_link(match: dict) -> str:
    metadata = match.get("metadata") or {}
    return metadata.get("url") or _content_field(match, "Link")


def _faq_body(match: dict) -> str:
    content = match.get("content") or ""
    content = re.sub(r"^FAQ:\s*.+?\n", "", content, count=1)
    content = re.sub(r"^Link:\s*.+?\n+", "", content, count=1)
    content = re.sub(r"Zum Hauptinhalt springen.*?Menü schließen", "", content, flags=re.DOTALL)
    content = re.sub(r"\s+", " ", content).strip()
    return content.rstrip()


def _query_terms(message: str | None) -> set[str]:
    text = (message or "").lower()
    terms = {w for w in re.findall(r"[a-zäöüß]{4,}", text)}
    synonyms = {
        "bill": {"rechnung", "invoice", "billing", "zahlung"},
        "invoice": {"rechnung", "invoice", "billing", "zahlung"},
        "activate": {"aktivierung", "aktivieren", "activation", "lizenzschlüssel", "license"},
        "activation": {"aktivierung", "aktivieren", "activation", "lizenzschlüssel", "license"},
        "install": {"installation", "installieren", "herunterladen", "download"},
        "cancel": {"widerruf", "cancellation", "withdrawal", "rückgabe", "digital"},
        "digital": {"digital", "widerruf", "rückgabe", "bereitstellung"},
    }
    for key, values in synonyms.items():
        if key in text:
            terms.update(values)
    return terms


def _relevant_faq_excerpt(match: dict, message: str | None) -> str:
    body = _faq_body(match)
    terms = _query_terms(message)
    if not terms:
        return body[:650].rstrip()
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|(?=\b[A-ZÄÖÜ][A-Za-zÄÖÜäöüß ]{3,70}\?)", body) if p.strip()]
    if not parts:
        return body[:650].rstrip()
    scored = []
    for idx, part in enumerate(parts):
        lowered = part.lower()
        score = sum(1 for term in terms if term in lowered)
        if score:
            scored.append((score, idx))
    if not scored:
        return body[:650].rstrip()
    _score, index = max(scored, key=lambda item: (item[0], -item[1]))
    start = max(0, index - 1)
    excerpt = " ".join(parts[start:index + 4])
    return excerpt[:800].rstrip()


def _faq_summary_for_intent(lang: str, intent: str | None) -> str | None:
    if lang == "en":
        summaries = {
            "key_not_working": (
                "For activation, install the correct product version first, open the license or "
                "activation area, enter the license key exactly as received, confirm activation, "
                "and check that the software shows as activated or licensed. For Windows, use "
                "Settings > Update & Security > Activation > Change product key. Please do not "
                "enter license keys or order data in this chat."
            ),
            "installation": (
                "For installation, download the official installer or ISO for your product, run the "
                "setup, then enter the license key in the activation or license area. If you are stuck, "
                "tell me the product name and the installation step, without personal data or license keys."
            ),
            "invoice": (
                "License data, download information, and the invoice are provided digitally after "
                "successful payment, usually by email. Please also check your spam folder and customer "
                "account. B2B customers receive a proper invoice with VAT shown."
            ),
            "policy": (
                "For digital products, LizenzDeals24 provides the withdrawal and return policy in the "
                "help pages. Consumers generally have a 14-day withdrawal period from contract conclusion; "
                "special rules can apply once digital content has been provided with consent. Please use "
                "the linked policy page for the exact legal wording."
            ),
        }
        return summaries.get(intent)

    summaries = {
        "key_not_working": (
            "Zur Aktivierung installieren Sie zuerst die passende Produktversion, öffnen den Lizenz- "
            "oder Aktivierungsbereich, geben den Lizenzschlüssel exakt wie erhalten ein, bestätigen die "
            "Aktivierung und prüfen anschließend den Status. Bei Windows: Einstellungen > Update & "
            "Sicherheit > Aktivierung > Product Key ändern. Bitte geben Sie hier keine Lizenzschlüssel "
            "oder Bestelldaten ein."
        ),
        "installation": (
            "Für die Installation laden Sie den offiziellen Installer oder die ISO-Datei des Produkts "
            "herunter, führen die Einrichtung aus und geben den Lizenzschlüssel danach im Lizenz- oder "
            "Aktivierungsbereich ein. Wenn Sie an einem Schritt hängen, nennen Sie bitte Produktname "
            "und Installationsschritt, aber keine persönlichen Daten oder Lizenzschlüssel."
        ),
        "invoice": (
            "Lizenzdaten, Download-Informationen und Rechnung werden nach erfolgreichem Zahlungseingang "
            "digital bereitgestellt, in der Regel per E-Mail. Bitte prüfen Sie auch den Spam-Ordner und "
            "Ihr Kundenkonto. Für B2B-Kunden wird eine ordnungsgemäße Rechnung mit ausgewiesener MwSt. "
            "bereitgestellt."
        ),
        "policy": (
            "Für digitale Produkte gelten die Widerrufsbelehrung und Rückgaberegelung von LizenzDeals24. "
            "Verbraucher haben grundsätzlich eine Widerrufsfrist von 14 Tagen ab Vertragsabschluss; bei "
            "digital bereitgestellten Inhalten können besondere Regeln gelten. Die genaue rechtliche "
            "Formulierung finden Sie auf der verlinkten Hilfeseite."
        ),
    }
    return summaries.get(intent)


def faq_fallback_answer(matches: list[dict], lang: str, message: str | None = None) -> str | None:
    faqs = faq_matches(matches)
    if not faqs:
        return None
    first = faqs[0]
    title = _faq_title(first)
    link = _faq_link(first)
    intent = support_intent(message or "", lang)
    body = _faq_summary_for_intent(lang, intent) or _relevant_faq_excerpt(first, message)
    if lang == "en":
        answer = f"I found this in the help pages: {body}"
        if title:
            answer += f"\nSource: {title}"
    else:
        answer = f"Ich habe diese Information in den Hilfeseiten gefunden: {body}"
        if title:
            answer += f"\nQuelle: {title}"
    if link:
        answer += f"\nLink: {link}"
    return answer


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


class ContactRequest(BaseModel):
    kind: Literal["angebot", "reklamation", "kontakt"]
    name: str = Field(..., min_length=2, max_length=120)
    email: str = Field(..., min_length=5, max_length=254)
    message: str = Field(..., min_length=5, max_length=3000)
    productNumber: str | None = Field(default=None, max_length=80)


class ContactResponse(BaseModel):
    status: str
    message: str


# --- Language detection (lightweight heuristic) ------------------------------

_DE_HINTS = {
    "der", "die", "das", "und", "ich", "ist", "nicht", "mit", "für", "ein",
    "eine", "wie", "was", "kann", "gibt", "haben", "kaufen", "kosten", "preis",
    "lizenz", "wie viel", "wieviel", "günstig", "verfügbar", "welche", "wo",
    "hilfe", "rechnung", "beratung", "angebot", "lizenzschlüssel",
    "lizenzschluessel", "funktioniert", "erhalten", "installieren", "zahlung",
}
_EN_HINTS = {
    "the", "and", "is", "are", "do", "does", "how", "what", "can", "i",
    "you", "price", "cost", "buy", "license", "available", "which", "where",
    "help", "invoice", "billing", "consultation", "quote", "received", "work",
    "working", "installation", "install", "key", "cheapest", "cheap", "less",
    "expensive", "president",
}


def detect_lang(text: str) -> str:
    """Return 'de' or 'en'. German is the shop default, so ties go to 'de'."""
    lowered = text.lower()
    if re.search(r"[äöüß]", lowered):
        return "de"
    words = set(re.findall(r"[a-zäöüß]+", lowered))
    de_hits = len(words & _DE_HINTS)
    en_hits = len(words & _EN_HINTS)
    if en_hits > de_hits:
        return "en"
    return "de"


def has_language_signal(text: str, lang: str) -> bool:
    lowered = text.lower()
    if lang == "de" and re.search(r"[äöüß]", lowered):
        return True
    words = set(re.findall(r"[a-zäöüß]+", lowered))
    hints = _DE_HINTS if lang == "de" else _EN_HINTS
    return bool(words & hints)


def resolve_lang(requested: str | None, text: str) -> str:
    """Prefer the user's typed language when it is clear; otherwise use the UI toggle."""
    detected = detect_lang(text)
    if requested in ("de", "en"):
        if detected != requested and has_language_signal(text, detected):
            return detected
        return requested
    return detected


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
            "maxOutputTokens": 900,
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


async def prepare_context(message: str, lang: str, prefer_faq: bool = False) -> tuple[str | None, list[dict], float | None]:
    """Embed and retrieve with the same anti-hallucination gate used by /chat."""
    embedding = await embed_query(message)
    match_count = max(config.TOP_K, 20) if prefer_faq else config.TOP_K
    matches = await search_products(embedding, match_count)
    top_score = matches[0]["similarity"] if matches else None
    good = [m for m in matches if m.get("similarity", 0) >= config.EFFECTIVE_MIN_SIMILARITY]
    if prefer_faq:
        faq_good = [m for m in good if (m.get("metadata") or {}).get("type") == "faq"]
        product_good = [m for m in good if (m.get("metadata") or {}).get("type") != "faq"]
        if faq_good:
            good = (faq_good[:config.TOP_K] + product_good[:2])[: max(config.TOP_K, 7)]
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


def token_chunks(text: str, size: int = 80):
    for i in range(0, len(text), size):
        yield text[i:i + size]


# --- Contact routing (PII stays out of the LLM) ------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_CONTACT_KIND_LABELS = {
    "angebot": "Angebot",
    "reklamation": "Reklamation",
    "kontakt": "Kontakt",
}


def _clean_header(value: str) -> str:
    return re.sub(r"[\r\n]+", " ", value).strip()


async def send_contact_email(req: ContactRequest) -> None:
    api_key = config.require_email_api_key()
    assert _client is not None
    label = _CONTACT_KIND_LABELS[req.kind]
    name = _clean_header(req.name)
    subject = f"[{label}] Anfrage von {name}"
    body_lines = [
        f"Typ: {label}",
        f"Name: {req.name.strip()}",
        f"E-Mail: {req.email.strip()}",
    ]
    if req.productNumber:
        body_lines.append(f"Artikelnummer: {req.productNumber.strip()}")
    body_lines.extend(["", "Nachricht:", req.message.strip()])
    payload = {
        "from": config.EMAIL_FROM,
        "to": [config.SUPPORT_EMAIL],
        "subject": subject,
        "text": "\n".join(body_lines),
    }
    resp = await _client.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=30.0,
    )
    if resp.status_code >= 400:
        raise RuntimeError(_provider_error(resp))


def contact_confirmation(kind: str) -> str:
    label = _CONTACT_KIND_LABELS.get(kind, "Kontakt")
    return f"{label} wurde gesendet. Unser Support meldet sich schnellstmöglich bei Ihnen."


# --- Routes ------------------------------------------------------------------

@app.get("/")
async def root() -> dict:
    return {
        "status": "ok",
        "health": "/health",
        "docs": "/docs",
        "chat": "POST /chat",
        "contact": "POST /contact",
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/contact", response_model=ContactResponse)
async def contact(req: ContactRequest) -> ContactResponse:
    if not _EMAIL_RE.match(req.email.strip()):
        raise HTTPException(status_code=400, detail="Invalid email address.")
    try:
        await send_contact_email(req)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Email service is not configured or unavailable.")
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Email service is unavailable.")
    return ContactResponse(status="ok", message=contact_confirmation(req.kind))


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    message = req.message.strip()
    lang = resolve_lang(req.lang, message)

    if is_greeting(message):
        return ChatResponse(answer=GREETING_REPLY[lang], sources=[])

    intent = support_intent(message, lang)
    if is_contact_intent(message, lang):
        return ChatResponse(answer=contact_reply(lang, intent), sources=[])
    prefer_faq = intent in _FAQ_PREFERRED_INTENTS

    if is_obvious_out_of_scope(message):
        return ChatResponse(answer=NO_CONTEXT[lang], sources=[])

    if is_too_short_for_product_search(message):
        return ChatResponse(answer=NO_CONTEXT[lang], sources=[])

    # 1. Embed + retrieve.
    try:
        context, good, _top_score = await prepare_context(message, lang, prefer_faq=prefer_faq)
    except RuntimeError:
        return ChatResponse(answer=FALLBACK[lang], sources=[])
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 429:
            return ChatResponse(answer=FALLBACK[lang], sources=[])
        raise

    # 2. No confident match -> log the gap and decline (no LLM guess needed).
    if context is None:
        return ChatResponse(answer=NO_CONTEXT[lang], sources=[])

    # 3. FAQ/support questions should not wait on the LLM when the answer is
    # already present in the approved help pages.
    if prefer_faq:
        faq_answer = faq_fallback_answer(good, lang, message)
        if faq_answer:
            return ChatResponse(answer=faq_answer, sources=build_sources(good))

    # 4. Price questions can be answered deterministically from catalog
    # metadata. This is faster and safer than asking the LLM to rephrase.
    if _PRICE_INTENT.search(message) or _INFO_INTENT.search(message):
        direct_answer = catalog_fallback_answer(message, good, lang)
        if direct_answer:
            return ChatResponse(answer=direct_answer, sources=build_sources(good))

    # 5. Build CONTEXT from the good matches and ask the LLM.
    try:
        answer = await generate_answer(message, context, lang)
    except RateLimited:
        faq_answer = faq_fallback_answer(good, lang, message)
        if faq_answer:
            return ChatResponse(answer=faq_answer, sources=build_sources(good))
        fallback_answer = catalog_fallback_answer(message, good, lang)
        if fallback_answer:
            return ChatResponse(answer=fallback_answer, sources=build_sources(good))
        return ChatResponse(answer=FALLBACK[lang], sources=[])
    except RuntimeError:
        faq_answer = faq_fallback_answer(good, lang, message)
        if faq_answer:
            return ChatResponse(answer=faq_answer, sources=build_sources(good))
        fallback_answer = catalog_fallback_answer(message, good, lang)
        if fallback_answer:
            return ChatResponse(answer=fallback_answer, sources=build_sources(good))
        return ChatResponse(answer=FALLBACK[lang], sources=[])
    except httpx.HTTPError:
        faq_answer = faq_fallback_answer(good, lang, message)
        if faq_answer:
            return ChatResponse(answer=faq_answer, sources=build_sources(good))
        fallback_answer = catalog_fallback_answer(message, good, lang)
        if fallback_answer:
            return ChatResponse(answer=fallback_answer, sources=build_sources(good))
        return ChatResponse(answer=FALLBACK[lang], sources=[])

    return ChatResponse(answer=answer, sources=build_sources(good))


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    message = req.message.strip()
    lang = resolve_lang(req.lang, message)

    async def events():
        if is_greeting(message):
            yield sse("answer", {"answer": GREETING_REPLY[lang], "sources": []})
            yield sse("done", {})
            return

        intent = support_intent(message, lang)
        if is_contact_intent(message, lang):
            yield sse("answer", {"answer": contact_reply(lang, intent), "sources": []})
            yield sse("done", {})
            return
        prefer_faq = intent in _FAQ_PREFERRED_INTENTS

        if is_obvious_out_of_scope(message):
            yield sse("answer", {"answer": NO_CONTEXT[lang], "sources": []})
            yield sse("done", {})
            return

        if is_too_short_for_product_search(message):
            yield sse("answer", {"answer": NO_CONTEXT[lang], "sources": []})
            yield sse("done", {})
            return

        try:
            context, good, _top_score = await prepare_context(message, lang, prefer_faq=prefer_faq)
        except (RuntimeError, httpx.HTTPStatusError):
            yield sse("error", {"answer": FALLBACK[lang], "sources": []})
            yield sse("done", {})
            return

        if context is None:
            yield sse("answer", {"answer": NO_CONTEXT[lang], "sources": []})
            yield sse("done", {})
            return

        sources = [s.model_dump() for s in build_sources(good)]

        if prefer_faq:
            faq_answer = faq_fallback_answer(good, lang, message)
            if faq_answer:
                for chunk in token_chunks(faq_answer):
                    yield sse("token", {"text": chunk})
                yield sse("sources", {"sources": sources})
                yield sse("done", {})
                return

        if _PRICE_INTENT.search(message) or _INFO_INTENT.search(message):
            direct_answer = catalog_fallback_answer(message, good, lang)
            if direct_answer:
                for chunk in token_chunks(direct_answer):
                    yield sse("token", {"text": chunk})
                yield sse("sources", {"sources": sources})
                yield sse("done", {})
                return

        api_key = config.require_gemini()
        url = (f"{config.GEMINI_BASE}/models/{config.GEMINI_CHAT_MODEL}"
               f":streamGenerateContent?alt=sse&key={api_key}")
        payload = build_generation_payload(message, context, lang)

        assert _client is not None
        try:
            sent_token = False
            async with _client.stream("POST", url, json=payload, timeout=60.0) as resp:
                if resp.status_code == 429:
                    faq_answer = faq_fallback_answer(good, lang, message)
                    if faq_answer:
                        for chunk in token_chunks(faq_answer):
                            yield sse("token", {"text": chunk})
                        yield sse("sources", {"sources": sources})
                        yield sse("done", {})
                        return
                    fallback_answer = catalog_fallback_answer(message, good, lang)
                    if fallback_answer:
                        for chunk in token_chunks(fallback_answer):
                            yield sse("token", {"text": chunk})
                        yield sse("sources", {"sources": sources})
                    else:
                        yield sse("error", {"answer": FALLBACK[lang], "sources": []})
                    yield sse("done", {})
                    return
                if resp.status_code >= 400:
                    faq_answer = faq_fallback_answer(good, lang, message)
                    if faq_answer:
                        for chunk in token_chunks(faq_answer):
                            yield sse("token", {"text": chunk})
                        yield sse("sources", {"sources": sources})
                        yield sse("done", {})
                        return
                    fallback_answer = catalog_fallback_answer(message, good, lang)
                    if fallback_answer:
                        for chunk in token_chunks(fallback_answer):
                            yield sse("token", {"text": chunk})
                        yield sse("sources", {"sources": sources})
                    else:
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
                faq_answer = faq_fallback_answer(good, lang, message)
                if faq_answer:
                    yield sse("answer", {"answer": faq_answer, "sources": sources})
                    yield sse("done", {})
                    return
                fallback_answer = catalog_fallback_answer(message, good, lang)
                if fallback_answer:
                    yield sse("answer", {"answer": fallback_answer, "sources": sources})
                else:
                    yield sse("answer", {"answer": NO_CONTEXT[lang], "sources": []})
            yield sse("done", {})
        except httpx.HTTPError:
            faq_answer = faq_fallback_answer(good, lang, message)
            if faq_answer:
                yield sse("answer", {"answer": faq_answer, "sources": sources})
                yield sse("done", {})
                return
            fallback_answer = catalog_fallback_answer(message, good, lang)
            if fallback_answer:
                yield sse("answer", {"answer": fallback_answer, "sources": sources})
            else:
                yield sse("error", {"answer": FALLBACK[lang], "sources": []})
            yield sse("done", {})

    return StreamingResponse(events(), media_type="text/event-stream")
