# LZD24 Live Deploy Checklist - Exact Click Guide

This guide has 3 parts:

1. Put the backend online.
2. Add the widget to Shopware.
3. Test on the live storefront.

Do the backend first. The Shopware widget needs a public backend URL, not
`localhost`.

---

## Part 1 - Deploy Backend Online

### Option A - Render Free Web Service

Use this if you have the project in GitHub/GitLab.

1. Open Render:
   - Go to `https://dashboard.render.com`
   - Log in.

2. Create service:
   - Click `+ New` in the top right.
   - Click `Web Service`.
   - Connect/select your GitHub repository.

3. Configure service:
   - `Name`: `lzd24-chat-api`
   - `Language`: `Python`
   - `Branch`: your active branch, usually `main`
   - `Root Directory`: `backend`
   - `Build Command`: `pip install -r requirements.txt`
   - `Start Command`: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - `Instance Type`: Free, if available.

4. Add environment variables:
   - In the Render service setup page, find `Environment Variables`.
   - Add these exact keys:

```text
GEMINI_API_KEY=<from backend/.env>
PYTHON_VERSION=3.12.8
GEMINI_CHAT_MODEL=gemini-2.5-flash-lite
GEMINI_EMBED_MODEL=gemini-embedding-001
GEMINI_EMBED_DIM=768
SUPABASE_URL=<from backend/.env>
SUPABASE_KEY=<from backend/.env>
STORE_API_URL=https://lizenzdeals24.de
STORE_API_KEY=<from backend/.env>
ALLOWED_ORIGINS=https://lizenzdeals24.de,https://www.lizenzdeals24.de,https://lizenzdeals24.com,https://lizenzdeals24.es,https://lizenzdeals24.fr
TOP_K=5
MIN_SIMILARITY=0.64
MIN_EFFECTIVE_SIMILARITY=0.64
SUPPORT_EMAIL=support@lizenzdeals24.de
WHATSAPP_URL=
```

5. Deploy:
   - Click `Create Web Service`.
   - Wait until Render shows `Live` or `Deploy succeeded`.

6. Copy backend URL:
   - Render gives a URL like:

```text
https://lzd24-chat-api.onrender.com
```

7. Test backend:
   - Open this in browser:

```text
https://lzd24-chat-api.onrender.com/health
```

   - Expected result:

```json
{"status":"ok"}
```

8. Test chat endpoint:

```powershell
Invoke-RestMethod -Method Post `
  -Uri https://lzd24-chat-api.onrender.com/chat `
  -ContentType "application/json" `
  -Body '{"message":"Was kostet Windows 11 Pro?","lang":"de"}'
```

Keep this final backend chat URL:

```text
https://lzd24-chat-api.onrender.com/chat
```

You need it in Shopware plugin settings.

---

## Part 2 - Install Widget In Shopware

You have two possible ways:

- Best option: Shopware plugin upload.
- Fallback option: Google Tag Manager Custom HTML.

Use only one option. Do not use both at the same time.

---

## Option A - Shopware Plugin Upload

Use the file:

```text
build/Lzd24Chatbot.zip
```

Current fixed package:

```text
Ginie Chatbot / Lzd24Chatbot version 1.3.0
```

This version contains the professional dark blue chat design, the client avatar,
streaming responses, cache-busted widget asset, trust-badge offset, and stricter
anti-hallucination handling.

### A1 - Upload Extension

1. Open Shopware admin:

```text
https://lizenzdeals24.de/admin
```

2. In the left sidebar, click:

```text
Extensions
```

3. Click:

```text
My extensions
```

4. At the top, stay on tab:

```text
Apps
```

5. Click the blue button:

```text
Upload extension
```

This is visible in your screenshot at the top right of `My extensions`.

6. Select this file from your computer:

```text
D:\fiverr\itsnow24\build\Lzd24Chatbot.zip
```

7. Wait until upload finishes.

### A2 - Install Extension

1. After upload, search in `My extensions` for:

```text
Ginie Chatbot
```

or:

```text
Lzd24Chatbot
```

2. If it shows an `Install` link/button:
   - Click `Install`.
   - Wait until installation finishes.

3. If it shows `Update`:
   - Click `Update`.
   - Wait until update finishes.

4. If it shows a toggle switch:
   - Turn the toggle ON / blue.

5. If you see `...` menu on the right:
   - Click `...`
   - Click `Update`, `Install`, `Activate`, or `Configure`, depending what appears.

### A3 - Configure Extension

1. In `My extensions`, find:

```text
Ginie Chatbot
```

2. Click:

```text
Configure
```

If there is no direct `Configure` link:

1. Click the `...` menu on the right side of the plugin row.
2. Click `Configure`.

3. Fill fields:

```text
Enable chatbot: ON
Backend chat URL: https://lzd24-chat-api.onrender.com/chat
Bot name: Ginie – Ihr Lizenzassistent
Avatar image URL: https://lizenzdeals24.de/media/f8/33/c3/1782816369/Support%20Chatbot%20Icon%20Mensch.png?ts=1782816369
German greeting: Wir sind online für Sie
English greeting: We are online for you.
Support email: support@lizenzdeals24.de
WhatsApp link: leave empty until client gives real wa.me link
Primary color: #1d4ed8
Button accent color: #2563eb
Header dark color: #0f1e3d
Default language: de
Launcher bottom offset: 112
Launcher right offset: 20
```

