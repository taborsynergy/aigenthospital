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
  switchTab("pipeline");
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
    pipeline: "Sales Pipeline",
    clinics:  "All Clinics",
    usage:    "Usage & Analytics",
    billing:  "Billing",
    sms:      "SMS",
  }[tab] || tab;

  if (tab === "pipeline") loadPipeline();
  if (tab === "clinics")  loadClinics();
  if (tab === "usage")    loadUsage();
  if (tab === "billing")  loadBilling();
  if (tab === "sms")      loadSms();
}

// ── Pipeline tab ──────────────────────────────────────────────────
function loadPipeline() {
  fetch(API + "/admin/api/stats", { headers: authHeaders() })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var all = data.clinics || [];
      renderPipeline(all, data);
    });
}

function planLabel(rate) {
  if (rate >= 997) return "Pro — $997/mo";
  if (rate >= 597) return "Growth — $597/mo";
  return "Starter — $297/mo";
}

function renderPipeline(all, stats) {
  var now = new Date();

  var hot    = [];   // trial, expires in 1-7 days
  var trials = [];   // trial, > 7 days left
  var paid   = [];   // active
  var lost   = [];   // expired trial or cancelled/past_due

  all.forEach(function (c) {
    var d = daysRemaining(c.trial_ends_at);
    if (c.subscription_status === "trial") {
      if (d !== null && d <= 0)       lost.push(c);
      else if (d !== null && d <= 7)  hot.push(c);
      else                            trials.push(c);
    } else if (c.subscription_status === "active") {
      paid.push(c);
    } else {
      lost.push(c);
    }
  });

  // Stats strip
  var conv = all.length ? Math.round((paid.length / all.length) * 100) : 0;
  var mrr  = paid.reduce(function (s, c) { return s + c.monthly_rate; }, 0);
  document.getElementById("pipeline-stats").innerHTML = [
    { val: all.length,    lbl: "Total Signups",        color: "#0F172A" },
    { val: trials.length, lbl: "Active Trials",         color: "#1D4ED8" },
    { val: hot.length,    lbl: "Follow Up Now 🔥",      color: "#D97706" },
    { val: paid.length,   lbl: "Paid Customers",        color: "#059669" },
    { val: lost.length,   lbl: "Lost / Expired",        color: "#DC2626" },
    { val: "$" + mrr.toLocaleString(), lbl: "MRR",      color: "#7C3AED" },
    { val: conv + "%",    lbl: "Conversion Rate",       color: "#0369A1" },
  ].map(function (s) {
    return '<div class="stat-card"><div class="value" style="color:' + s.color + '">' + s.val + '</div>' +
           '<div class="label">' + s.lbl + '</div></div>';
  }).join("");

  // Expiry alert
  if (hot.length > 0) {
    document.getElementById("expiry-alert").style.display = "block";
    document.getElementById("expiry-alert-text").textContent =
      " " + hot.length + " trial(s) expire within 7 days — call or email them now to convert.";
  } else {
    document.getElementById("expiry-alert").style.display = "none";
  }

  // Hot leads table
  document.getElementById("hot-tbody").innerHTML = hot.length ? hot.map(function (c) {
    var d = daysRemaining(c.trial_ends_at);
    return "<tr>" +
      "<td><strong>" + esc(c.name) + "</strong></td>" +
      "<td>" + esc(c.specialty) + "</td>" +
      "<td>" + esc(c.email) + (c.phone ? "<br><small>" + esc(c.phone) + "</small>" : "") + "</td>" +
      "<td>" + planLabel(c.monthly_rate) + "</td>" +
      "<td>" + (c.trial_ends_at ? c.trial_ends_at.slice(0,10) : "—") + "</td>" +
      "<td><strong style='color:" + (d <= 3 ? "#DC2626" : "#D97706") + "'>" + d + " days</strong></td>" +
      "<td><button class='btn btn-sm' style='background:#059669;color:#fff' onclick='activateClinic(\"" + esc(c.slug) + "\")'>Activate</button> " +
          "<button class='btn btn-outline btn-sm' onclick='openNotes(\"" + esc(c.slug) + "\",\"" + esc(c.name) + "\",\"" + esc(c.admin_notes||"") + "\")'>Notes</button></td>" +
    "</tr>";
  }).join("") : "<tr><td colspan='7' style='text-align:center;padding:20px;color:#64748b'>No hot leads right now — good!</td></tr>";

  // Paid table
  document.getElementById("paid-tbody").innerHTML = paid.length ? paid.map(function (c) {
    var u = c.usage || {};
    var renewDays = daysRemaining(c.subscription_ends_at);
    var renewColor = renewDays !== null && renewDays <= 5 ? "#DC2626" : "#059669";
    return "<tr>" +
      "<td><strong>" + esc(c.name) + "</strong><br><small style='color:#64748b'>" + esc(c.email) + "</small></td>" +
      "<td style='color:#059669;font-weight:700'>" + planLabel(c.monthly_rate) + "</td>" +
      "<td>" + (c.activated_at ? c.activated_at.slice(0,10) : "—") + "</td>" +
      "<td style='color:" + renewColor + ";font-weight:600'>" + (renewDays !== null ? renewDays + "d" : "—") + "</td>" +
      "<td>" + (u.messages || 0) + " msgs</td>" +
      "<td style='max-width:160px;font-size:12px;color:#64748b;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>" +
        (c.admin_notes ? esc(c.admin_notes.slice(0,60)) + (c.admin_notes.length > 60 ? "…" : "") : "<em style='color:#cbd5e1'>No notes</em>") + "</td>" +
      "<td><button class='btn btn-sm' style='background:#059669;color:#fff' onclick='activateClinic(\"" + esc(c.slug) + "\")'>Renew 30d</button> " +
          "<button class='btn btn-outline btn-sm' onclick='openNotes(\"" + esc(c.slug) + "\",\"" + esc(c.name) + "\",\"" + esc(c.admin_notes||"") + "\")'>Notes</button></td>" +
    "</tr>";
  }).join("") : "<tr><td colspan='7' style='text-align:center;padding:20px;color:#64748b'>No paid customers yet — convert those trials!</td></tr>";

  // Active trials table
  document.getElementById("trial-tbody").innerHTML = trials.length ? trials.map(function (c) {
    var d = daysRemaining(c.trial_ends_at);
    return "<tr>" +
      "<td><strong>" + esc(c.name) + "</strong></td>" +
      "<td>" + esc(c.specialty) + "</td>" +
      "<td>" + esc(c.email) + "</td>" +
      "<td>" + planLabel(c.monthly_rate) + "</td>" +
      "<td>" + (c.created_at ? c.created_at.slice(0,10) : "—") + "</td>" +
      "<td>" + (c.trial_ends_at ? c.trial_ends_at.slice(0,10) : "—") + "</td>" +
      "<td>" + (d !== null ? d + " days" : "—") + "</td>" +
    "</tr>";
  }).join("") : "<tr><td colspan='7' style='text-align:center;padding:20px;color:#64748b'>No active trials</td></tr>";

  // Lost table
  document.getElementById("lost-tbody").innerHTML = lost.length ? lost.map(function (c) {
    var endDate = c.trial_ends_at ? c.trial_ends_at.slice(0,10) : "—";
    return "<tr>" +
      "<td><strong>" + esc(c.name) + "</strong></td>" +
      "<td>" + esc(c.specialty) + "</td>" +
      "<td>" + esc(c.email) + "</td>" +
      "<td>" + planLabel(c.monthly_rate) + "</td>" +
      "<td style='color:#DC2626'>" + endDate + "</td>" +
      "<td><button class='btn btn-sm' style='background:#059669;color:#fff' onclick='activateClinic(\"" + esc(c.slug) + "\")'>Reactivate</button> " +
          "<a class='btn btn-outline btn-sm' href='mailto:" + esc(c.email) + "?subject=Your%20Tabor%20Synergy%20trial&body=Hi%2C%20your%20trial%20has%20expired.%20Ready%20to%20continue%3F'>Win-Back Email</a></td>" +
    "</tr>";
  }).join("") : "<tr><td colspan='6' style='text-align:center;padding:20px;color:#64748b'>No lost leads — great!</td></tr>";
}

