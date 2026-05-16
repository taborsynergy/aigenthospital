/* ── Tabor Synergy Admin Dashboard ─────────────────────────────── */
"use strict";

const API = "";   // same origin
let adminPassword = localStorage.getItem("admin_password") || "";
let clinics = [];
let editingSlug = null;
let activeTab = "clinics";

// ── Bootstrap ────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", function () {
  if (adminPassword) {
    attemptLogin(adminPassword);
  }
  document.getElementById("login-btn").addEventListener("click", function () {
    var pw = document.getElementById("login-pw").value.trim();
    if (pw) attemptLogin(pw);
  });
  document.getElementById("login-pw").addEventListener("keydown", function (e) {
    if (e.key === "Enter") document.getElementById("login-btn").click();
  });
});

function attemptLogin(pw) {
  headers(pw).then(function (ok) {
    if (ok) {
      adminPassword = pw;
      localStorage.setItem("admin_password", pw);
      document.getElementById("login-screen").style.display = "none";
      initDashboard();
    } else {
      document.getElementById("login-error").textContent = "Incorrect password.";
    }
  });
}

function headers(pw) {
  return fetch(API + "/admin/api/stats", { headers: { "X-Admin-Password": pw } })
    .then(function (r) { return r.ok; })
    .catch(function () { return false; });
}

function authHeaders() {
  return { "Content-Type": "application/json", "X-Admin-Password": adminPassword };
}

function logout() {
  localStorage.removeItem("admin_password");
  location.reload();
}

// ── Dashboard init ────────────────────────────────────────────────
function initDashboard() {
  document.querySelectorAll(".nav-item").forEach(function (el) {
    el.addEventListener("click", function () {
      switchTab(el.dataset.tab);
    });
  });
  document.getElementById("add-clinic-btn").addEventListener("click", openAddClinic);
  document.getElementById("modal-close").addEventListener("click", closeModal);
  document.getElementById("clinic-form").addEventListener("submit", submitClinic);
  switchTab("clinics");
}

function switchTab(tab) {
  activeTab = tab;
  document.querySelectorAll(".nav-item").forEach(function (el) {
    el.classList.toggle("active", el.dataset.tab === tab);
  });
  document.querySelectorAll(".tab-content").forEach(function (el) {
    el.classList.toggle("active", el.id === "tab-" + tab);
  });
  document.querySelector(".topbar h2").textContent = {
    clinics: "Clinics",
    usage:   "Usage & Analytics",
    billing: "Billing",
    sms:     "SMS",
  }[tab] || tab;

  if (tab === "clinics") loadClinics();
  if (tab === "usage")   loadUsage();
  if (tab === "billing") loadBilling();
  if (tab === "sms")     loadSms();
}

// ── Clinics tab ───────────────────────────────────────────────────
function loadClinics() {
  fetch(API + "/admin/api/clinics", { headers: authHeaders() })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      clinics = data;
      renderClinics(data);
      renderStats(data);
    });
}

function renderStats(data) {
  var active = data.filter(function (c) { return c.subscription_status === "active"; }).length;
  var trial  = data.filter(function (c) { return c.subscription_status === "trial"; }).length;
  var mrr    = data.filter(function (c) { return c.subscription_status === "active"; })
                   .reduce(function (s, c) { return s + c.monthly_rate; }, 0);
  document.getElementById("stat-total").textContent  = data.length;
  document.getElementById("stat-active").textContent = active;
  document.getElementById("stat-trial").textContent  = trial;
  document.getElementById("stat-mrr").textContent    = "$" + mrr.toLocaleString();
}