4. Click:

```text
Save
```

### A4 - Clear Cache

1. In Shopware left sidebar, click:

```text
Settings
```

2. In the `System` column, click:

```text
Caches & indexes
```

This is visible in your Settings screenshot under `System`.

3. Click:

```text
Clear caches
```

4. If available, also click:

```text
Clear and warm up caches
```

### A4.1 - Confirm New Widget Asset Is Live

After cache clear, open this URL in a browser:

```text
https://lizenzdeals24.de/bundles/lzd24chatbot/widget/widget.js?v=1.3.0
```

Search on the page with `Ctrl + F`:

```text
Unsere Experten sind online!
```

If you find this text, the new professional widget is live.

If you still see the old simple widget code with only `Wir sind online für Sie.`
and no `Unsere Experten sind online!`, Shopware is still serving old plugin
assets. Upload/update the `build/Lzd24Chatbot.zip` again, confirm version
`1.3.0`, then clear cache again.

### A5 - Check Live Storefront

1. Open a private/incognito browser window.
2. Go to:

```text
https://lizenzdeals24.de
```

3. Wait 5-10 seconds.
4. Check bottom right corner.
5. You should see the Ginie chat bubble.

If it does not show:

1. Hard refresh:
   - Windows: `Ctrl + F5`
2. Check plugin is active.
3. Check backend URL is correct.
4. Check Shopware cache was cleared.
5. Check browser console for errors.

---

## Option B - Google Tag Manager

Use this if plugin upload fails or if the agency prefers GTM.

Important: your screenshots show this installed extension:

```text
GA4 & Google Ads with Google Tag Manager
```

That means GTM may already be connected, but you still need GTM container access.

### B1 - Open Google Tag Manager

1. Go to:

```text
https://tagmanager.google.com
```

2. Log in with the account that manages Lizenzdeals24 GTM.

3. Open the container for:

```text
lizenzdeals24.de
```

### B2 - Create Custom HTML Tag

1. In GTM left sidebar, click:

```text
Tags
```

2. Click:

```text
New
```

3. Click:

```text
Tag Configuration
```

4. Choose:

```text
Custom HTML
```

5. Open this file in your project:

```text
deploy/gtm-custom-html.html
```

6. Paste all HTML into the Custom HTML box.

7. Replace:

```text
https://YOUR-PUBLIC-BACKEND/chat
```

with your real backend URL:

```text
https://lzd24-chat-api.onrender.com/chat
```

8. Replace:

```text
https://YOUR-PUBLIC-WIDGET-HOST/widget.js
```

with a real public widget JS URL.

Examples:

```text
https://your-domain.com/widget.js
```

or a static host/CDN URL.

### B3 - Add Trigger

1. Click:

```text
Triggering
```

2. Select:

```text
All Pages
```

3. Name the tag:

```text
LZD24 Ginie Chatbot
```

4. Click:

```text
Save
```

### B4 - Preview Test

1. Click:

```text
Preview
```

2. Enter:

```text
https://lizenzdeals24.de
```

3. Connect Tag Assistant.
4. Confirm tag `LZD24 Ginie Chatbot` fires on the page.

### B5 - Publish

1. Click:

```text
Submit
```

2. Add version name:

```text
LZD24 Ginie Chatbot
```

3. Click:

```text
Publish
```

---

## Part 3 - Where To Get Avatar URL In Shopware

From your screenshot, the avatar file exists in Sales Channel custom fields:

```text
Kundensupport Icon LZD24.png
```

Better way to get direct URL:

1. In Shopware left sidebar, click:

```text
Content
```

2. Click:

```text
Media
```

3. Search:

```text
Kundensupport Icon LZD24
```

4. Open the image.
5. Copy the public media URL if Shopware shows it.
6. Paste that URL into plugin config:

```text
Avatar image URL
```

If Shopware does not show direct URL:

1. Open the image in storefront/media preview.
2. Right click image.
3. Click `Copy image address`.

---

## Part 4 - Final Live Acceptance Checks

Open:

```text
https://lizenzdeals24.de
```

Ask:

```text
Was kostet Windows 11 Pro?
```

Expected:

```text
Mentions Microsoft Windows 11 Pro and price from catalog.
```

Ask:

```text
How much does Windows 11 Pro cost?
```

Expected:

```text
English answer with Windows 11 Pro price.
```

Ask:

```text
Wie ist das Wetter morgen?
```

Expected:

```text
Bot refuses / says no information, does not invent.
```

Ask:

```text
Ich möchte ein Angebot anfragen
```

Expected:

```text
Bot routes to support@lizenzdeals24.de and asks not to enter personal data.
```

---

## Important Notes

- `localhost` and `127.0.0.1` are only for your computer. Never use them on the
  live shop.
- Live Shopware needs `https://...` backend URL.
- Do not expose `GEMINI_API_KEY` or `SUPABASE_KEY` in browser, GTM, or plugin
  JavaScript. They belong only in Render environment variables.
- If the widget appears but replies `Connection failed`, the backend URL or CORS
  is wrong.
- If the widget does not appear at all, the plugin/GTM script is not loaded or
  cache is not cleared.