// ── Notes modal ───────────────────────────────────────────────────
var notesSlug = "";
function openNotes(slug, name, current) {
  notesSlug = slug;
  document.getElementById("notes-clinic-name").textContent = name;
  document.getElementById("notes-textarea").value = current || "";
  document.getElementById("notes-modal").classList.remove("hidden");
}
function closeNotesModal() {
  document.getElementById("notes-modal").classList.add("hidden");
}
function saveNotes() {
  var notes = document.getElementById("notes-textarea").value;
  fetch(API + "/admin/api/clinics/" + notesSlug + "/notes", {
    method: "PATCH",
    headers: authHeaders(),
    body: JSON.stringify({ notes: notes }),
  })
    .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
    .then(function () { closeNotesModal(); toast("Notes saved."); loadPipeline(); })
    .catch(function () { toast("Failed to save notes.", true); });
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

function daysRemaining(isoDate) {
  if (!isoDate) return null;
  return Math.ceil((new Date(isoDate) - Date.now()) / 86400000);
}

function statusBadge(c) {
  if (c.subscription_status === "trial") {
    var diff = daysRemaining(c.trial_ends_at);
    var label = diff === null ? "—" : diff > 0 ? diff + "d left" : "Expired";
    var color = (diff !== null && diff <= 0) ? "past_due" : "trial";
    return '<span class="badge badge-' + color + '">trial</span> <small style="color:#64748b">' + label + '</small>';
  }
  if (c.subscription_status === "active") {
    var diff2 = daysRemaining(c.subscription_ends_at);
    var label2 = diff2 === null ? "—" : diff2 > 0 ? diff2 + "d left" : "Expired";
    var color2 = (diff2 !== null && diff2 <= 0) ? "past_due" : "active";
    return '<span class="badge badge-' + color2 + '">active</span> <small style="color:#64748b">renews ' + label2 + '</small>';
  }
  return '<span class="badge badge-' + c.subscription_status + '">' + c.subscription_status + '</span>';
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
      '<td>' + statusBadge(c) + '</td>' +
      '<td>$' + c.monthly_rate + '/mo</td>' +
      '<td>' + (c.created_at ? c.created_at.slice(0, 10) : "—") + '</td>' +
      '<td>' +
        '<button class="btn btn-outline btn-sm" onclick="editClinic(\'' + c.slug + '\')">Edit</button> ' +
        '<button class="btn btn-green btn-sm" onclick="openChat(\'' + c.slug + '\')">Chat</button> ' +
        '<button class="btn btn-sm" style="background:#059669;color:#fff" onclick="activateClinic(\'' + c.slug + '\')">Activate 30d</button> ' +
        '<button class="btn btn-sm" style="background:#DC2626;color:#fff" onclick="suspendClinic(\'' + c.slug + '\')">Suspend</button> ' +
        '<button class="btn btn-sm" style="background:#6D28D9;color:#fff" onclick="openResetPw(\'' + c.slug + '\',\'' + esc(c.name) + '\')">Reset Pw</button> ' +
        '<button class="btn btn-danger btn-sm" onclick="deleteClinic(\'' + c.slug + '\')">Delete</button>' +
      '</td>' +
    '</tr>';
  }).join("");
}