function renderClinics(data) {
  var tbody = document.getElementById("clinic-tbody");
  if (!data.length) {
    tbody.innerHTML = '<tr><td colspan="7"><div class="empty"><div class="icon">🏥</div><p>No clinics yet. Click "+ Add Clinic" to get started.</p></div></td></tr>';
    return;
  }
  tbody.innerHTML = data.map(function (c) {
    return '<tr>' +
      '<td><strong>' + esc(c.name) + '</strong><br><span style="color:#64748b;font-size:12px">/c/' + esc(c.slug) + '</span></td>' +
      '<td>' + esc(c.specialty) + '</td>' +
      '<td>' + esc(c.agent_name) + '</td>' +
      '<td><span class="badge badge-' + c.subscription_status + '">' + c.subscription_status + '</span></td>' +
      '<td>$' + c.monthly_rate + '/mo</td>' +
      '<td>' + (c.created_at ? c.created_at.slice(0, 10) : "—") + '</td>' +
      '<td>' +
        '<button class="btn btn-outline btn-sm" onclick="editClinic(\'' + c.slug + '\')">Edit</button> ' +
        '<button class="btn btn-green btn-sm" onclick="openChat(\'' + c.slug + '\')">Chat</button> ' +
        '<button class="btn btn-danger btn-sm" onclick="deleteClinic(\'' + c.slug + '\')">Delete</button>' +
      '</td>' +
    '</tr>';
  }).join("");
}

function openChat(slug) {
  window.open("/c/" + slug, "_blank");
}

function deleteClinic(slug) {
  if (!confirm("Deactivate " + slug + "?")) return;
  fetch(API + "/admin/api/clinics/" + slug, { method: "DELETE", headers: authHeaders() })
    .then(function () { toast("Clinic deactivated."); loadClinics(); });
}

// ── Add / Edit clinic modal ────────────────────────────────────────
function openAddClinic() {
  editingSlug = null;
  document.getElementById("modal-title").textContent = "Add New Clinic";
  document.getElementById("clinic-form").reset();
  document.getElementById("field-slug").disabled = false;
  openModal();
}

function editClinic(slug) {
  var c = clinics.find(function (x) { return x.slug === slug; });
  if (!c) return;
  editingSlug = slug;
  document.getElementById("modal-title").textContent = "Edit — " + c.name;

  var form = document.getElementById("clinic-form");
  Object.keys(c).forEach(function (k) {
    var el = form.querySelector('[name="' + k + '"]');
    if (el) el.value = c[k] || "";
  });
  document.getElementById("field-slug").disabled = true;
  openModal();
}

function openModal()  { document.getElementById("clinic-modal").classList.remove("hidden"); }
function closeModal() { document.getElementById("clinic-modal").classList.add("hidden"); }

function submitClinic(e) {
  e.preventDefault();
  var form = document.getElementById("clinic-form");
  var data = {};
  new FormData(form).forEach(function (v, k) { data[k] = v; });
  data.monthly_rate = parseFloat(data.monthly_rate) || 299;

  var url    = editingSlug ? API + "/admin/api/clinics/" + editingSlug : API + "/admin/api/clinics";
  var method = editingSlug ? "PATCH" : "POST";

  fetch(url, { method: method, headers: authHeaders(), body: JSON.stringify(data) })
    .then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "Error"); });
      return r.json();
    })
    .then(function () {
      closeModal();
      toast(editingSlug ? "Clinic updated." : "Clinic created.");
      loadClinics();
    })
    .catch(function (e) { toast("Error: " + e.message, true); });
}

// ── Usage tab ─────────────────────────────────────────────────────
function loadUsage() {
  fetch(API + "/admin/api/stats", { headers: authHeaders() })
    .then(function (r) { return r.json(); })
    .then(function (data) { renderUsage(data.clinics || []); });
}

function renderUsage(rows) {
  var tbody = document.getElementById("usage-tbody");
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="5"><div class="empty"><div class="icon">📊</div><p>No usage data yet.</p></div></td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(function (c) {
    var u = c.usage || {};
    return '<tr>' +
      '<td><strong>' + esc(c.name) + '</strong></td>' +
      '<td>' + esc(c.specialty) + '</td>' +
      '<td>' + (u.messages || 0) + '</td>' +
      '<td>' + ((u.tokens || 0)).toLocaleString() + '</td>' +
      '<td><span class="badge badge-' + c.subscription_status + '">' + c.subscription_status + '</span></td>' +
    '</tr>';
  }).join("");
}

