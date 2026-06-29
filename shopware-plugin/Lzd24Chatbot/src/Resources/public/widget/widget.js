/* =============================================================================
 * LZD24 Support — embeddable chat widget
 * Single-file, dependency-free. Load with ONE tag (e.g. via Google Tag Manager):
 *
 *   <script src="https://your-cdn/widget.js" defer></script>
 *
 * Everything tweakable lives in CONFIG below — edit it without touching logic.
 * ===========================================================================*/
(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // CONFIG — edit these, not the logic below.
  // You may also override any field BEFORE this script loads via:
  //   window.LZD24_CONFIG = { backendUrl: "...", primaryColor: "#..." };
  // ---------------------------------------------------------------------------
  var CONFIG = Object.assign(
    {
      backendUrl: "http://localhost:8000/chat", // FastAPI /chat endpoint
      botName: "Ginie - Ihr Lizenzassistent",
      avatarUrl: "https://api.dicebear.com/9.x/bottts/svg?seed=LZD24", // placeholder
      primaryColor: "#1d4ed8",
      primaryColorDark: "#1e40af",
      defaultLang: "de", // "de" | "en"
      supportEmail: "support@lizenzdeals24.de",
      whatsappUrl: "",
      greetingDE: "Wir sind online für Sie.",
      greetingEN: "We are online for you.",
      disclaimerDE: "Bitte keine persönlichen Daten eingeben.",
      disclaimerEN: "Please do not enter any personal data.",
      showGreetingPopup: true,
      greetingDelayMs: 1200,
      showSources: true,
      maxSourceNames: 2,
    },
    window.LZD24_CONFIG || {}
  );

  // Static UI strings per language.
  var I18N = {
    de: {
      title: CONFIG.botName,
      placeholder: "Ihre Frage…",
      send: "Senden",
      greeting: CONFIG.greetingDE,
      disclaimer: CONFIG.disclaimerDE,
      welcome: CONFIG.greetingDE,
      error: "Verbindung fehlgeschlagen. Bitte später erneut versuchen.",
      open: "Chat öffnen",
      email: "E-Mail",
      whatsapp: "WhatsApp",
    },
    en: {
      title: CONFIG.botName,
      placeholder: "Your question…",
      send: "Send",
      greeting: CONFIG.greetingEN,
      disclaimer: CONFIG.disclaimerEN,
      welcome: CONFIG.greetingEN,
      error: "Connection failed. Please try again later.",
      open: "Open chat",
      email: "Email",
      whatsapp: "WhatsApp",
    },
  };

  var lang = CONFIG.defaultLang === "en" ? "en" : "de";
  var greetedOnce = false;

  // ---------------------------------------------------------------------------
  // Styles (scoped under #lzd24-root to avoid clashing with the host page).
  // ---------------------------------------------------------------------------
  function injectStyles() {
    if (document.getElementById("lzd24-styles")) return;
    var css = `
    #lzd24-root, #lzd24-root * { box-sizing: border-box; }
    #lzd24-root {
      --lzd-primary: ${CONFIG.primaryColor};
      --lzd-primary-dark: ${CONFIG.primaryColorDark};
      position: fixed; bottom: 20px; right: 20px; z-index: 2147483000;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    #lzd24-bubble {
      width: 60px; height: 60px; border-radius: 50%; cursor: pointer;
      background: var(--lzd-primary); border: none; box-shadow: 0 6px 20px rgba(0,0,0,.25);
      display: flex; align-items: center; justify-content: center; transition: transform .15s ease;
    }
    #lzd24-bubble:hover { transform: scale(1.06); }
    #lzd24-bubble img { width: 38px; height: 38px; border-radius: 50%; background:#fff; }
    #lzd24-greet {
      position: absolute; bottom: 72px; right: 0; max-width: 260px;
      background:#fff; color:#1f2937; padding:12px 14px; border-radius:14px;
      box-shadow:0 8px 24px rgba(0,0,0,.18); font-size:14px; line-height:1.4;
      animation: lzd-pop .25s ease;
    }
    #lzd24-greet .lzd-x { position:absolute; top:4px; right:8px; cursor:pointer; color:#9ca3af; font-size:16px; }
    @keyframes lzd-pop { from { opacity:0; transform: translateY(8px);} to {opacity:1; transform:none;} }

    #lzd24-panel {
      position: absolute; bottom: 0; right: 0; width: 360px; max-width: calc(100vw - 32px);
      height: 520px; max-height: calc(100vh - 40px);
      background:#fff; border-radius:16px; overflow:hidden; display:none;
      flex-direction:column; box-shadow:0 12px 40px rgba(0,0,0,.28);
    }
    #lzd24-panel.lzd-open { display:flex; animation: lzd-pop .2s ease; }
    #lzd24-header {
      background: linear-gradient(135deg, var(--lzd-primary), var(--lzd-primary-dark));
      color:#fff; padding:12px 14px; display:flex; align-items:center; gap:10px;
    }
    #lzd24-header img { width:34px; height:34px; border-radius:50%; background:#fff; }
    #lzd24-header .lzd-name { font-weight:600; font-size:15px; flex:1; }
    #lzd24-header .lzd-status { font-size:11px; opacity:.85; }
    .lzd-lang { display:flex; gap:4px; }
    .lzd-lang button {
      background: rgba(255,255,255,.18); color:#fff; border:none; border-radius:6px;
      padding:3px 7px; font-size:11px; cursor:pointer; font-weight:600;
    }
    .lzd-lang button.lzd-active { background:#fff; color: var(--lzd-primary); }
    #lzd24-close { background:none; border:none; color:#fff; font-size:20px; cursor:pointer; line-height:1; }

    #lzd24-msgs { flex:1; overflow-y:auto; padding:14px; background:#f8fafc; }
    .lzd-msg { margin-bottom:10px; display:flex; }
    .lzd-msg.lzd-bot { justify-content:flex-start; }
    .lzd-msg.lzd-user { justify-content:flex-end; }
    .lzd-bubble-msg {
      max-width:80%; padding:9px 12px; border-radius:14px; font-size:14px; line-height:1.45;
      white-space:pre-wrap; word-wrap:break-word;
    }
    .lzd-bot .lzd-bubble-msg { background:#fff; color:#1f2937; border:1px solid #e5e7eb; border-bottom-left-radius:4px; }
    .lzd-user .lzd-bubble-msg { background: var(--lzd-primary); color:#fff; border-bottom-right-radius:4px; }
    .lzd-sources { font-size:11px; color:#6b7280; margin-top:4px; padding-left:2px; }

    .lzd-typing { display:inline-flex; gap:4px; align-items:center; padding:10px 12px; }
    .lzd-typing span { width:7px; height:7px; background:#9ca3af; border-radius:50%; animation: lzd-blink 1.2s infinite; }
    .lzd-typing span:nth-child(2){ animation-delay:.2s; } .lzd-typing span:nth-child(3){ animation-delay:.4s; }
    @keyframes lzd-blink { 0%,80%,100%{opacity:.3;} 40%{opacity:1;} }

    #lzd24-foot { border-top:1px solid #e5e7eb; background:#fff; }
    #lzd24-actions { display:flex; gap:8px; padding:8px 10px 0; }
    #lzd24-actions a {
      flex:1; text-align:center; text-decoration:none; border-radius:8px; padding:7px 8px;
      font-size:12px; font-weight:700; border:1px solid #d1d5db;
    }
    #lzd24-email { color: var(--lzd-primary); background:#eff6ff; }
    #lzd24-whatsapp { color:#047857; background:#ecfdf5; border-color:#a7f3d0 !important; }
    #lzd24-disclaimer { font-size:11px; color:#9ca3af; text-align:center; padding:6px 10px 0; }
    #lzd24-inputrow { display:flex; gap:8px; padding:10px; }
    #lzd24-input {
      flex:1; resize:none; border:1px solid #d1d5db; border-radius:10px; padding:9px 11px;
      font-size:14px; font-family:inherit; max-height:90px; outline:none;
    }
    #lzd24-input:focus { border-color: var(--lzd-primary); }
    #lzd24-sendbtn {
      background: var(--lzd-primary); color:#fff; border:none; border-radius:10px;
      padding:0 14px; cursor:pointer; font-weight:600; font-size:14px;
    }
    #lzd24-sendbtn:disabled { opacity:.5; cursor:default; }
    `;
    var style = document.createElement("style");
    style.id = "lzd24-styles";
    style.textContent = css;
    document.head.appendChild(style);
  }

  // ---------------------------------------------------------------------------
  // DOM construction
  // ---------------------------------------------------------------------------
  var els = {};

  function build() {
    var root = document.createElement("div");
    root.id = "lzd24-root";
    root.innerHTML = `
      <div id="lzd24-panel" role="dialog" aria-label="${CONFIG.botName}">
        <div id="lzd24-header">
          <img src="${CONFIG.avatarUrl}" alt="" />
          <div style="flex:1">
            <div class="lzd-name">${CONFIG.botName}</div>
            <div class="lzd-status">● Online</div>
          </div>
          <div class="lzd-lang">
            <button data-lang="de">DE</button>
            <button data-lang="en">EN</button>
          </div>
          <button id="lzd24-close" aria-label="Close">×</button>
        </div>
        <div id="lzd24-msgs"></div>
        <div id="lzd24-foot">
          <div id="lzd24-actions">
            <a id="lzd24-email" href="mailto:${CONFIG.supportEmail}" target="_blank" rel="noopener"></a>
            <a id="lzd24-whatsapp" href="${CONFIG.whatsappUrl}" target="_blank" rel="noopener"></a>
          </div>
          <div id="lzd24-disclaimer"></div>
          <div id="lzd24-inputrow">
            <textarea id="lzd24-input" rows="1"></textarea>
            <button id="lzd24-sendbtn"></button>
          </div>
        </div>
      </div>
      <div id="lzd24-greet" style="display:none">
        <span class="lzd-x">×</span>
        <span class="lzd-greet-text"></span>
      </div>
      <button id="lzd24-bubble" aria-label="${I18N[lang].open}">
        <img src="${CONFIG.avatarUrl}" alt="" />
      </button>
    `;
    document.body.appendChild(root);

    els.root = root;
    els.panel = root.querySelector("#lzd24-panel");
    els.bubble = root.querySelector("#lzd24-bubble");
    els.close = root.querySelector("#lzd24-close");
    els.msgs = root.querySelector("#lzd24-msgs");
    els.input = root.querySelector("#lzd24-input");
    els.send = root.querySelector("#lzd24-sendbtn");
    els.email = root.querySelector("#lzd24-email");
    els.whatsapp = root.querySelector("#lzd24-whatsapp");
    els.greet = root.querySelector("#lzd24-greet");
    els.greetText = root.querySelector(".lzd-greet-text");
    els.greetX = root.querySelector(".lzd-x");
    els.disclaimer = root.querySelector("#lzd24-disclaimer");
    els.langBtns = root.querySelectorAll(".lzd-lang button");

    wireEvents();
    applyLang();
  }

  // ---------------------------------------------------------------------------
  // Events
  // ---------------------------------------------------------------------------
  function wireEvents() {
    els.bubble.addEventListener("click", openPanel);
    els.close.addEventListener("click", closePanel);
    els.send.addEventListener("click", onSend);
    els.greetX.addEventListener("click", function () { els.greet.style.display = "none"; });
    els.greet.addEventListener("click", function (e) {
      if (e.target !== els.greetX) openPanel();
    });

    els.input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        onSend();
      }
    });
    els.input.addEventListener("input", function () {
      els.input.style.height = "auto";
      els.input.style.height = Math.min(els.input.scrollHeight, 90) + "px";
    });

    els.langBtns.forEach(function (b) {
      b.addEventListener("click", function () {
        lang = b.getAttribute("data-lang");
        applyLang();
      });
    });
  }

  function applyLang() {
    var t = I18N[lang];
    els.input.placeholder = t.placeholder;
    els.send.textContent = t.send;
    els.email.textContent = t.email;
    els.email.href = "mailto:" + CONFIG.supportEmail;
    els.whatsapp.textContent = t.whatsapp;
    els.whatsapp.style.display = CONFIG.whatsappUrl ? "block" : "none";
    els.disclaimer.textContent = t.disclaimer;
    els.greetText.textContent = t.greeting;
    els.langBtns.forEach(function (b) {
      b.classList.toggle("lzd-active", b.getAttribute("data-lang") === lang);
    });
  }

  function openPanel() {
    els.greet.style.display = "none";
    els.panel.classList.add("lzd-open");
    els.bubble.style.display = "none";
    if (!greetedOnce) {
      addMessage("bot", I18N[lang].welcome);
      greetedOnce = true;
    }
    setTimeout(function () { els.input.focus(); }, 50);
  }

  function closePanel() {
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
    bubble.textContent = text;
    wrap.appendChild(bubble);

    if (CONFIG.showSources && sources && sources.length) {
      var s = document.createElement("div");
      s.className = "lzd-sources";
      var names = sources.map(function (x) { return x.name; }).filter(Boolean);
      if (names.length) {
        var visible = names.slice(0, CONFIG.maxSourceNames || 2);
        var more = names.length > visible.length ? " +" + (names.length - visible.length) : "";
        s.textContent = (lang === "de" ? "Quellen: " : "Sources: ") + visible.join(" · ") + more;
        bubble.appendChild(s);
      }
    }
    els.msgs.appendChild(wrap);
    els.msgs.scrollTop = els.msgs.scrollHeight;
    return wrap;
  }

  function showTyping() {
    var wrap = document.createElement("div");
    wrap.className = "lzd-msg lzd-bot";
    wrap.id = "lzd24-typing";
    wrap.innerHTML = '<div class="lzd-bubble-msg"><div class="lzd-typing"><span></span><span></span><span></span></div></div>';
    els.msgs.appendChild(wrap);
    els.msgs.scrollTop = els.msgs.scrollHeight;
  }
  function hideTyping() {
    var t = document.getElementById("lzd24-typing");
    if (t) t.remove();
  }

  function onSend() {
    var text = els.input.value.trim();
    if (!text) return;
    els.input.value = "";
    els.input.style.height = "auto";
    addMessage("user", text);
    sendToBackend(text);
  }

  function sendToBackend(text) {
    els.send.disabled = true;
    showTyping();
    fetch(CONFIG.backendUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, lang: lang }),
    })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        hideTyping();
        addMessage("bot", data.answer || I18N[lang].error, data.sources);
      })
      .catch(function () {
        hideTyping();
        addMessage("bot", I18N[lang].error);
      })
      .finally(function () {
        els.send.disabled = false;
        els.input.focus();
      });
  }

  // ---------------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------------
  function init() {
    injectStyles();
    build();
    if (CONFIG.showGreetingPopup) {
      setTimeout(function () {
        if (!els.panel.classList.contains("lzd-open")) {
          els.greet.style.display = "block";
        }
      }, CONFIG.greetingDelayMs);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