function openChat(slug) {
  window.open("/c/" + slug, "_blank");
}

function activateClinic(slug) {
  if (!confirm("Activate 30-day subscription for " + slug + "?\n\nThis confirms payment has been received.")) return;
  fetch(API + "/admin/api/clinics/" + slug + "/activate", { method: "POST", headers: authHeaders() })
    .then(function (r) {
      if (!r.ok) throw new Error("Failed");
      toast("Subscription activated — expires in 30 days.");
      loadClinics();
    })
    .catch(function () { toast("Error activating subscription."); });
}

function suspendClinic(slug) {
  if (!confirm("Suspend access for " + slug + "?\n\nPatients will see a 'service paused' message immediately.")) return;
  fetch(API + "/admin/api/clinics/" + slug, {
    method: "PATCH",
    headers: authHeaders(),
    body: JSON.stringify({ subscription_status: "cancelled" }),
  })
    .then(function (r) {
      if (!r.ok) throw new Error("Failed");
      toast("Access suspended for " + slug + ".");
      loadClinics();
    })
    .catch(function () { toast("Error suspending clinic.", true); });
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
  document.getElementById("initial-password-field").style.display = "";
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
  // Password field not shown when editing — use "Reset Pw" button instead
  document.getElementById("initial-password-field").style.display = "none";
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
  // On edit, strip initial_password — use Reset Pw endpoint instead
  if (editingSlug) delete data.initial_password;

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
    var noteSnippet = c.admin_notes
      ? esc(c.admin_notes.slice(0, 50)) + (c.admin_notes.length > 50 ? "…" : "")
      : '<em style="color:#cbd5e1">No notes</em>';
    return '<tr>' +
      '<td><strong>' + esc(c.name) + '</strong><br><small style="color:#64748b">' + esc(c.email) + '</small></td>' +
      '<td><span class="badge badge-' + c.subscription_status + '">' + c.subscription_status + '</span></td>' +
      '<td style="font-weight:600">$' + c.monthly_rate + '/mo</td>' +
      '<td style="font-size:12px;color:#64748b">' + noteSnippet + '</td>' +
      '<td>' +
        '<button class="btn btn-primary btn-sm" onclick="sendCheckout(\'' + c.slug + '\')">Send PayPal Link</button> ' +
        '<button class="btn btn-sm" style="background:#059669;color:#fff" onclick="activateClinic(\'' + c.slug + '\')">Activate 30d</button>' +
      '</td>' +
    '</tr>';
  }).join("");
}