// ── Billing tab ───────────────────────────────────────────────────
function loadBilling() {
  fetch(API + "/admin/api/clinics", { headers: authHeaders() })
    .then(function (r) { return r.json(); })
    .then(renderBilling);
}

function renderBilling(data) {
  var tbody = document.getElementById("billing-tbody");
  if (!data.length) {
    tbody.innerHTML = '<tr><td colspan="5"><div class="empty"><div class="icon">💳</div><p>No clinics yet.</p></div></td></tr>';
    return;
  }
  tbody.innerHTML = data.map(function (c) {
    return '<tr>' +
      '<td><strong>' + esc(c.name) + '</strong></td>' +
      '<td><span class="badge badge-' + c.subscription_status + '">' + c.subscription_status + '</span></td>' +
      '<td>$' + c.monthly_rate + '/mo</td>' +
      '<td>' + (c.stripe_customer_id || '—') + '</td>' +
      '<td>' +
        '<button class="btn btn-primary btn-sm" onclick="sendCheckout(\'' + c.slug + '\')">Send Invoice Link</button>' +
      '</td>' +
    '</tr>';
  }).join("");
}

function sendCheckout(slug) {
  fetch(API + "/admin/api/clinics/" + slug + "/checkout", { method: "POST", headers: authHeaders() })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.url) {
        var msg = data.mock
          ? "Mock checkout URL (Stripe not configured):\n" + data.url
          : "Checkout URL (send to clinic):\n" + data.url;
        prompt("Copy this link and send it to the clinic:", data.url);
      } else {
        toast("Error: " + (data.error || "Unknown"), true);
      }
    });
}

// ── SMS tab ───────────────────────────────────────────────────────
function loadSms() {
  var sel = document.getElementById("sms-clinic-select");
  fetch(API + "/admin/api/clinics", { headers: authHeaders() })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      sel.innerHTML = '<option value="">— Select a clinic —</option>' +
        data.map(function (c) {
          return '<option value="' + esc(c.slug) + '">' + esc(c.name) + '</option>';
        }).join("");
    });

  document.getElementById("sms-send-btn").onclick = sendSms;
  document.getElementById("sms-load-btn").onclick  = function () {
    var slug = document.getElementById("sms-clinic-select").value;
    if (slug) loadSmsConvos(slug);
  };
}

function sendSms() {
  var slug = document.getElementById("sms-clinic-select").value;
  var to   = document.getElementById("sms-to").value.trim();
  var body = document.getElementById("sms-body").value.trim();
  if (!slug || !to || !body) { toast("Fill in clinic, phone, and message.", true); return; }

  fetch(API + "/admin/api/clinics/" + slug + "/sms", {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ to: to, message: body }),
  })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.sent) { toast("SMS sent!"); document.getElementById("sms-body").value = ""; }
      else toast("Failed to send SMS.", true);
    });
}

function loadSmsConvos(slug) {
  fetch(API + "/admin/api/clinics/" + slug + "/sms", { headers: authHeaders() })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var tbody = document.getElementById("sms-tbody");
      if (!data.length) {
        tbody.innerHTML = '<tr><td colspan="3"><div class="empty"><div class="icon">💬</div><p>No SMS conversations yet.</p></div></td></tr>';
        return;
      }
      tbody.innerHTML = data.map(function (c) {
        return '<tr>' +
          '<td>' + esc(c.patient_phone) + '</td>' +
          '<td>' + (c.last_message_at ? c.last_message_at.slice(0, 16).replace("T", " ") : "—") + '</td>' +
          '<td>' + esc(c.session_id) + '</td>' +
        '</tr>';
      }).join("");
    });
}

// ── Utilities ─────────────────────────────────────────────────────
function esc(str) {
  return String(str || "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function toast(msg, isError) {
  var el = document.getElementById("toast");
  el.textContent = msg;
  el.style.background = isError ? "#DC2626" : "#0F172A";
  el.classList.add("show");
  setTimeout(function () { el.classList.remove("show"); }, 3000);
}
