"""LZD24 ingestion: Shopware products -> embeddings -> Supabase/pgvector.

Run:  python ingest.py
      python ingest.py --dry-run     # fetch + build chunks, no embed/upsert
      python ingest.py --limit 20    # only process first N products (debug)

Idempotent: products are keyed by their Shopware id and UPSERTed, so re-running
updates rows in place instead of creating duplicates.
"""
from __future__ import annotations

import argparse
import sys
import time

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

    content = (
        f"Produkt: {name}\n"
        f"Hersteller: {manufacturer}\n"
        f"Kategorie: {categories}\n"
        f"Eigenschaften:\n{properties}\n"
        f"Beschreibung: {description}\n"
        f"Preis: {price}"
    )

    metadata = {
        "name": name,
        "manufacturer": manufacturer,
        "categories": categories,
        "price": price,
        "product_number": product.get("productNumber"),
    }
    return pid, content, metadata


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
        if resp.status_code == 429:
            wait = delay * (2 ** attempt)
            print(f"    rate limited (429), backing off {wait:.0f}s...")
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

def upsert_products(rows: list[dict]) -> None:
    """Upsert rows into Supabase via PostgREST (on_conflict=id)."""
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
            print(f"  upserted rows {i + 1}-{i + len(chunk)}")


# --- Main -------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest Shopware products into pgvector.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and build chunks but skip embedding/upsert.")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only the first N products (debugging).")
    args = parser.parse_args()

    store_url, store_key = config.require_store()
    print(f"Fetching products from {store_url}/store-api/product ...")
    products = fetch_all_products(store_url, store_key)
    print(f"Total products fetched: {len(products)}")

    if args.limit:
        products = products[: args.limit]
        print(f"(limited to first {len(products)} for this run)")

    # Build chunks first so a dry run shows exactly what would be embedded.
    chunks = [build_chunk(p) for p in products if p.get("id")]
    print(f"Built {len(chunks)} chunks.")

    if args.dry_run:
        print("\n--- DRY RUN: sample chunk ---")
        if chunks:
            print(chunks[0][1])
        print("\nNo embeddings created, nothing written. Done.")
        return 0

    api_key = config.require_gemini()
    rows: list[dict] = []
    with httpx.Client() as gclient:
        for idx, (pid, content, metadata) in enumerate(chunks, 1):
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
            if idx % 10 == 0 or idx == len(chunks):
                print(f"  embedded {idx}/{len(chunks)}")
            # Gentle pacing for the free tier.
            time.sleep(0.3)

    print(f"Upserting {len(rows)} products into Supabase ...")
    upsert_products(rows)
    print("Done. Ingestion complete and idempotent (re-run anytime to refresh).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
