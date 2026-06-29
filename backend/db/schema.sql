-- =============================================================================
-- LZD24 RAG Chatbot — Supabase / Postgres schema
-- Run this ONCE in the Supabase SQL Editor before the first ingestion.
-- Safe to re-run: every statement is idempotent (IF NOT EXISTS / OR REPLACE).
-- =============================================================================

-- 1. Enable pgvector ----------------------------------------------------------
create extension if not exists vector;

-- 2. Products table -----------------------------------------------------------
-- `id` is the Shopware product id (stable) so re-ingestion upserts in place.
-- Gemini embeddings are requested with outputDimensionality=768.
create table if not exists public.products (
    id          text primary key,
    name        text not null,
    content     text not null,
    embedding   vector(768),
    metadata    jsonb not null default '{}'::jsonb,
    updated_at  timestamptz not null default now()
);

-- 3. ANN index for cosine similarity -----------------------------------------
-- ivfflat needs `lists` tuned to row count; ~sqrt(rows). For ~188 products,
-- a small list count is plenty. Build AFTER data exists for best recall, but
-- creating it empty is fine — Postgres will use it once rows are present.
create index if not exists products_embedding_idx
    on public.products
    using ivfflat (embedding vector_cosine_ops)
    with (lists = 16);

-- Helps the upsert path and metadata filtering.
create index if not exists products_metadata_idx
    on public.products using gin (metadata);

-- 4. Unanswered questions log -------------------------------------------------
-- Captures questions where retrieval found no confident match, so the shop
-- owner can spot content gaps. Contains NO personal data by design.
create table if not exists public.unanswered (
    id          bigint generated always as identity primary key,
    question    text not null,
    lang        text,
    top_score   double precision,
    created_at  timestamptz not null default now()
);

-- 5. Vector search RPC --------------------------------------------------------
-- Returns the top `match_count` products ranked by cosine similarity.
-- similarity is in [0,1] where 1 == identical direction.
create or replace function public.match_products (
    query_embedding vector(768),
    match_count     int default 5
)
returns table (
    id         text,
    name       text,
    content    text,
    metadata   jsonb,
    similarity double precision
)
language sql
stable
as $$
    select
        p.id,
        p.name,
        p.content,
        p.metadata,
        1 - (p.embedding <=> query_embedding) as similarity
    from public.products p
    where p.embedding is not null
    order by p.embedding <=> query_embedding
    limit match_count;
$$;

-- =============================================================================
-- OPTIONAL HARDENING (recommended for production)
-- Keep Row Level Security ON and reach the data only via the service_role key
-- from the backend. The service_role key bypasses RLS, so no policies are
-- needed for the backend itself. Do NOT expose the service_role key to the
-- browser/widget — the widget talks to YOUR backend, never to Supabase.
-- =============================================================================
alter table public.products  enable row level security;
alter table public.unanswered enable row level security;
