/* ── Aria Chat Widget ─────────────────────────────────────────────
   Drop-in script. Add to any page:
     <script src="https://aifrontdesk.taborsynergy.com/widget.js" data-clinic="your-clinic-slug" defer></script>
   ────────────────────────────────────────────────────────────── */
(function () {
  "use strict";

  // ── Config ───────────────────────────────────────────────────────
  const script       = document.currentScript || document.querySelector('script[data-ws]');
  const CLINIC_SLUG  = window.ARIA_CLINIC_SLUG || (script && script.dataset.clinic) || null;
  const _wsRoot      = (script && script.dataset.ws) || deriveWsBase();
  const WS_BASE      = CLINIC_SLUG ? _wsRoot + "/" + CLINIC_SLUG : _wsRoot;
  const RECONNECT_DELAY_MS = 3000;
  const MAX_RECONNECT      = 5;

  const QUICK_REPLIES = [
    "Schedule an appointment",
    "Check my insurance",
    "Pay my balance",
    "Office hours & location",
    "New patient info",
  ];

  // ── State ────────────────────────────────────────────────────────
  let ws            = null;
  let sessionId     = generateId();
  let reconnectCount = 0;
  let reconnectTimer = null;
  let isOpen        = false;
  let unread        = 0;
  let isWaiting     = false;   // waiting for bot reply

  // ── Build DOM ────────────────────────────────────────────────────
  injectCSS();
  const { launcher, badge, widget, connBar, msgList, typingEl, input, sendBtn, chipsEl } = buildUI();

  // Specialty → emoji map (mirrors server-side _SPECIALTY_ICONS in main.py)
  var SPECIALTY_ICONS = {
    "dental": "🦷", "dentistry": "🦷", "orthodontics": "🦷",
    "endodontics": "🦷", "periodontics": "🦷", "oral surgery": "🦷",
    "dermatology": "🔬",
    "pediatrics": "👶", "pediatric": "👶",
    "orthopedics": "🦴", "orthopedic": "🦴", "sports medicine": "🦴", "chiropractic": "🦴",
    "ophthalmology": "👁️", "optometry": "👁️", "eye care": "👁️",
    "ob-gyn": "🤰", "obstetrics": "🤰", "gynecology": "🤰", "prenatal": "🤰",
    "ent": "👂", "ear, nose": "👂", "ear nose": "👂",
    "cardiology": "❤️", "cardiac": "❤️", "heart": "❤️",
    "oncology": "🎗️", "cancer": "🎗️",
    "family medicine": "🏠", "family practice": "🏠", "primary care": "🏠",
    "urgent care": "🚑", "emergency": "🚑",
    "neurology": "🧠", "neuroscience": "🧠", "psychiatry": "🧠", "psychology": "🧠",
    "pulmonology": "🫁", "respiratory": "🫁",
    "nephrology": "🫘", "kidney": "🫘",
    "gastroenterology": "🏥", "gastro": "🏥",
    "endocrinology": "💉", "diabetes": "💉",
    "radiology": "🩻",
    "physical therapy": "🏃", "rehabilitation": "🏃",
  };

  function specialtyIcon(specialty) {
    if (!specialty) return "🏥";
    var s = specialty.toLowerCase();
    var keys = Object.keys(SPECIALTY_ICONS);
    for (var i = 0; i < keys.length; i++) {
      if (s.indexOf(keys[i]) !== -1) return SPECIALTY_ICONS[keys[i]];
    }
    return "🏥";
  }

  // Fetch clinic config and update header dynamically
  var apiBase   = location.protocol + "//" + location.host;
  var configUrl = CLINIC_SLUG
    ? apiBase + "/api/" + CLINIC_SLUG + "/config"
    : apiBase + "/api/health";
  fetch(configUrl)
    .then(function (r) { return r.json(); })
    .then(function (cfg) {
      var nameEl    = document.getElementById("aria-header-name");
      var subEl     = document.getElementById("aria-header-sub");
      var avatarEl  = document.getElementById("aria-avatar");
      var agentName  = cfg.agent_name  || cfg.agent;
      var clinicName = cfg.clinic_name || cfg.clinic;
      var specialty  = cfg.specialty   || "";
      if (nameEl   && agentName)  nameEl.textContent  = agentName;
      if (subEl    && clinicName) subEl.textContent   = clinicName + " · Front Desk";
      if (avatarEl && specialty)  avatarEl.textContent = specialtyIcon(specialty);
    })
    .catch(function () { /* keep defaults */ });

  // ── Events ──────────────────────────────────────────────────────
  launcher.addEventListener("click", toggleWidget);
  document.getElementById("aria-close-btn").addEventListener("click", closeWidget);
  sendBtn.addEventListener("click", sendMessage);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  input.addEventListener("input", autoResize);

  // ── WebSocket ────────────────────────────────────────────────────
  connect();

  // ════════════════════════════════════════════════════════════════
  // Core functions
  // ════════════════════════════════════════════════════════════════

  function connect() {
    const url = WS_BASE + "/" + sessionId;
    setConnStatus("connecting");

    ws = new WebSocket(url);

    ws.onopen = function () {
      reconnectCount = 0;
      setConnStatus(null);
    };

    ws.onmessage = function (evt) {
      const msg = JSON.parse(evt.data);
      switch (msg.type) {
        case "message":
          hideTyping();
          appendBotMessage(msg.content, msg.escalated);
          if (!isOpen) bumpUnread();
          break;
        case "typing":
          msg.active ? showTyping() : hideTyping();
          break;
        case "error":
          hideTyping();
          appendBotMessage(msg.content || "Something went wrong. Please try again.");
          break;
      }
      isWaiting = false;
      sendBtn.disabled = false;
    };

    ws.onerror = function () { /* onclose handles reconnect */ };

    ws.onclose = function () {
      setConnStatus("error");
      if (reconnectCount < MAX_RECONNECT) {
        reconnectCount++;
        reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
      }
    };
  }

  function sendMessage() {
    const text = input.value.trim();
    if (!text || isWaiting) return;

    if (!ws || ws.readyState !== WebSocket.OPEN) {
      appendBotMessage("I'm not connected right now. Reconnecting — please try again in a moment.");
      connect();
      return;
    }

    appendUserMessage(text);
    hideChips();
    input.value = "";
    autoResize();

    isWaiting = true;
    sendBtn.disabled = true;

    ws.send(JSON.stringify({ message: text }));
  }

  function sendQuickReply(text) {
    input.value = text;
    sendMessage();
  }

  // ── UI helpers ──────────────────────────────────────────────────

  function appendBotMessage(text, escalated) {
    const wrap = document.createElement("div");
    wrap.className = "aria-msg bot";

    if (escalated) {
      const banner = document.createElement("div");
      banner.className = "aria-escalation-banner";
      banner.textContent = "⚡ A team member has been notified and will join shortly.";
      msgList.appendChild(banner);
    }

    const bubble = document.createElement("div");
    bubble.className = "aria-bubble";
    bubble.textContent = text;

    const time = document.createElement("div");
    time.className = "aria-time";
    time.textContent = formatTime(new Date());

    wrap.appendChild(bubble);
    wrap.appendChild(time);
    msgList.appendChild(wrap);
    scrollToBottom();
  }

  function appendUserMessage(text) {
    const wrap = document.createElement("div");
    wrap.className = "aria-msg user";

    const bubble = document.createElement("div");
    bubble.className = "aria-bubble";
    bubble.textContent = text;

    const time = document.createElement("div");
    time.className = "aria-time";
    time.textContent = formatTime(new Date());

    wrap.appendChild(bubble);
    wrap.appendChild(time);
    msgList.appendChild(wrap);
    scrollToBottom();
  }

  function showTyping() {
    typingEl.classList.add("visible");
    scrollToBottom();
  }
  function hideTyping() { typingEl.classList.remove("visible"); }

  function hideChips()  { chipsEl.style.display = "none"; }

  function scrollToBottom() {
    requestAnimationFrame(function () { msgList.scrollTop = msgList.scrollHeight; });
  }

  function setConnStatus(state) {
    connBar.className = "";
    if (state === "connecting") { connBar.className = "connecting"; connBar.textContent = "Connecting…"; }
    if (state === "error")      { connBar.className = "error";      connBar.textContent = "Connection lost. Reconnecting…"; }
  }

  function toggleWidget() {
    isOpen ? closeWidget() : openWidget();
  }

  function openWidget() {
    isOpen = true;
    widget.classList.remove("hidden");
    unread = 0;
    badge.style.display = "none";
    badge.textContent = "";
    input.focus();
  }

  function closeWidget() {
    isOpen = false;
    widget.classList.add("hidden");
  }

  function bumpUnread() {
    unread++;
    badge.textContent = unread > 9 ? "9+" : unread;
    badge.style.display = "flex";
  }

  function autoResize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 100) + "px";
  }

  // ── DOM construction ─────────────────────────────────────────────

  function buildUI() {
    // Launcher
    const launcher = document.createElement("button");
    launcher.id = "aria-launcher";
    launcher.setAttribute("aria-label", "Open Aria chat");
    launcher.innerHTML = iconChat() + '<div id="aria-badge"></div>';
    document.body.appendChild(launcher);
    const badge = document.getElementById("aria-badge");

    // Widget
    const widget = document.createElement("div");
    widget.id = "aria-widget";
    widget.className = "hidden";
    widget.setAttribute("role", "dialog");
    widget.setAttribute("aria-label", "Aria chat window");

    // Header
    widget.innerHTML = `
      <div id="aria-header">
        <div id="aria-avatar">🏥</div>
        <div id="aria-header-info">
          <div id="aria-header-name">Aria</div>
          <div id="aria-header-sub">Front Desk Assistant</div>
        </div>
        <div id="aria-status-dot" title="Online"></div>
        <button id="aria-close-btn" aria-label="Close chat">✕</button>
      </div>
      <div id="aria-conn-bar"></div>
      <div id="aria-messages"></div>
      <div id="aria-typing">
        <div class="aria-dot"></div>
        <div class="aria-dot"></div>
        <div class="aria-dot"></div>
      </div>
      <div id="aria-chips"></div>
      <div id="aria-input-area">
        <textarea id="aria-input" rows="1" placeholder="Type a message…" aria-label="Message"></textarea>
        <button id="aria-send-btn" aria-label="Send message">${iconSend()}</button>
      </div>
      <div id="aria-footer">Powered by <strong>Tabor Synergy</strong></div>
    `;
    document.body.appendChild(widget);

    const connBar  = document.getElementById("aria-conn-bar");
    const msgList  = document.getElementById("aria-messages");
    const typingEl = document.getElementById("aria-typing");
    const input    = document.getElementById("aria-input");
    const sendBtn  = document.getElementById("aria-send-btn");
    const chipsEl  = document.getElementById("aria-chips");

    // Quick-reply chips
    QUICK_REPLIES.forEach(function (label) {
      const chip = document.createElement("button");
      chip.className = "aria-chip";
      chip.textContent = label;
      chip.addEventListener("click", function () { sendQuickReply(label); });
      chipsEl.appendChild(chip);
    });

    return { launcher, badge, widget, connBar, msgList, typingEl, input, sendBtn, chipsEl };
  }

  function injectCSS() {
    if (document.getElementById("aria-widget-css")) return;
    const link = document.createElement("link");
    link.id   = "aria-widget-css";
    link.rel  = "stylesheet";
    link.href = (script && script.src ? script.src.replace(/widget\.js.*$/, "") : "/") + "widget.css";
    document.head.appendChild(link);
  }

  // ── Utilities ────────────────────────────────────────────────────

  function generateId() {
    return "aria_" + Math.random().toString(36).slice(2, 11);
  }

  function formatTime(d) {
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function deriveWsBase() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    return proto + "://" + location.host + "/ws";
  }

  function iconChat() {
    return `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-2 12H6v-2h12v2zm0-3H6V9h12v2zm0-3H6V6h12v2z"/>
    </svg>`;
  }

  function iconSend() {
    return `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
    </svg>`;
  }
})();
