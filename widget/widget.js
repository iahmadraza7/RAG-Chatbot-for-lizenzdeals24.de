/* =============================================================================
 * LZD24 / Ginie - embeddable chat widget
 * Single-file, dependency-free. Override settings before loading this script:
 *   window.LZD24_CONFIG = { backendUrl: "...", avatarUrl: "..." };
 * ===========================================================================*/
(function () {
  "use strict";

  var CONFIG = Object.assign(
    {
      backendUrl: "http://localhost:8000/chat",
      botName: "Ginie – Ihr Lizenzassistent",
      avatarUrl: "https://lizenzdeals24.de/media/f8/33/c3/1782816369/Support%20Chatbot%20Icon%20Mensch.png?ts=1782816369",
      agentAvatarUrl: "",
      useAgentAvatar: false,
      primaryColor: "#1d4ed8",
      primaryColorDark: "#0f1e3d",
      accentColor: "#2563eb",
      defaultLang: "de",
      greetingDE: "Wir sind online für Sie",
      greetingEN: "We are online for you",
      quickRepliesDE: [
        { icon: "key", text: "Lizenzschlüssel nicht erhalten" },
        { icon: "zap", text: "Lizenzschlüssel funktioniert nicht" },
        { icon: "monitor", text: "Hilfe bei Installation" },
        { icon: "receipt", text: "Hilfe mit Rechnung" },
        { icon: "chat", text: "Beratung" },
      ],
      quickRepliesEN: [
        { icon: "key", text: "License key not received" },
        { icon: "zap", text: "License key does not work" },
        { icon: "monitor", text: "Help with installation" },
        { icon: "receipt", text: "Help with invoice" },
        { icon: "chat", text: "Consultation" },
      ],
      offsetBottom: 45,
      offsetRight: 24,
      supportEmail: "support@lizenzdeals24.de",
      contactUrl: "/kontakt",
      telUrl: "tel:+4921732643330",
      whatsappUrl: "",
      disclaimerDE: "Bitte keine persönlichen Daten eingeben.",
      disclaimerEN: "Please do not enter personal data.",
      showGreetingPopup: true,
      greetingDelayMs: 650,
      showSources: false,
      maxSourceNames: 2,
      stream: true,
      streamUrl: "",
      historyStorageKey: "lzd24-chat-history-v1",
    },
    window.LZD24_CONFIG || {}
  );

  if (/^#?(9ad72d|a8e61d|84cc16|22c55e)$/i.test(String(CONFIG.accentColor || ""))) {
    CONFIG.accentColor = CONFIG.primaryColor || "#2563eb";
  }

  var avatar = CONFIG.useAgentAvatar && CONFIG.agentAvatarUrl ? CONFIG.agentAvatarUrl : CONFIG.avatarUrl;
  var lang = CONFIG.defaultLang === "en" ? "en" : "de";
  var greetedOnce = false;
  var activeController = null;
  var conversation = loadConversation();
  var configuredBottom = Number(CONFIG.offsetBottom);
  var desktopBottom = Number.isFinite(configuredBottom) && configuredBottom > 0 ? configuredBottom : 45;
  var configuredRight = Number(CONFIG.offsetRight);
  var desktopRight = Number.isFinite(configuredRight) && configuredRight > 0 ? configuredRight : 24;
  var mobileBottom = desktopBottom;

  var I18N = {
    de: {
      popupTitle: "Unsere Experten sind online!",
      popupText: "Hast du Fragen rund um deine Lizenz? Ich helfe dir gerne weiter.",
      startChat: "Jetzt chatten",
      callNow: "Jetzt telefonieren",
      decline: "Danke – gerade nicht.",
      online: "Online",
      menu: "Menü",
      close: "Schließen",
      history: "Chatverlauf",
      noHistory: "Du hast keine frueheren Chats.",
      back: "Zurück",
      introKicker: "LizenzDeals24",
      introTitle: "Hi, ich bin Ginie.",
      introText: "Sag mir einfach, wie ich dir helfen kann!",
      welcomeTitle: "Hallo! Wie können wir Ihnen helfen?",
      placeholder: "Schreibe eine Nachricht...",
      send: "Senden",
      error: "Verbindung fehlgeschlagen. Bitte später erneut versuchen.",
      sources: "Quellen: ",
      disclaimer: CONFIG.disclaimerDE,
      open: "Chat öffnen",
      callTitle: "Wir sind online",
      callText: "Durch einen Anruf wird eine Konversation mit dem nächsten verfügbaren Agenten eingeleitet.",
      callButton: "Jetzt anrufen",
      cancel: "Abbrechen",
    },
    en: {
      popupTitle: "Our experts are online!",
      popupText: "Questions about your license? I am happy to help.",
      startChat: "Start chat",
      callNow: "Call now",
      decline: "Thanks - not now.",
      online: "Online",
      menu: "Menu",
      close: "Close",
      history: "Chat history",
      noHistory: "You have no previous chats.",
      back: "Back",
      introKicker: "LizenzDeals24",
      introTitle: "Hi, I am Ginie.",
      introText: "Tell me how I can help you.",
      welcomeTitle: "Hello! How can we help you?",
      placeholder: "Write a message...",
      send: "Send",
      error: "Connection failed. Please try again later.",
      sources: "Sources: ",
      disclaimer: CONFIG.disclaimerEN,
      open: "Open chat",
      callTitle: "We are online",
      callText: "A call starts a conversation with the next available support agent.",
      callButton: "Call now",
      cancel: "Cancel",
    },
  };

  var ICONS = {
    menu: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h12M4 12h16M4 17h10"/></svg>',
    close: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    history: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7M3 4v6h6M12 7v5l3 2"/></svg>',
    phone: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 2 .7 2.9a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.2-1.2a2 2 0 0 1 2.1-.5c.9.3 1.9.6 2.9.7A2 2 0 0 1 22 16.9z"/></svg>',
    back: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>',
    key: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 7a4 4 0 1 0 2.8 6.8L21 17v3h-3v-2h-2v-2h-2l-1.2-1.2A4 4 0 0 0 15 7zM7 10h.01"/></svg>',
    zap: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13 2L3 14h8l-1 8 11-14h-8l1-6z"/></svg>',
    monitor: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v11H4zM8 21h8M12 16v5"/></svg>',
    receipt: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h12v18l-2-1-2 1-2-1-2 1-2-1-2 1zM9 7h6M9 11h6M9 15h4"/></svg>',
    chat: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/></svg>',
    plus: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
    send: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
    headset: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 13a8 8 0 0 1 16 0M4 13v4a2 2 0 0 0 2 2h1v-8H6a2 2 0 0 0-2 2zM20 13v4a2 2 0 0 1-2 2h-1v-8h1a2 2 0 0 1 2 2zM12 21h3"/></svg>',
  };

  function icon(name) {
    return ICONS[name] || ICONS.chat;
  }

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
    if (typeof reply === "string") return { icon: "chat", text: reply };
    return { icon: reply.icon || "chat", text: reply.text || "" };
  }

  function quickReplies() {
    return (lang === "en" ? CONFIG.quickRepliesEN : CONFIG.quickRepliesDE).map(normalizeReply);
  }

  function loadConversation() {
    try {
      if (!window.localStorage) return [];
      var raw = window.localStorage.getItem(CONFIG.historyStorageKey);
      if (!raw) return [];
      var items = JSON.parse(raw);
      if (!Array.isArray(items)) return [];
      return items
        .filter(function (item) {
          return item && (item.who === "user" || item.who === "bot") && typeof item.text === "string";
        })
        .slice(-80);
    } catch (_) {
      return [];
    }
  }

  function saveConversation() {
    try {
      if (!window.localStorage) return;
      window.localStorage.setItem(CONFIG.historyStorageKey, JSON.stringify(conversation.slice(-80)));
    } catch (_) {
      // Browser storage can be disabled; the chat must still work normally.
    }
  }

  function persistMessage(who, text, bubble) {
    if (who !== "user" && who !== "bot") return;
    conversation.push({ who: who, text: text || "", ts: Date.now() });
    conversation = conversation.slice(-80);
    if (bubble) bubble.setAttribute("data-lzd-history-index", String(conversation.length - 1));
    saveConversation();
  }

  function updateStoredMessage(bubble) {
    var rawIndex = bubble && bubble.getAttribute("data-lzd-history-index");
    var index = rawIndex == null ? -1 : Number(rawIndex);
    if (index < 0 || !conversation[index]) return;
    conversation[index].text = bubble.textContent || "";
    saveConversation();
  }

  function injectStyles() {
    if (document.getElementById("lzd24-styles")) return;
    var css = `
    #lzd24-root, #lzd24-root * { box-sizing: border-box; }
    #lzd24-root {
      --lzd-blue: ${CONFIG.primaryColor || "#1d4ed8"};
      --lzd-dark: ${CONFIG.primaryColorDark || "#0f1e3d"};
      --lzd-dark-2: #0b1830;
      --lzd-accent: ${CONFIG.accentColor || "#2563eb"};
      --lzd-muted: rgba(226, 232, 240, .72);
      position: fixed;
      bottom: ${desktopBottom}px;
      right: ${desktopRight}px;
      z-index: 2147483000;
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: #f8fafc;
    }
    #lzd24-root svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
    #lzd24-root button, #lzd24-root textarea, #lzd24-root a { font-family: inherit; }
    #lzd24-launcher-wrap { position: relative; display: flex; flex-direction: column; align-items: flex-end; gap: 12px; }
    #lzd24-bubble {
      width: 58px; height: 58px; border-radius: 50%; cursor: pointer; border: 3px solid #fff;
      background: var(--lzd-dark); display: flex; align-items: center; justify-content: center;
      box-shadow: 0 18px 46px rgba(8, 25, 31, .38); transition: transform .18s ease, box-shadow .18s ease;
    }
    #lzd24-bubble:hover { transform: translateY(-2px) scale(1.03); box-shadow: 0 22px 56px rgba(8, 25, 31, .48); }
    #lzd24-bubble img { width: 50px; height: 50px; border-radius: 50%; background: #fff; object-fit: cover; object-position: center; }

    #lzd24-greet {
      width: 305px; max-width: calc(100vw - 24px); background: var(--lzd-dark); color: #fff;
      border-radius: 16px; padding: 13px; overflow: hidden; position: relative;
      box-shadow: 0 22px 58px rgba(8,25,31,.38); border: 1px solid rgba(255,255,255,.08); animation: lzd-pop .2s ease;
    }
    #lzd24-greet-badge { position:absolute; top:15px; right:15px; width:50px; height:50px; border-radius:50%; background:#fff; padding:3px; }
    #lzd24-greet-badge img { width:100%; height:100%; object-fit:cover; border-radius:50%; display:block; }
    #lzd24-greet-badge::after { content:""; position:absolute; top:0; right:2px; width:13px; height:13px; border-radius:50%; background:#60a5fa; border:2px solid var(--lzd-dark); }
    #lzd24-greet-headline { display:inline-block; max-width: 178px; background:#fff; color:#0f172a; border-radius:11px; padding:8px 11px; font-size:13px; line-height:1.22; font-weight:850; margin-bottom:11px; position:relative; }
    #lzd24-greet-headline::after { content:""; position:absolute; left:18px; bottom:-7px; border-width:8px 8px 0 0; border-style:solid; border-color:#fff transparent transparent transparent; }
    #lzd24-greet-body p { margin: 0 62px 12px 0; color:#edf6f7; font-size:13px; line-height:1.34; font-weight:700; }
    .lzd-greet-actions { display:flex; flex-direction:column; gap:8px; margin-top:3px; }
    .lzd-greet-actions button, .lzd-greet-actions a {
      width:100%; border:0; border-radius:999px; padding:10px 13px; font-weight:900; cursor:pointer; text-align:center; text-decoration:none; font-size:13px;
    }
    #lzd24-start { background:var(--lzd-accent); color:#fff; box-shadow: 0 10px 22px rgba(37,99,235,.24); }
    #lzd24-contact { background:#fff; color:var(--lzd-dark); }
    #lzd24-decline { background:transparent; color:#e5e7eb; padding:5px 8px; text-decoration:underline; font-size:12px; box-shadow:none; }
    @keyframes lzd-pop { from { opacity:0; transform:translateY(12px) scale(.98);} to { opacity:1; transform:none; } }

    #lzd24-panel {
      position:absolute; bottom:0; right:0; width:390px; max-width:calc(100vw - 24px); height:620px; max-height:calc(100vh - ${desktopBottom + 20}px);
      display:none; flex-direction:column; overflow:hidden; background:var(--lzd-dark); color:#fff;
      border-radius:18px; box-shadow:0 24px 70px rgba(2,6,23,.38); border:1px solid rgba(255,255,255,.1);
    }
    #lzd24-panel.lzd-open { display:flex; animation:lzd-pop .18s ease; }
    #lzd24-header { flex:0 0 auto; min-height:58px; padding:12px 14px 8px; display:flex; align-items:center; gap:10px; background:var(--lzd-dark); color:#d8e4e7; }
    .lzd-icon-btn { width:34px; height:34px; display:grid; place-items:center; background:transparent; border:0; color:#d8e4e7; border-radius:8px; cursor:pointer; padding:0; }
    .lzd-icon-btn:hover { background:rgba(255,255,255,.08); color:#fff; }
    #lzd24-header-title { flex:1; min-width:0; font-size:16px; font-weight:800; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; color:#dbe7ea; }
    .lzd-lang { display:flex; gap:4px; margin-right:2px; }
    .lzd-lang button { border:1px solid rgba(255,255,255,.12); background:rgba(255,255,255,.07); color:#cbd5e1; border-radius:8px; padding:4px 7px; font-size:11px; font-weight:900; cursor:pointer; }
    .lzd-lang button.lzd-active { background:#fff; color:var(--lzd-dark); }

    .lzd-view { display:none; flex:1 1 auto; min-height:0; overflow:hidden; }
    #lzd24-panel[data-view="chat"] #lzd24-chat-view,
    #lzd24-panel[data-view="call"] #lzd24-call-view,
    #lzd24-panel[data-view="history"] #lzd24-history-view { display:flex; }
    #lzd24-panel[data-view="call"] #lzd24-foot,
    #lzd24-panel[data-view="history"] #lzd24-foot { display:none; }
    #lzd24-chat-view { flex-direction:column; }
    #lzd24-hero { flex:0 0 auto; position:relative; padding: 6px 22px 14px; min-height:166px; }
    #lzd24-brand { font-size:26px; line-height:1; font-weight:950; letter-spacing:.2px; color:#fff; margin:10px 0 8px; }
    #lzd24-brand span { color:var(--lzd-accent); }
    #lzd24-hero h2 { margin:0; max-width:245px; font-size:25px; line-height:1.12; color:#fff; font-weight:900; }
    #lzd24-hero h2 span { color:var(--lzd-accent); display:block; }
    #lzd24-hero p { max-width:250px; margin:10px 0 0; color:#f1f5f9; font-size:15px; line-height:1.32; font-weight:650; }
    #lzd24-hero-avatar { position:absolute; right:18px; top:40px; width:104px; height:104px; border-radius:50%; background:#fff; object-fit:cover; object-position:center; box-shadow:0 18px 34px rgba(0,0,0,.18); }
    #lzd24-hero-status { position:absolute; right:24px; top:43px; width:14px; height:14px; border-radius:50%; background:#60a5fa; border:2px solid var(--lzd-dark); }
    #lzd24-msgs { flex:1 1 auto; overflow-y:auto; padding: 0 22px 14px; scrollbar-color: rgba(255,255,255,.45) transparent; }
    #lzd24-welcome-title { margin: 12px 0 14px; font-size:20px; line-height:1.25; font-weight:900; color:#fff; }
    #lzd24-quick { display:flex; flex-direction:column; gap:2px; margin-bottom:16px; }
    .lzd-chip { border:0; background:transparent; color:rgba(226,232,240,.72); min-height:45px; text-align:left; padding:8px 0; display:flex; align-items:center; gap:13px; cursor:pointer; font-size:15px; font-weight:700; }
    .lzd-chip svg { width:19px; height:19px; flex:0 0 auto; color:rgba(226,232,240,.66); }
    .lzd-chip:hover { color:#fff; }
    .lzd-chip:hover svg { color:var(--lzd-accent); }
    .lzd-msg { margin-bottom:13px; display:flex; }
    .lzd-msg.lzd-bot { justify-content:flex-start; }
    .lzd-msg.lzd-user { justify-content:flex-end; }
    .lzd-bubble-msg { max-width:84%; padding:10px 13px; border-radius:14px; font-size:15px; line-height:1.42; white-space:pre-wrap; overflow-wrap:anywhere; }
    .lzd-bot .lzd-bubble-msg { background:rgba(255,255,255,.08); color:#f8fafc; border:1px solid rgba(255,255,255,.08); border-bottom-left-radius:5px; }
    .lzd-user .lzd-bubble-msg { background:var(--lzd-accent); color:#fff; border-bottom-right-radius:5px; font-weight:750; }
    .lzd-sources { font-size:11px; color:rgba(226,232,240,.62); margin-top:7px; padding-top:7px; border-top:1px solid rgba(255,255,255,.12); }
    .lzd-typing { display:inline-flex; gap:4px; align-items:center; padding:3px 0; }
    .lzd-typing span { width:7px; height:7px; background:#cbd5e1; border-radius:50%; animation:lzd-blink 1.2s infinite; }
    .lzd-typing span:nth-child(2){ animation-delay:.2s; } .lzd-typing span:nth-child(3){ animation-delay:.4s; }
    @keyframes lzd-blink { 0%,80%,100%{opacity:.35;} 40%{opacity:1;} }

    .lzd-secondary-view { flex-direction:column; background:#fff; color:#0f172a; padding:22px; }
    .lzd-back { display:inline-flex; align-items:center; gap:10px; background:transparent; border:0; color:#0f172a; font-size:18px; font-weight:800; padding:0; cursor:pointer; width:max-content; }
    .lzd-back svg { width:24px; height:24px; }
    #lzd24-call-center { flex:1; display:flex; flex-direction:column; align-items:center; justify-content:flex-start; padding-top:30px; text-align:center; }
    #lzd24-call-icon { width:76px; height:76px; border-radius:50%; background:var(--lzd-dark); color:#fff; display:grid; place-items:center; position:relative; margin-bottom:34px; }
    #lzd24-call-icon::after { content:""; position:absolute; top:2px; right:4px; width:15px; height:15px; border-radius:50%; background:#16a34a; border:3px solid #fff; }
    #lzd24-call-center h3 { margin:0 0 24px; font-size:31px; line-height:1.15; font-weight:500; color:#111827; }
    #lzd24-call-center p { margin:0 0 42px; background:#f1f5f9; border-radius:12px; padding:20px 22px; color:#1f2937; font-size:18px; line-height:1.45; }
    #lzd24-call-action, #lzd24-call-cancel { width:100%; max-width:290px; border-radius:999px; padding:15px 18px; text-align:center; font-size:17px; font-weight:850; text-decoration:none; }
    #lzd24-call-action { background:var(--lzd-accent); color:#fff; margin-bottom:16px; }
    #lzd24-call-cancel { background:#fff; color:var(--lzd-accent); border:1px solid var(--lzd-accent); }
    #lzd24-history-view { flex-direction:column; padding:22px; background:var(--lzd-dark); color:#fff; }
    #lzd24-history-view p { margin:34px 0 0; color:rgba(226,232,240,.68); font-size:18px; font-weight:650; }
    #lzd24-history-list { margin-top:22px; display:flex; flex-direction:column; gap:10px; overflow-y:auto; padding-right:4px; }
    .lzd-history-item { border:1px solid rgba(255,255,255,.08); border-radius:12px; padding:10px 12px; background:rgba(255,255,255,.06); color:#f8fafc; }
    .lzd-history-item strong { display:block; margin-bottom:5px; color:#bfdbfe; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
    .lzd-history-item span { display:block; color:#e5eef6; font-size:14px; line-height:1.4; white-space:pre-wrap; overflow-wrap:anywhere; }
    .lzd-history-item.lzd-user { margin-left:34px; background:rgba(37,99,235,.28); }
    .lzd-history-item.lzd-bot { margin-right:34px; }

    #lzd24-foot { flex:0 0 auto; background:var(--lzd-dark); padding: 10px 14px 14px; }
    #lzd24-disclaimer { font-size:10.5px; color:rgba(226,232,240,.48); text-align:center; padding:0 0 7px; }
    #lzd24-inputrow { display:flex; gap:8px; align-items:flex-end; background:#0d2c33; border:1px solid rgba(255,255,255,.08); border-radius:8px; padding:8px; }
    #lzd24-plus { width:32px; height:34px; flex:0 0 auto; border:0; background:transparent; color:#fff; display:grid; place-items:center; cursor:pointer; padding:0; }
    #lzd24-input { flex:1; resize:none; border:0; padding:6px 2px; font-size:16px; line-height:1.35; max-height:96px; outline:none; background:transparent; color:#fff; min-width:0; }
    #lzd24-input::placeholder { color:rgba(226,232,240,.58); }
    #lzd24-sendbtn { width:42px; height:42px; flex:0 0 auto; border:0; border-radius:7px; background:var(--lzd-accent); color:#fff; cursor:pointer; display:grid; place-items:center; }
    #lzd24-sendbtn:disabled { opacity:.6; cursor:default; }

    @media (max-width: 480px) {
      #lzd24-root { right: 12px; bottom: max(${mobileBottom}px, calc(env(safe-area-inset-bottom) + ${mobileBottom}px)); }
      #lzd24-panel {
        position:fixed; left:8px; right:8px; top:max(8px, env(safe-area-inset-top)); bottom:max(8px, env(safe-area-inset-bottom));
        width:auto; height:auto; max-width:none; max-height:none; border-radius:16px;
      }
      @supports (height: 100dvh) {
        #lzd24-panel { height: calc(100dvh - 16px); bottom:auto; }
      }
      #lzd24-header { min-height:52px; padding:9px 10px 6px; gap:6px; }
      #lzd24-header-title { font-size:14px; }
      .lzd-icon-btn { width:30px; height:30px; }
      .lzd-lang button { padding:4px 6px; font-size:10px; }
      #lzd24-hero { min-height:138px; padding:4px 16px 10px; }
      #lzd24-brand { font-size:22px; margin:8px 0 7px; }
      #lzd24-hero h2 { max-width:190px; font-size:22px; }
      #lzd24-hero p { max-width:205px; margin-top:8px; font-size:14px; }
      #lzd24-hero-avatar { right:16px; top:38px; width:78px; height:78px; }
      #lzd24-hero-status { right:20px; top:39px; }
      #lzd24-msgs { padding:0 16px 10px; }
      #lzd24-welcome-title { font-size:18px; margin:8px 0 10px; }
      .lzd-chip { min-height:39px; font-size:14px; gap:10px; }
      .lzd-bubble-msg { max-width:88%; font-size:14px; }
      #lzd24-foot { padding:8px 10px 10px; }
      #lzd24-input { font-size:15px; }
      #lzd24-greet { width: min(300px, calc(100vw - 24px)); }
      #lzd24-bubble { width:56px; height:56px; }
      #lzd24-bubble img { width:48px; height:48px; }
    }
    `;
    var style = document.createElement("style");
    style.id = "lzd24-styles";
    style.textContent = css;
    document.head.appendChild(style);
  }

  var els = {};

  function buildQuickReplies() {
    return quickReplies().map(function (reply) {
      return '<button class="lzd-chip" type="button" data-text="' + esc(reply.text) + '">' + icon(reply.icon) + '<span>' + esc(reply.text) + '</span></button>';
    }).join("");
  }

  function build() {
    var root = document.createElement("div");
    root.id = "lzd24-root";
    root.innerHTML = `
      <div id="lzd24-panel" data-view="chat" role="dialog" aria-label="${esc(CONFIG.botName)}">
        <div id="lzd24-header">
          <button id="lzd24-menu" class="lzd-icon-btn" type="button" aria-label="${I18N[lang].menu}">${icon("menu")}</button>
          <div id="lzd24-header-title">${esc(CONFIG.botName)}</div>
          <div class="lzd-lang"><button type="button" data-lang="de">DE</button><button type="button" data-lang="en">EN</button></div>
          <button id="lzd24-history" class="lzd-icon-btn" type="button" aria-label="${I18N[lang].history}">${icon("history")}</button>
          <button id="lzd24-phone" class="lzd-icon-btn" type="button" aria-label="${I18N[lang].callNow}">${icon("phone")}</button>
          <button id="lzd24-close" class="lzd-icon-btn" type="button" aria-label="${I18N[lang].close}">${icon("close")}</button>
        </div>

        <div id="lzd24-chat-view" class="lzd-view">
          <div id="lzd24-hero">
            <div id="lzd24-brand">LizenzDeals<span>24</span></div>
            <h2 id="lzd24-intro-title"></h2>
            <p id="lzd24-intro-text"></p>
            <img id="lzd24-hero-avatar" src="${esc(avatar)}" alt="" />
            <span id="lzd24-hero-status"></span>
          </div>
          <div id="lzd24-msgs"></div>
        </div>

        <div id="lzd24-call-view" class="lzd-view lzd-secondary-view">
          <button class="lzd-back" type="button">${icon("back")}<span></span></button>
          <div id="lzd24-call-center">
            <div id="lzd24-call-icon">${icon("headset")}</div>
            <h3></h3>
            <p></p>
            <a id="lzd24-call-action" href="${esc(CONFIG.telUrl || "#")}"></a>
            <button id="lzd24-call-cancel" type="button"></button>
          </div>
        </div>

        <div id="lzd24-history-view" class="lzd-view">
          <button class="lzd-back" type="button">${icon("back")}<span></span></button>
          <div id="lzd24-history-list"></div>
          <p></p>
        </div>

        <div id="lzd24-foot">
          <div id="lzd24-disclaimer"></div>
          <div id="lzd24-inputrow">
            <button id="lzd24-plus" type="button" aria-label="Kontakt">${icon("plus")}</button>
            <textarea id="lzd24-input" rows="1"></textarea>
            <button id="lzd24-sendbtn" type="button" aria-label="${I18N[lang].send}">${icon("send")}</button>
          </div>
        </div>
      </div>

      <div id="lzd24-launcher-wrap">
        <div id="lzd24-greet" style="display:none">
          <div id="lzd24-greet-badge"><img src="${esc(avatar)}" alt="" /></div>
          <div id="lzd24-greet-headline"></div>
          <div id="lzd24-greet-body">
            <p id="lzd24-greet-text"></p>
            <div class="lzd-greet-actions">
              <button id="lzd24-start" type="button"></button>
              <a id="lzd24-contact" href="${esc(CONFIG.telUrl || CONFIG.contactUrl || "#")}"></a>
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
    els.history = root.querySelector("#lzd24-history");
    els.phone = root.querySelector("#lzd24-phone");
    els.msgs = root.querySelector("#lzd24-msgs");
    els.input = root.querySelector("#lzd24-input");
    els.send = root.querySelector("#lzd24-sendbtn");
    els.plus = root.querySelector("#lzd24-plus");
    els.greet = root.querySelector("#lzd24-greet");
    els.greetTitle = root.querySelector("#lzd24-greet-headline");
    els.greetText = root.querySelector("#lzd24-greet-text");
    els.start = root.querySelector("#lzd24-start");
    els.contact = root.querySelector("#lzd24-contact");
    els.decline = root.querySelector("#lzd24-decline");
    els.disclaimer = root.querySelector("#lzd24-disclaimer");
    els.langBtns = root.querySelectorAll(".lzd-lang button");
    els.introTitle = root.querySelector("#lzd24-intro-title");
    els.introText = root.querySelector("#lzd24-intro-text");
    els.backBtns = root.querySelectorAll(".lzd-back");
    els.callTitle = root.querySelector("#lzd24-call-center h3");
    els.callText = root.querySelector("#lzd24-call-center p");
    els.callAction = root.querySelector("#lzd24-call-action");
    els.callCancel = root.querySelector("#lzd24-call-cancel");
    els.historyList = root.querySelector("#lzd24-history-list");
    els.historyEmpty = root.querySelector("#lzd24-history-view p");

    wireEvents();
    applyLang();
  }

  function renderWelcome() {
    els.msgs.innerHTML = `
      <div id="lzd24-welcome-title">${esc(I18N[lang].welcomeTitle)}</div>
      <div id="lzd24-quick">${buildQuickReplies()}</div>
    `;
    els.msgs.querySelectorAll(".lzd-chip").forEach(function (button) {
      button.addEventListener("click", function () {
        showView("chat");
        sendUserText(button.getAttribute("data-text") || "");
      });
    });
  }

  function renderConversation() {
    renderWelcome();
    conversation.forEach(function (message) {
      addMessage(message.who, message.text, null, { persist: false });
    });
    scrollBottom();
  }

  function renderHistory() {
    if (!els.historyList) return;
    els.historyList.innerHTML = "";
    if (!conversation.length) {
      els.historyEmpty.style.display = "block";
      return;
    }
    els.historyEmpty.style.display = "none";
    conversation.slice(-30).forEach(function (message) {
      var item = document.createElement("div");
      item.className = "lzd-history-item lzd-" + message.who;
      var who = message.who === "user" ? (lang === "de" ? "Sie" : "You") : "Ginie";
      item.innerHTML = "<strong>" + esc(who) + "</strong><span>" + esc(message.text) + "</span>";
      els.historyList.appendChild(item);
    });
  }

  function wireEvents() {
    els.bubble.addEventListener("click", openPanel);
    els.start.addEventListener("click", openPanel);
    els.close.addEventListener("click", closePanel);
    els.decline.addEventListener("click", function () { els.greet.style.display = "none"; });
    els.menu.addEventListener("click", function () { showView("history"); });
    els.history.addEventListener("click", function () { showView("history"); });
    els.phone.addEventListener("click", function () { showView("call"); });
    els.callCancel.addEventListener("click", function () { showView("chat"); });
    els.backBtns.forEach(function (button) {
      button.addEventListener("click", function () { showView("chat"); });
    });
    els.plus.addEventListener("click", function () {
      window.location.href = "mailto:" + CONFIG.supportEmail;
    });
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
        renderConversation();
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
    els.contact.textContent = t.callNow;
    els.decline.textContent = t.decline;
    els.introTitle.innerHTML = esc(t.introTitle).replace("Ginie", '<span>Ginie</span>');
    els.introText.textContent = t.introText;
    els.callTitle.textContent = t.callTitle;
    els.callText.textContent = t.callText;
    els.callAction.textContent = t.callButton;
    els.callCancel.textContent = t.cancel;
    els.historyEmpty.textContent = t.noHistory;
    els.backBtns.forEach(function (button) { button.querySelector("span").textContent = t.back; });
    els.langBtns.forEach(function (b) { b.classList.toggle("lzd-active", b.getAttribute("data-lang") === lang); });
  }

  function showView(view) {
    if (view === "history") renderHistory();
    els.panel.setAttribute("data-view", view);
  }

  function openPanel() {
    els.greet.style.display = "none";
    els.panel.classList.add("lzd-open");
    els.bubble.style.display = "none";
    showView("chat");
    if (!greetedOnce) {
      renderConversation();
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

  function addMessage(who, text, sources, options) {
    options = options || {};
    var wrap = document.createElement("div");
    wrap.className = "lzd-msg lzd-" + who;
    var bubble = document.createElement("div");
    bubble.className = "lzd-bubble-msg";
    bubble.textContent = text || "";
    wrap.appendChild(bubble);
    if (CONFIG.showSources && sources && sources.length) addSources(bubble, sources);
    els.msgs.appendChild(wrap);
    if (options.persist !== false) persistMessage(who, text || "", bubble);
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

  function hideTyping() {
    var t = document.getElementById("lzd24-typing");
    if (t) t.remove();
  }

  function scrollBottom() {
    els.msgs.scrollTop = els.msgs.scrollHeight;
  }

  function onSend() {
    var text = els.input.value.trim();
    if (!text) return;
    els.input.value = "";
    els.input.style.height = "auto";
    sendUserText(text);
  }

  function sendUserText(text) {
    if (!text) return;
    showView("chat");
    addMessage("user", text);
    sendToBackend(text);
  }

  function setBusy(isBusy) {
    els.send.disabled = isBusy;
    els.input.disabled = isBusy;
  }

  function appendToken(bubble, token) {
    bubble.textContent += token;
    updateStoredMessage(bubble);
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