function sendCheckout(slug) {
  fetch(API + "/admin/api/clinics/" + slug + "/checkout", { method: "POST", headers: authHeaders() })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.url) {
        var label = "PayPal link copied! Send it to the clinic, then click Activate 30d after payment.";
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(data.url).then(function () {
            toast(label);
          }).catch(function () {
            prompt("Copy this PayPal link and send it to the clinic:", data.url);
          });
        } else {
          prompt("Copy this PayPal link and send it to the clinic:", data.url);
        }
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

// ── Reset Password modal ──────────────────────────────────────────
var resetPwSlug = "";
function openResetPw(slug, name) {
  resetPwSlug = slug;
  document.getElementById("resetpw-clinic-name").textContent = name;
  document.getElementById("resetpw-input").value = "";
  document.getElementById("resetpw-error").textContent = "";
  document.getElementById("resetpw-modal").classList.remove("hidden");
  setTimeout(function () { document.getElementById("resetpw-input").focus(); }, 100);
}
function closeResetPw() {
  document.getElementById("resetpw-modal").classList.add("hidden");
}
function saveResetPw() {
  var pw = document.getElementById("resetpw-input").value.trim();
  if (pw.length < 6) {
    document.getElementById("resetpw-error").textContent = "Password must be at least 6 characters.";
    return;
  }
  fetch(API + "/admin/api/clinics/" + resetPwSlug + "/reset-password", {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ new_password: pw }),
  })
    .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
    .then(function () { closeResetPw(); toast("Password reset successfully."); })
    .catch(function () { document.getElementById("resetpw-error").textContent = "Error resetting password."; });
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
