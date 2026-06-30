# Milestone 1 - Setup & Core Bot

Completed:

- Core FastAPI chatbot backend.
- Shopware Store API product ingestion.
- 250 products embedded into Supabase.
- German and English product Q&A.
- Strict retrieved-context answering.
- Out-of-scope rejection to reduce hallucinations.
- Ginie widget UI with greeting popup.
- Editable configuration for bot name, greeting, avatar URL, colors, support email, WhatsApp URL, language, and backend URL.
- Shopware plugin scaffold with admin configuration fields.
- GTM Custom HTML fallback snippet.
- Public Render backend live at `https://lzd24-chat-api.onrender.com`.
- Updated professional widget package `build/Lzd24Chatbot.zip` version `1.3.0`.
- Streaming chat endpoint `/chat/stream` for faster visible responses, with `/chat` fallback.
- Client avatar image configured from Shopware media URL.
- Bottom offset configured so the widget does not cover the Trustsiegel.
- Blue LizenzDeals24 theme applied instead of competitor-style green buttons.
- Anti-hallucination gate hardened so low-confidence questions do not return random products.

Not part of Milestone 1 / requires next access:

- Outlook form/email automation and WhatsApp button final URL, handled in Milestone 2.
