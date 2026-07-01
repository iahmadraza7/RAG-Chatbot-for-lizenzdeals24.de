"""LZD24 ingestion: Shopware products -> embeddings -> Supabase/pgvector.

Run:  python ingest.py
      python ingest.py --dry-run     # fetch + build chunks, no embed/upsert
      python ingest.py --limit 20    # only process first N products (debug)

Idempotent: products are keyed by their Shopware id and UPSERTed, so re-running
updates rows in place instead of creating duplicates.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

import config

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- Shopware fetching ------------------------------------------------------

PAGE_SIZE = 100
# Pull the associations we need to build a rich, accurate text chunk.
ASSOCIATIONS = {
    "manufacturer": {},
    "properties": {"associations": {"group": {}}},
    "categories": {},
    "seoUrls": {},
}


def fetch_all_products(store_url: str, store_key: str) -> list[dict]:
    """Page through POST /store-api/product until every product is fetched."""
    url = f"{store_url}/store-api/product"
    headers = {"sw-access-key": store_key, "Content-Type": "application/json"}
    products: list[dict] = []
    page = 1

    with httpx.Client(timeout=60.0) as client:
        while True:
            body = {"limit": PAGE_SIZE, "page": page, "associations": ASSOCIATIONS}
            resp = client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("elements", []) or []
            if not batch:
                break
            products.extend(batch)
            total = data.get("total")
            print(f"  fetched page {page}: {len(batch)} products "
                  f"(running total {len(products)}"
                  f"{f' / {total}' if total else ''})")
            # Stop when the API reports we've reached the end.
            if len(batch) < PAGE_SIZE:
                break
            page += 1

    return products


# --- Chunk building ---------------------------------------------------------

def _price(product: dict) -> str:
    """Best-effort gross price extraction across Shopware payload shapes."""
    calc = product.get("calculatedPrice") or {}
    if isinstance(calc, dict) and calc.get("totalPrice") is not None:
        return f"{calc['totalPrice']:.2f} EUR"
    prices = product.get("price")
    if isinstance(prices, list) and prices:
        gross = prices[0].get("gross")
        if gross is not None:
            return f"{gross:.2f} EUR"
    return "Preis auf Anfrage"


def _absolute_url(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return value
    return f"{config.STORE_API_URL.rstrip('/')}/{value.lstrip('/')}"


def _product_url(product: dict) -> str:
    """Best-effort canonical storefront URL from Shopware seoUrls association."""
    seo_urls = product.get("seoUrls") or product.get("seoUrl") or []
    if isinstance(seo_urls, dict):
        seo_urls = [seo_urls]
    if not isinstance(seo_urls, list):
        return ""

    def score(item: dict) -> int:
        return int(bool(item.get("isCanonical"))) * 2 - int(bool(item.get("isDeleted")))

    candidates = [item for item in seo_urls if isinstance(item, dict)]
    candidates.sort(key=score, reverse=True)
    for item in candidates:
        for key in ("url", "seoPathInfo", "pathInfo"):
            url = _absolute_url(item.get(key))
            if url:
                return url
    return ""


def _categories(product: dict) -> str:
    cats = product.get("categories") or []
    names = [c.get("name") for c in cats if isinstance(c, dict) and c.get("name")]
    return ", ".join(dict.fromkeys(names)) or "—"


def _properties(product: dict) -> str:
    """Group properties as `Group: value1, value2` lines."""
    props = product.get("properties") or []
    grouped: dict[str, list[str]] = {}
    for p in props:
        if not isinstance(p, dict):
            continue
        group = (p.get("group") or {}).get("name") or "Eigenschaft"
        value = p.get("name")
        if value:
            grouped.setdefault(group, []).append(value)
    if not grouped:
        return "—"
    return "\n".join(f"  - {g}: {', '.join(vals)}" for g, vals in grouped.items())


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    import html
    import re
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def build_chunk(product: dict) -> tuple[str, str, dict]:
    """Return (id, content_text, metadata) for one product."""
    pid = product.get("id")
    name = product.get("translated", {}).get("name") or product.get("name") or "Unbenannt"
    manufacturer = (product.get("manufacturer") or {}).get("name") or "—"
    categories = _categories(product)
    properties = _properties(product)
    description = _strip_html(
        product.get("translated", {}).get("description")
        or product.get("description")
    ) or "—"
    price = _price(product)
    product_number = product.get("productNumber") or "—"
    product_url = _product_url(product)

    content = (
        f"Produkt: {name}\n"
        f"Artikelnummer: {product_number}\n"
        f"Hersteller: {manufacturer}\n"
        f"Kategorie: {categories}\n"
        f"Eigenschaften:\n{properties}\n"
        f"Beschreibung: {description}\n"
        f"Preis: {price}"
    )
    if product_url:
        content += f"\nLink: {product_url}"

    metadata = {
        "type": "product",
        "name": name,
        "manufacturer": manufacturer,
        "categories": categories,
        "price": price,
        "product_number": product_number if product_number != "—" else None,
        "product_url": product_url or None,
    }
    return pid, content, metadata


# --- FAQ / help page ingestion ----------------------------------------------

class VisibleTextParser(HTMLParser):
    """Small visible-text extractor without adding a new dependency."""

    SKIP_TAGS = {
        "script", "style", "noscript", "svg", "canvas", "template",
        "header", "nav", "footer", "form",
    }
    BLOCK_TAGS = {
        "address", "article", "aside", "blockquote", "br", "div", "footer",
        "h1", "h2", "h3", "h4", "h5", "h6", "header", "li", "main", "nav",
        "ol", "p", "section", "table", "td", "th", "tr", "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if self._skip_depth == 0 and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if self._skip_depth == 0 and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        if self._skip_depth == 0:
            self.parts.append(text)

    @property
    def title(self) -> str:
        return normalize_text(" ".join(self.title_parts))[:160]

    @property
    def text(self) -> str:
        return normalize_text(" ".join(self.parts))


def normalize_text(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_faq_urls(urls: list[str], url_file: str | None) -> list[str]:
    collected = [url.strip() for url in urls if url.strip()]
    if url_file:
        with open(url_file, "r", encoding="utf-8") as handle:
            collected.extend(line.strip() for line in handle if line.strip() and not line.startswith("#"))

    deduped: list[str] = []
    seen: set[str] = set()
    for url in collected:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def fetch_faq_page(client: httpx.Client, url: str) -> tuple[str, str, str]:
    resp = client.get(url, follow_redirects=True, timeout=60.0)
    resp.raise_for_status()
    parser = VisibleTextParser()
    parser.feed(resp.text)
    parser.close()
    final_url = str(resp.url)
    title = parser.title or final_url
    text = parser.text
    if not text:
        raise RuntimeError(f"No visible text extracted from {final_url}")
    return final_url, title, text


def chunk_text(text: str, max_chars: int = 2200, overlap: int = 220) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            for start in range(0, len(paragraph), max_chars - overlap):
                part = paragraph[start:start + max_chars].strip()
                if part:
                    chunks.append(part)
            continue
        if current and len(current) + len(paragraph) + 2 > max_chars:
            chunks.append(current.strip())
            current = current[-overlap:].strip() if overlap and len(current) > overlap else ""
        current = f"{current}\n\n{paragraph}".strip() if current else paragraph
    if current:
        chunks.append(current.strip())
    return chunks


def faq_id(url: str, index: int) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:24]
    return f"faq:{digest}:{index:03d}"


def build_faq_chunks(urls: list[str]) -> list[tuple[str, str, dict]]:
    chunks: list[tuple[str, str, dict]] = []
    with httpx.Client(headers={"User-Agent": "LZD24Chatbot/1.0"}) as client:
        for url in urls:
            final_url, title, text = fetch_faq_page(client, url)
            page_chunks = chunk_text(text)
            print(f"  fetched FAQ: {final_url} ({len(page_chunks)} chunks)")
            for idx, body in enumerate(page_chunks, 1):
                content = f"FAQ: {title}\nLink: {final_url}\n\n{body}"
                metadata = {
                    "type": "faq",
                    "name": title,
                    "url": final_url,
                    "title": title,
                    "chunk": idx,
                    "chunks": len(page_chunks),
                }
                chunks.append((faq_id(final_url, idx), content, metadata))
    return chunks


# --- Embedding (Gemini embeddings) ------------------------------------------

def embed_text(client: httpx.Client, api_key: str, text: str,
               retries: int = 5) -> list[float]:
    """Embed a single document chunk with RETRIEVAL_DOCUMENT task type.

    Retries on 429 (free-tier rate limit) with exponential backoff.
    """
    url = (f"{config.GEMINI_BASE}/models/{config.GEMINI_EMBED_MODEL}"
           f":embedContent?key={api_key}")
    # Gemini embeddings have token and byte payload limits.
    # Truncate the embedding INPUT only (byte-safe for umlauts) so long German
    # product descriptions don't cause a 400. Full content is still stored in
    # Supabase and passed to the LLM as context, so answer quality is unaffected.
    MAX_EMBED_BYTES = 6000
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_EMBED_BYTES:
        text = encoded[:MAX_EMBED_BYTES].decode("utf-8", errors="ignore")
    payload = {
        "model": f"models/{config.GEMINI_EMBED_MODEL}",
        "content": {"parts": [{"text": text}]},
        "taskType": "RETRIEVAL_DOCUMENT",
        "outputDimensionality": config.EMBED_DIM,
    }
    delay = 2.0
    for attempt in range(retries):
        resp = client.post(url, json=payload, timeout=60.0)
        if resp.status_code in (429, 500, 502, 503, 504):
            wait = delay * (2 ** attempt)
            reason = "rate limited" if resp.status_code == 429 else "provider unavailable"
            print(f"    {reason} ({resp.status_code}), backing off {wait:.0f}s...")
            time.sleep(wait)
            continue
        if resp.status_code >= 400:
            try:
                message = resp.json().get("error", {}).get("message") or resp.text
            except ValueError:
                message = resp.text
            raise RuntimeError(
                f"Gemini embedding failed ({resp.status_code}): {message}"
            )
        resp.raise_for_status()
        values = resp.json()["embedding"]["values"]
        if len(values) != config.EMBED_DIM:
            raise RuntimeError(
                f"Unexpected embedding dim {len(values)} (expected {config.EMBED_DIM})"
            )
        return values
    raise RuntimeError("Embedding failed after repeated rate limits (429).")


# --- Supabase upsert --------------------------------------------------------

def upsert_rows(rows: list[dict], label: str = "rows") -> None:
    """Upsert rows into Supabase via PostgREST (on_conflict=id)."""
    if not rows:
        return
    sb_url, sb_key = config.require_supabase()
    url = f"{sb_url}/rest/v1/products?on_conflict=id"
    headers = config.supabase_headers(sb_key)
    # merge-duplicates => UPSERT; return=minimal keeps the response light.
    headers["Prefer"] = "resolution=merge-duplicates,return=minimal"

    with httpx.Client(timeout=60.0) as client:
        # Send in modest batches to stay well under payload limits.
        BATCH = 50
        for i in range(0, len(rows), BATCH):
            chunk = rows[i:i + BATCH]
            resp = client.post(url, headers=headers, json=chunk)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Supabase upsert failed ({resp.status_code}): {resp.text}"
                )
            print(f"  upserted {label} {i + 1}-{i + len(chunk)}")


def delete_faq_urls(urls: list[str]) -> None:
    """Delete existing FAQ chunks for these canonical URLs before re-upsert."""
    if not urls:
        return
    sb_url, sb_key = config.require_supabase()
    endpoint = f"{sb_url}/rest/v1/products"
    headers = config.supabase_headers(sb_key)
    headers["Prefer"] = "return=minimal"

    with httpx.Client(timeout=60.0) as client:
        for url in urls:
            resp = client.delete(endpoint, headers=headers, params={
                "metadata->>type": "eq.faq",
                "metadata->>url": f"eq.{url}",
            })
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Supabase FAQ delete failed ({resp.status_code}): {resp.text}"
                )
            print(f"  refreshed FAQ URL: {url}")


# --- Main -------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest Shopware products and FAQ pages into pgvector.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and build chunks but skip embedding/upsert.")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only the first N products (debugging).")
    parser.add_argument("--faq-url", action="append", default=[],
                        help="Public FAQ/help/policy page URL to ingest. Can be repeated.")
    parser.add_argument("--faq-url-file",
                        help="Text file with one public FAQ/help/policy URL per line.")
    parser.add_argument("--only-faq", action="store_true",
                        help="Skip product ingestion and ingest only FAQ URLs.")
    args = parser.parse_args()

    product_chunks: list[tuple[str, str, dict]] = []
    faq_chunks: list[tuple[str, str, dict]] = []
    faq_urls = load_faq_urls(args.faq_url, args.faq_url_file)

    if not args.only_faq:
        store_url, store_key = config.require_store()
        print(f"Fetching products from {store_url}/store-api/product ...")
        products = fetch_all_products(store_url, store_key)
        print(f"Total products fetched: {len(products)}")

        if args.limit:
            products = products[: args.limit]
            print(f"(limited to first {len(products)} for this run)")

        product_chunks = [build_chunk(p) for p in products if p.get("id")]
        print(f"Built {len(product_chunks)} product chunks.")

    if faq_urls:
        print(f"Fetching {len(faq_urls)} FAQ/help pages ...")
        faq_chunks = build_faq_chunks(faq_urls)
        print(f"Built {len(faq_chunks)} FAQ chunks.")

    if args.dry_run:
        print("\n--- DRY RUN: sample product chunk ---")
        if product_chunks:
            print(product_chunks[0][1])
        else:
            print("(no product chunks)")
        print("\n--- DRY RUN: sample FAQ chunk ---")
        if faq_chunks:
            print(faq_chunks[0][1][:1600])
        else:
            print("(no FAQ chunks)")
        print("\nNo embeddings created, nothing written. Done.")
        return 0

    all_chunks = product_chunks + faq_chunks
    if not all_chunks:
        print("Nothing to ingest. Provide products and/or --faq-url values.")
        return 0

    api_key = config.require_gemini()
    rows: list[dict] = []
    with httpx.Client() as gclient:
        for idx, (pid, content, metadata) in enumerate(all_chunks, 1):
            try:
                embedding = embed_text(gclient, api_key, content)
            except RuntimeError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 1
            rows.append({
                "id": pid,
                "name": metadata["name"],
                "content": content,
                "embedding": config.vector_literal(embedding),
                "metadata": metadata,
            })
            if idx % 10 == 0 or idx == len(all_chunks):
                print(f"  embedded {idx}/{len(all_chunks)}")
            # Gentle pacing for the free tier.
            time.sleep(0.3)

    product_rows = [row for row in rows if row["metadata"].get("type") == "product"]
    faq_rows = [row for row in rows if row["metadata"].get("type") == "faq"]
    if product_rows:
        print(f"Upserting {len(product_rows)} products into Supabase ...")
        upsert_rows(product_rows, "product rows")
    if faq_rows:
        canonical_urls = []
        seen_urls: set[str] = set()
        for row in faq_rows:
            url = row["metadata"].get("url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                canonical_urls.append(url)
        print(f"Refreshing and upserting {len(faq_rows)} FAQ chunks into Supabase ...")
        delete_faq_urls(canonical_urls)
        upsert_rows(faq_rows, "FAQ rows")
    print("Done. Ingestion complete and idempotent (re-run anytime to refresh).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
