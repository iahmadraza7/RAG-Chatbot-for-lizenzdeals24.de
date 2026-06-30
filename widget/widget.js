/* =============================================================================
 * LZD24 / Ginie — embeddable chat widget
 * Single-file, dependency-free. Load with ONE tag (e.g. via Google Tag Manager):
 *
 *   <script src="https://your-cdn/widget.js" defer></script>
 *
 * Everything tweakable lives in CONFIG below. Override before this script loads:
 *   window.LZD24_CONFIG = { backendUrl: "...", avatarUrl: "..." };
 * ===========================================================================*/
(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // CONFIG — edit/override these, not the logic below.
  // ---------------------------------------------------------------------------
  var CONFIG = Object.assign(
    {
      backendUrl: "http://localhost:8000/chat",
      botName: "Ginie – Ihr Lizenzassistent",
      avatarUrl: "https://api.dicebear.com/9.x/bottts/svg?seed=LZD24",
      agentAvatarUrl: "",
      useAgentAvatar: false,
      primaryColor: "#1d4ed8",
      primaryColorDark: "#0f1e3d",
      defaultLang: "de",
      greetingDE: "Wir sind online für Sie",
      greetingEN: "We are online for you",
      quickRepliesDE: [
        { icon: "🔑", text: "Lizenzschlüssel nicht erhalten" },
        { icon: "⚠", text: "Lizenzschlüssel funktioniert nicht" },
        { icon: "💻", text: "Hilfe bei Installation" },
        { icon: "🧾", text: "Hilfe mit Rechnung" },
        { icon: "💬", text: "Beratung" },
      ],
      quickRepliesEN: [
        { icon: "🔑", text: "License key not received" },
        { icon: "⚠", text: "License key does not work" },
        { icon: "💻", text: "Help with installation" },
        { icon: "🧾", text: "Help with invoice" },
        { icon: "💬", text: "Consultation" },
      ],
      offsetBottom: 96,
      offsetRight: 20,
      supportEmail: "support@lizenzdeals24.de",
      contactUrl: "/kontakt",
      telUrl: "tel:+4921732643330",
      whatsappUrl: "",
      disclaimerDE: "Bitte keine persönlichen Daten eingeben.",
      disclaimerEN: "Please do not enter any personal data.",
      showGreetingPopup: true,
      greetingDelayMs: 900,
      showSources: true,
      maxSourceNames: 2,
      stream: true,
      streamUrl: "",
    },
    window.LZD24_CONFIG || {}
  );

  var avatar = CONFIG.useAgentAvatar && CONFIG.agentAvatarUrl ? CONFIG.agentAvatarUrl : CONFIG.avatarUrl;
  var lang = CONFIG.defaultLang === "en" ? "en" : "de";
  var greetedOnce = false;
  var activeController = null;

  var I18N = {
    de: {
      popupTitle: "Willkommen bei LizenzDeals24",
      popupText: CONFIG.greetingDE,
      startChat: "Jetzt chatten",
      contact: "Kontakt aufnehmen",
      decline: "Danke – gerade nicht.",
      online: "Online",
      menu: "Menü",
      close: "Schließen",
      welcomeTitle: "Hallo! Wie können wir Ihnen helfen?",
      welcomeText: "Wählen Sie ein Thema oder schreiben Sie uns Ihre Frage.",
      placeholder: "Schreibe eine Nachricht…",
      send: "Senden",
      error: "Verbindung fehlgeschlagen. Bitte später erneut versuchen.",
      sources: "Quellen: ",
      disclaimer: CONFIG.disclaimerDE,
      open: "Chat öffnen",
    },
    en: {
      popupTitle: "Welcome to LizenzDeals24",
      popupText: CONFIG.greetingEN,
      startChat: "Start chat",
      contact: "Contact us",
      decline: "Thanks – not now.",
      online: "Online",
      menu: "Menu",
      close: "Close",
      welcomeTitle: "Hello! How can we help you?",
      welcomeText: "Choose a topic or type your question.",
      placeholder: "Write a message…",
      send: "Send",
      error: "Connection failed. Please try again later.",
      sources: "Sources: ",
      disclaimer: CONFIG.disclaimerEN,
      open: "Open chat",
    },
  };

  function streamEndpoint() {
    if (CONFIG.streamUrl) return CONFIG.streamUrl;
    if (/\/chat\/?$/.test(CONFIG.backendUrl)) {
      return CONFIG.backendUrl.replace(/\/chat\/?$/, "/chat/stream");
    }
    return CONFIG.backendUrl.replace(/\/$/, "") + "/chat/stream";
  }

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function normalizeReply(reply) {
    if (typeof reply === "string") return { icon: "", text: reply };
    return { icon: reply.icon || "", text: reply.text || "" };
  }

  function quickReplies() {
    return (lang === "en" ? CONFIG.quickRepliesEN : CONFIG.quickRepliesDE).map(normalizeReply);
  }

  // ---------------------------------------------------------------------------
  // Styles
  // ---------------------------------------------------------------------------
  function injectStyles() {
    if (document.getElementById("lzd24-styles")) return;
    var css = `
    #lzd24-root, #lzd24-root * { box-sizing: border-box; }
    #lzd24-root {
      --lzd-primary: ${CONFIG.primaryColor};
      --lzd-navy: ${CONFIG.primaryColorDark || "#0f1e3d"};
      --lzd-panel: #0f1e3d;
      --lzd-border: rgba(148, 163, 184, .22);
      position: fixed;
      bottom: ${Number(CONFIG.offsetBottom) || 96}px;
      right: ${Number(CONFIG.offsetRight) || 20}px;
      z-index: 2147483000;
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: #0f172a;
    }
    #lzd24-root button, #lzd24-root textarea, #lzd24-root a { font-family: inherit; }
    #lzd24-launcher-wrap { position: relative; display: flex; flex-direction: column; align-items: flex-end; gap: 12px; }
    #lzd24-bubble {
      width: 66px; height: 66px; border-radius: 50%; cursor: pointer; border: 1px solid rgba(255,255,255,.38);
      background: radial-gradient(circle at 30% 22%, #60a5fa, var(--lzd-primary) 46%, #0f1e3d 100%);
      display: flex; align-items: center; justify-content: center; box-shadow: 0 18px 42px rgba(15,30,61,.34);
      transition: transform .18s ease, box-shadow .18s ease;
    }
    #lzd24-bubble:hover { transform: translateY(-2px) scale(1.03); box-shadow: 0 22px 50px rgba(15,30,61,.42); }
    #lzd24-bubble img { width: 42px; height: 42px; border-radius: 50%; background:#fff; object-fit: cover; border: 2px solid rgba(255,255,255,.82); }
    #lzd24-greet {
      width: 330px; max-width: calc(100vw - 28px); background: #fff; border-radius: 16px; overflow: hidden;
      box-shadow: 0 18px 55px rgba(15,23,42,.22); border: 1px solid rgba(15,30,61,.08); animation: lzd-pop .22s ease;
    }
    #lzd24-greet-head { background: linear-gradient(135deg, var(--lzd-navy), #1d4ed8); color: #fff; padding: 14px 16px; display:flex; gap:10px; align-items:center; }
    #lzd24-greet-head img { width: 38px; height: 38px; border-radius: 50%; background:#fff; object-fit:cover; }
    #lzd24-greet-title { font-weight: 800; font-size: 15px; line-height:1.2; }
    #lzd24-greet-sub { color: #dbeafe; font-size: 12px; margin-top:2px; }
    #lzd24-greet-body { padding: 14px 16px 16px; }
    #lzd24-greet-body p { margin:0 0 12px; color:#334155; font-size: 14px; line-height:1.42; }
    .lzd-greet-actions { display:flex; flex-direction: column; gap: 8px; }
    .lzd-greet-actions button, .lzd-greet-actions a {
      border: 0; border-radius: 10px; padding: 10px 12px; font-weight: 800; cursor:pointer; text-align:center; text-decoration:none; font-size:13px;
    }
    #lzd24-start { background: var(--lzd-primary); color:#fff; }
    #lzd24-contact { background:#eef4ff; color:#1d4ed8; border:1px solid #bfdbfe; }
    #lzd24-decline { background: transparent; color:#64748b; }
    @keyframes lzd-pop { from { opacity:0; transform: translateY(10px) scale(.98);} to {opacity:1; transform:none;} }

    #lzd24-panel {
      position: absolute; bottom: 0; right: 0; width: 390px; max-width: calc(100vw - 28px); height: 630px; max-height: calc(100vh - 34px);
      background:#fff; border-radius: 20px; overflow:hidden; display:none; flex-direction:column;
      box-shadow:0 24px 70px rgba(2,6,23,.38); border: 1px solid rgba(148,163,184,.28);
    }
    #lzd24-panel.lzd-open { display:flex; animation:lzd-pop .18s ease; }
    #lzd24-header {
      background: linear-gradient(135deg, var(--lzd-navy), #172554 56%, var(--lzd-primary));
      color:#fff; padding: 14px 14px; display:flex; align-items:center; gap: 10px; min-height: 76px;
    }
    #lzd24-menu, #lzd24-close { width: 32px; height: 32px; display:grid; place-items:center; background:rgba(255,255,255,.1); color:#fff; border:1px solid rgba(255,255,255,.14); border-radius:10px; cursor:pointer; }
    #lzd24-header-main { flex:1; min-width:0; }
    #lzd24-title { font-size: 15px; line-height: 1.2; font-weight: 850; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    #lzd24-status { font-size: 12px; color:#bfdbfe; margin-top:4px; display:flex; align-items:center; gap:6px; }
    #lzd24-status-dot { width:7px; height:7px; border-radius:50%; background:#22c55e; box-shadow:0 0 0 4px rgba(34,197,94,.15); }
    #lzd24-head-avatar { width: 48px; height:48px; border-radius:50%; object-fit:cover; background:#fff; border:2px solid rgba(255,255,255,.8); }
    .lzd-lang { display:flex; gap:4px; }
    .lzd-lang button { background: rgba(255,255,255,.13); color:#dbeafe; border:1px solid rgba(255,255,255,.14); border-radius:8px; padding:4px 7px; font-size:11px; cursor:pointer; font-weight:800; }
    .lzd-lang button.lzd-active { background:#fff; color:var(--lzd-primary); }

    #lzd24-msgs { flex:1; overflow-y:auto; padding: 16px 14px; background: linear-gradient(180deg, #f8fbff 0%, #eef4ff 100%); }
    #lzd24-welcome { background:#fff; border:1px solid #dbeafe; border-radius:16px; padding:14px; margin-bottom:12px; display:flex; gap:12px; box-shadow:0 8px 24px rgba(15,23,42,.06); }
    #lzd24-welcome img { width:44px; height:44px; border-radius:50%; background:#eff6ff; object-fit:cover; flex:0 0 auto; }
    #lzd24-welcome strong { display:block; color:#0f1e3d; font-size:15px; margin-bottom:4px; }
    #lzd24-welcome span { display:block; color:#475569; font-size:13px; line-height:1.35; }
    #lzd24-quick { display:flex; gap:8px; flex-wrap:wrap; margin: 0 0 14px; }
    .lzd-chip { background:#fff; color:#1e293b; border:1px solid #bfdbfe; border-radius:999px; padding:8px 10px; font-size:12px; cursor:pointer; display:inline-flex; gap:6px; align-items:center; box-shadow:0 4px 12px rgba(15,23,42,.05); }
    .lzd-chip:hover { border-color: var(--lzd-primary); color: var(--lzd-primary); }
    .lzd-msg { margin-bottom:11px; display:flex; }
    .lzd-msg.lzd-bot { justify-content:flex-start; }
    .lzd-msg.lzd-user { justify-content:flex-end; }
    .lzd-bubble-msg { max-width:82%; padding:10px 12px; border-radius:15px; font-size:14px; line-height:1.44; white-space:pre-wrap; word-wrap:break-word; }
    .lzd-bot .lzd-bubble-msg { background:#fff; color:#1e293b; border:1px solid #dbeafe; border-bottom-left-radius:5px; box-shadow:0 4px 14px rgba(15,23,42,.05); }
    .lzd-user .lzd-bubble-msg { background: var(--lzd-primary); color:#fff; border-bottom-right-radius:5px; box-shadow:0 7px 18px rgba(29,78,216,.22); }
    .lzd-sources { font-size:11px; color:#64748b; margin-top:7px; padding-top:7px; border-top:1px solid #e2e8f0; }
    .lzd-typing { display:inline-flex; gap:4px; align-items:center; padding:3px 0; }
    .lzd-typing span { width:7px; height:7px; background:#94a3b8; border-radius:50%; animation:lzd-blink 1.2s infinite; }
    .lzd-typing span:nth-child(2){ animation-delay:.2s; } .lzd-typing span:nth-child(3){ animation-delay:.4s; }
    @keyframes lzd-blink { 0%,80%,100%{opacity:.35;} 40%{opacity:1;} }

    #lzd24-foot { background:#fff; border-top:1px solid #dbeafe; padding: 10px; }
    #lzd24-actions { display:flex; gap:8px; margin-bottom:8px; }
    #lzd24-actions a { flex:1; text-align:center; text-decoration:none; border-radius:10px; padding:8px; font-size:12px; font-weight:800; border:1px solid #bfdbfe; color:#1d4ed8; background:#eff6ff; }
    #lzd24-whatsapp { color:#047857 !important; background:#ecfdf5 !important; border-color:#a7f3d0 !important; }
    #lzd24-disclaimer { font-size:11px; color:#94a3b8; text-align:center; padding:0 0 8px; }
    #lzd24-inputrow { display:flex; gap:8px; align-items:flex-end; }
    #lzd24-input { flex:1; resize:none; border:1px solid #cbd5e1; border-radius:13px; padding:11px 12px; font-size:14px; line-height:1.35; max-height:96px; outline:none; background:#fff; color:#0f172a; }
    #lzd24-input:focus { border-color: var(--lzd-primary); box-shadow:0 0 0 3px rgba(29,78,216,.12); }
    #lzd24-sendbtn { width:46px; height:44px; flex:0 0 auto; border:0; border-radius:13px; background:var(--lzd-primary); color:#fff; cursor:pointer; font-size:18px; display:grid; place-items:center; box-shadow:0 8px 18px rgba(29,78,216,.25); }
    #lzd24-sendbtn:disabled { opacity:.55; cursor:default; box-shadow:none; }

    @media (max-width: 480px) {
      #lzd24-panel { position: fixed; inset: 10px; width:auto; height:auto; max-width:none; max-height:none; border-radius:18px; }
      #lzd24-greet { width: calc(100vw - 20px); }
      #lzd24-bubble { width:62px; height:62px; }
    }
    `;
    var style = document.createElement("style");
    style.id = "lzd24-styles";
    style.textContent = css;
    document.head.appendChild(style);
  }

  // ---------------------------------------------------------------------------
  // DOM
  // ---------------------------------------------------------------------------
  var els = {};

  function buildQuickReplies() {
    return quickReplies().map(function (reply) {
      return '<button class="lzd-chip" type="button" data-text="' + esc(reply.text) + '"><span>' + esc(reply.icon) + '</span>' + esc(reply.text) + '</button>';
    }).join("");
  }

  function build() {
    var root = document.createElement("div");
    root.id = "lzd24-root";
    root.innerHTML = `
      <div id="lzd24-panel" role="dialog" aria-label="${esc(CONFIG.botName)}">
        <div id="lzd24-header">
          <button id="lzd24-menu" type="button" aria-label="${I18N[lang].menu}">☰</button>
          <div id="lzd24-header-main">
            <div id="lzd24-title">${esc(CONFIG.botName)}</div>
            <div id="lzd24-status"><span id="lzd24-status-dot"></span><span>${I18N[lang].online}</span></div>
          </div>
          <div class="lzd-lang"><button type="button" data-lang="de">DE</button><button type="button" data-lang="en">EN</button></div>
          <img id="lzd24-head-avatar" src="${esc(avatar)}" alt="" />
          <button id="lzd24-close" type="button" aria-label="${I18N[lang].close}">×</button>
        </div>
        <div id="lzd24-msgs"></div>
        <div id="lzd24-foot">
          <div id="lzd24-actions">
            <a id="lzd24-email" href="mailto:${esc(CONFIG.supportEmail)}" target="_blank" rel="noopener">E-Mail</a>
            <a id="lzd24-whatsapp" href="${esc(CONFIG.whatsappUrl)}" target="_blank" rel="noopener">WhatsApp</a>
          </div>
          <div id="lzd24-disclaimer"></div>
          <div id="lzd24-inputrow">
            <textarea id="lzd24-input" rows="1"></textarea>
            <button id="lzd24-sendbtn" type="button" aria-label="${I18N[lang].send}">➤</button>
          </div>
        </div>
      </div>
      <div id="lzd24-launcher-wrap">
        <div id="lzd24-greet" style="display:none">
          <div id="lzd24-greet-head">
            <img src="${esc(avatar)}" alt="" />
            <div><div id="lzd24-greet-title"></div><div id="lzd24-greet-sub">${esc(CONFIG.botName)}</div></div>
          </div>
          <div id="lzd24-greet-body">
            <p id="lzd24-greet-text"></p>
            <div class="lzd-greet-actions">
              <button id="lzd24-start" type="button"></button>
              <a id="lzd24-contact" href="${esc(CONFIG.telUrl || CONFIG.contactUrl || '#')}" target="_blank" rel="noopener"></a>
              <button id="lzd24-decline" type="button"></button>
            </div>
          </div>
        </div>
        <button id="lzd24-bubble" type="button" aria-label="${I18N[lang].open}"><img src="${esc(avatar)}" alt="" /></button>
      </div>
    `;
    document.body.appendChild(root);

    els.root = root;
    els.panel = root.querySelector("#lzd24-panel");
    els.bubble = root.querySelector("#lzd24-bubble");
    els.close = root.querySelector("#lzd24-close");
    els.menu = root.querySelector("#lzd24-menu");
    els.msgs = root.querySelector("#lzd24-msgs");
    els.input = root.querySelector("#lzd24-input");
    els.send = root.querySelector("#lzd24-sendbtn");
    els.email = root.querySelector("#lzd24-email");
    els.whatsapp = root.querySelector("#lzd24-whatsapp");
    els.greet = root.querySelector("#lzd24-greet");
    els.greetTitle = root.querySelector("#lzd24-greet-title");
    els.greetText = root.querySelector("#lzd24-greet-text");
    els.start = root.querySelector("#lzd24-start");
    els.contact = root.querySelector("#lzd24-contact");
    els.decline = root.querySelector("#lzd24-decline");
    els.disclaimer = root.querySelector("#lzd24-disclaimer");
    els.langBtns = root.querySelectorAll(".lzd-lang button");

    wireEvents();
    applyLang();
  }

  function renderWelcome() {
    els.msgs.innerHTML = `
      <div id="lzd24-welcome">
        <img src="${esc(avatar)}" alt="" />
        <div><strong>${esc(I18N[lang].welcomeTitle)}</strong><span>${esc(I18N[lang].welcomeText)}</span></div>
      </div>
      <div id="lzd24-quick">${buildQuickReplies()}</div>
    `;
    els.msgs.querySelectorAll(".lzd-chip").forEach(function (button) {
      button.addEventListener("click", function () {
        sendUserText(button.getAttribute("data-text") || "");
      });
    });
  }

  function wireEvents() {
    els.bubble.addEventListener("click", openPanel);
    els.start.addEventListener("click", openPanel);
    els.close.addEventListener("click", closePanel);
    els.decline.addEventListener("click", function () { els.greet.style.display = "none"; });
    els.send.addEventListener("click", onSend);
    els.input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); }
    });
    els.input.addEventListener("input", function () {
      els.input.style.height = "auto";
      els.input.style.height = Math.min(els.input.scrollHeight, 96) + "px";
    });
    els.langBtns.forEach(function (b) {
      b.addEventListener("click", function () {
        lang = b.getAttribute("data-lang") === "en" ? "en" : "de";
        greetedOnce = false;
        applyLang();
        renderWelcome();
      });
    });
  }

  function applyLang() {
    var t = I18N[lang];
    els.input.placeholder = t.placeholder;
    els.disclaimer.textContent = t.disclaimer;
    els.greetTitle.textContent = t.popupTitle;
    els.greetText.textContent = t.popupText;
    els.start.textContent = t.startChat;
    els.contact.textContent = t.contact;
    els.decline.textContent = t.decline;
    els.email.textContent = "E-Mail";
    els.email.href = "mailto:" + CONFIG.supportEmail;
    els.whatsapp.textContent = "WhatsApp";
    els.whatsapp.style.display = CONFIG.whatsappUrl ? "block" : "none";
    els.langBtns.forEach(function (b) { b.classList.toggle("lzd-active", b.getAttribute("data-lang") === lang); });
  }

  function openPanel() {
    els.greet.style.display = "none";
    els.panel.classList.add("lzd-open");
    els.bubble.style.display = "none";
    if (!greetedOnce) {
      renderWelcome();
      greetedOnce = true;
    }
    setTimeout(function () { els.input.focus(); }, 60);
  }

  function closePanel() {
    if (activeController) activeController.abort();
    activeController = null;
    els.panel.classList.remove("lzd-open");
    els.bubble.style.display = "flex";
  }

  // ---------------------------------------------------------------------------
  // Messaging
  // ---------------------------------------------------------------------------
  function addMessage(who, text, sources) {
    var wrap = document.createElement("div");
    wrap.className = "lzd-msg lzd-" + who;
    var bubble = document.createElement("div");
    bubble.className = "lzd-bubble-msg";
    bubble.textContent = text || "";
    wrap.appendChild(bubble);
    if (CONFIG.showSources && sources && sources.length) addSources(bubble, sources);
    els.msgs.appendChild(wrap);
    scrollBottom();
    return bubble;
  }

  function addSources(bubble, sources) {
    var names = sources.map(function (x) { return x.name; }).filter(Boolean);
    if (!names.length) return;
    var visible = names.slice(0, CONFIG.maxSourceNames || 2);
    var more = names.length > visible.length ? " +" + (names.length - visible.length) : "";
    var s = document.createElement("div");
    s.className = "lzd-sources";
    s.textContent = I18N[lang].sources + visible.join(" · ") + more;
    bubble.appendChild(s);
  }

  function showTyping() {
    var wrap = document.createElement("div");
    wrap.className = "lzd-msg lzd-bot";
    wrap.id = "lzd24-typing";
    wrap.innerHTML = '<div class="lzd-bubble-msg"><div class="lzd-typing"><span></span><span></span><span></span></div></div>';
    els.msgs.appendChild(wrap);
    scrollBottom();
  }
  function hideTyping() { var t = document.getElementById("lzd24-typing"); if (t) t.remove(); }
  function scrollBottom() { els.msgs.scrollTop = els.msgs.scrollHeight; }

  function onSend() {
    var text = els.input.value.trim();
    if (!text) return;
    els.input.value = "";
    els.input.style.height = "auto";
    sendUserText(text);
  }

  function sendUserText(text) {
    if (!text) return;
    addMessage("user", text);
    sendToBackend(text);
  }

  function setBusy(isBusy) {
    els.send.disabled = isBusy;
    els.input.disabled = isBusy;
  }

  function appendToken(bubble, token) {
    bubble.textContent += token;
    scrollBottom();
  }

  function sendToBackend(text) {
    setBusy(true);
    if (CONFIG.stream && window.ReadableStream) {
      streamFromBackend(text).catch(function (err) {
        if (err && err.name === "AbortError") {
          hideTyping();
          setBusy(false);
          return;
        }
        return sendFallback(text);
      });
    } else {
      sendFallback(text);
    }
  }

  async function streamFromBackend(text) {
    if (activeController) activeController.abort();
    activeController = new AbortController();
    showTyping();
    var resp = await fetch(streamEndpoint(), {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify({ message: text, lang: lang }),
      signal: activeController.signal,
    });
    if (!resp.ok || !resp.body) throw new Error("stream unavailable");

    var reader = resp.body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";
    var botBubble = null;
    var sources = [];

    function handleEvent(eventName, dataText) {
      if (!dataText) return;
      var data;
      try { data = JSON.parse(dataText); } catch (_) { return; }
      if (eventName === "token") {
        if (!botBubble) { hideTyping(); botBubble = addMessage("bot", ""); }
        appendToken(botBubble, data.text || "");
      } else if (eventName === "answer") {
        hideTyping();
        botBubble = addMessage("bot", data.answer || I18N[lang].error, data.sources || []);
      } else if (eventName === "sources") {
        sources = data.sources || [];
      } else if (eventName === "error") {
        hideTyping();
        botBubble = addMessage("bot", data.answer || I18N[lang].error);
      }
    }

    function drain() {
      var idx;
      while ((idx = buffer.indexOf("\n\n")) >= 0) {
        var raw = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        var eventName = "message";
        var dataLines = [];
        raw.split(/\r?\n/).forEach(function (line) {
          if (line.indexOf("event:") === 0) eventName = line.slice(6).trim();
          if (line.indexOf("data:") === 0) dataLines.push(line.slice(5).trim());
        });
        handleEvent(eventName, dataLines.join("\n"));
      }
    }

    while (true) {
      var result = await reader.read();
      if (result.done) break;
      buffer += decoder.decode(result.value, { stream: true });
      drain();
    }
    buffer += decoder.decode();
    drain();

    hideTyping();
    if (botBubble && sources.length && CONFIG.showSources) addSources(botBubble, sources);
    setBusy(false);
    activeController = null;
    els.input.focus();
  }

  function sendFallback(text) {
    hideTyping();
    showTyping();
    fetch(CONFIG.backendUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, lang: lang }),
    })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (data) { hideTyping(); addMessage("bot", data.answer || I18N[lang].error, data.sources); })
      .catch(function () { hideTyping(); addMessage("bot", I18N[lang].error); })
      .finally(function () { setBusy(false); els.input.focus(); });
  }

  // ---------------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------------
  function init() {
    injectStyles();
    build();
    if (CONFIG.showGreetingPopup) {
      setTimeout(function () {
        if (!els.panel.classList.contains("lzd-open")) els.greet.style.display = "block";
      }, CONFIG.greetingDelayMs);
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
