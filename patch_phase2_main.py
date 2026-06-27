"""Patch main.py for Phase 2: wire routers + add Setup tab sections 5-7."""
import sys
sys.stdout.reconfigure(encoding="utf-8")

with open("backend/main.py", "r", encoding="utf-8") as f:
    content = f.read()

# ── 1. Add router imports ─────────────────────────────────────────────────────
OLD_IMPORT = "from backend.routers.whitelabel import router as whitelabel_router  # noqa: E402"
NEW_IMPORT = (OLD_IMPORT +
    "\nfrom backend.routers.appointment_types import router as appt_types_router  # noqa: E402"
    "\nfrom backend.routers.holidays import router as holidays_router  # noqa: E402")
assert OLD_IMPORT in content, "import anchor not found"
content = content.replace(OLD_IMPORT, NEW_IMPORT, 1)
print("imports OK")

# ── 2. Register routers ───────────────────────────────────────────────────────
OLD_INCLUDE = "app.include_router(whitelabel_router)"
NEW_INCLUDE = (OLD_INCLUDE +
    "\napp.include_router(appt_types_router)"
    "\napp.include_router(holidays_router)")
assert OLD_INCLUDE in content, "include_router anchor not found"
content = content.replace(OLD_INCLUDE, NEW_INCLUDE, 1)
print("include_router OK")

# ── 3. Phase 2 CSS ───────────────────────────────────────────────────────────
PHASE2_CSS = """
    /* phase-2 setup */
    .apt-card { background:#F9FAFB;border:1px solid #E5E7EB;border-radius:10px;
                padding:12px 16px;display:flex;align-items:center;justify-content:space-between; }
    .apt-card-name { font-weight:700;font-size:14px;color:#1F2937; }
    .apt-card-sub  { font-size:12px;color:#6B7280;margin-top:2px; }
    .hol-tag { background:#FEF2F2;color:#DC2626;border:1px solid #FCA5A5;
               border-radius:20px;padding:4px 12px;font-size:12px;font-weight:600;
               display:inline-flex;align-items:center;gap:6px;margin:4px; }
    .hol-tag button { background:none;border:none;color:#DC2626;cursor:pointer;
                      font-size:14px;line-height:1;padding:0; }
    .toggle-row { display:flex;align-items:center;justify-content:space-between;
                  padding:10px 0;border-bottom:1px solid #F3F4F6; }
    .toggle-row:last-child { border-bottom:none; }
    .toggle-lbl { font-size:13px;color:#374151;font-weight:500; }
    .toggle-sub  { font-size:11px;color:#9CA3AF;margin-top:2px; }
    .toggle-sw { position:relative;width:44px;height:24px; }
    .toggle-sw input { opacity:0;width:0;height:0; }
    .toggle-sw .slider { position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;
                         background:#D1D5DB;border-radius:24px;transition:.2s; }
    .toggle-sw .slider:before { position:absolute;content:"";height:18px;width:18px;
                                 left:3px;bottom:3px;background:#fff;border-radius:50%;
                                 transition:.2s; }
    .toggle-sw input:checked + .slider { background:#1E40AF; }
    .toggle-sw input:checked + .slider:before { transform:translateX(20px); }
"""
CSS_ANCHOR = "  </style>"
pos = content.find(CSS_ANCHOR)
assert pos != -1, "CSS anchor not found"
content = content[:pos] + PHASE2_CSS + "\n" + content[pos:]
print("CSS OK")

# ── 4. Phase 2 HTML (inject before /tab-setup closing) ───────────────────────
PHASE2_HTML = """
      <!-- Section 5: Appointment Types -->
      <div class="share-card" style="margin-top:14px;">
        <h3 style="margin:0 0 6px;font-size:15px;color:#1E40AF;">Visit Types &amp; Durations</h3>
        <p style="color:#6B7280;font-size:12px;margin:0 0 14px;">
          Define the types of appointments you offer. Aria will list these when patients ask what visits are available.
        </p>
        <div id="apt-list" style="display:flex;flex-direction:column;gap:10px;margin-bottom:14px;"></div>
        <button onclick="showAddAptType()"
          style="background:#EFF6FF;color:#1E40AF;border:1px solid #BFDBFE;border-radius:8px;
                 padding:8px 16px;font-size:13px;font-weight:600;cursor:pointer;">
          + Add Visit Type
        </button>
        <div id="apt-form" style="display:none;margin-top:16px;background:#F9FAFB;
             border:1px solid #E5E7EB;border-radius:10px;padding:16px;">
          <h4 style="margin:0 0 12px;font-size:14px;color:#374151;" id="apt-form-title">Add Visit Type</h4>
          <input type="hidden" id="af-id" value=""/>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div><label class="setup-lbl">Visit Name *</label>
                 <input id="af-name" type="text" class="setup-inp" placeholder="New Patient Visit"/></div>
            <div><label class="setup-lbl">Duration</label>
                 <select id="af-duration" class="setup-inp">
                   <option value="15">15 minutes</option>
                   <option value="30" selected>30 minutes</option>
                   <option value="45">45 minutes</option>
                   <option value="60">60 minutes</option>
                   <option value="90">90 minutes</option>
                 </select></div>
          </div>
          <div style="margin-top:10px;">
            <label class="setup-lbl">Description (optional)</label>
            <textarea id="af-desc" class="setup-inp" rows="2"
              placeholder="First-time visit includes full medical history review"></textarea>
          </div>
          <div style="margin-top:12px;display:flex;gap:10px;justify-content:flex-end;">
            <button onclick="cancelAptForm()"
              style="background:#F3F4F6;color:#374151;border:1px solid #D1D5DB;
                     border-radius:8px;padding:8px 16px;font-size:13px;cursor:pointer;">Cancel</button>
            <button onclick="saveAptType()" class="setup-save-btn">Save Visit Type</button>
          </div>
          <span id="af-msg" class="setup-msg" style="display:block;margin-top:8px;text-align:right;"></span>
        </div>
      </div>

      <!-- Section 6: Blocked Dates / Holidays -->
      <div class="share-card" style="margin-top:14px;">
        <h3 style="margin:0 0 6px;font-size:15px;color:#1E40AF;">Closed Dates &amp; Holidays</h3>
        <p style="color:#6B7280;font-size:12px;margin:0 0 14px;">
          Add dates when your clinic is closed. Aria will never offer slots on these days.
        </p>
        <div style="display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap;margin-bottom:12px;">
          <div>
            <label class="setup-lbl">Date (YYYY-MM-DD)</label>
            <input id="hol-date" type="date" class="setup-inp" style="width:180px;"/>
          </div>
          <div>
            <label class="setup-lbl">Reason (optional)</label>
            <input id="hol-reason" type="text" class="setup-inp" style="width:220px;"
              placeholder="Independence Day"/>
          </div>
          <button onclick="addHoliday()" class="setup-save-btn" style="margin-bottom:1px;">
            + Block Date
          </button>
          <span id="hol-msg" class="setup-msg"></span>
        </div>
        <div id="hol-tags" style="display:flex;flex-wrap:wrap;gap:4px;min-height:32px;
             background:#F9FAFB;border:1px solid #E5E7EB;border-radius:8px;padding:8px;"></div>
      </div>

      <!-- Section 7: Notification Preferences -->
      <div class="share-card" style="margin-top:14px;margin-bottom:4px;">
        <h3 style="margin:0 0 6px;font-size:15px;color:#1E40AF;">Notification Preferences</h3>
        <p style="color:#6B7280;font-size:12px;margin:0 0 14px;">
          Control which automated reminders Aria sends to patients. (Growth and Enterprise plans only.)
        </p>
        <div class="toggle-row">
          <div>
            <div class="toggle-lbl">72-hour reminder</div>
            <div class="toggle-sub">Sent 3 days before the appointment</div>
          </div>
          <label class="toggle-sw">
            <input type="checkbox" id="notif-72h" checked onchange="saveNotifPrefs()">
            <span class="slider"></span>
          </label>
        </div>
        <div class="toggle-row">
          <div>
            <div class="toggle-lbl">24-hour reminder</div>
            <div class="toggle-sub">Sent 1 day before the appointment</div>
          </div>
          <label class="toggle-sw">
            <input type="checkbox" id="notif-24h" checked onchange="saveNotifPrefs()">
            <span class="slider"></span>
          </label>
        </div>
        <div style="margin-top:14px;">
          <label class="setup-lbl">Custom Booking Confirmation Message (optional)</label>
          <textarea id="notif-confirm" class="setup-inp" rows="3"
            placeholder="Thank you for booking with us! We look forward to seeing you. Please arrive 10 minutes early and bring your insurance card and photo ID."></textarea>
          <p style="font-size:11px;color:#9CA3AF;margin:4px 0 0;">
            This message is appended to every booking confirmation email. Leave blank to use the default.
          </p>
        </div>
        <div style="margin-top:14px;text-align:right;">
          <button class="setup-save-btn" onclick="saveNotifPrefs()">Save Notification Settings</button>
          <span id="s-notif-msg" class="setup-msg"></span>
        </div>
      </div>
"""

HTML_ANCHOR = "    </div><!-- /tab-setup -->"
assert HTML_ANCHOR in content, "phase2 HTML anchor not found"
content = content.replace(HTML_ANCHOR, PHASE2_HTML + "\n" + HTML_ANCHOR, 1)
print("HTML OK")

# ── 5. Phase 2 JS ─────────────────────────────────────────────────────────────
PHASE2_JS = r"""
// ========== Phase 2: Appointment Types ==========

function loadAptTypes() {{
  var token = localStorage.getItem(TKEY);
  fetch("/api/"+SLUG+"/appointment-types",{{headers:{{"X-Clinic-Token":token}}}})
  .then(function(r){{return r.json();}})
  .then(function(d){{
    var list = document.getElementById("apt-list");
    if (!list) return;
    var types = d.appointment_types||[];
    if (!types.length){{
      list.innerHTML='<p style="font-size:13px;color:#9CA3AF;">No visit types yet. Click + Add below.</p>';
      return;
    }}
    list.innerHTML = types.map(function(t){{
      return '<div class="apt-card">'+
        '<div><div class="apt-card-name">'+_xe(t.name)+'</div>'+
        '<div class="apt-card-sub">'+t.duration_minutes+' min'+(t.description?' &bull; '+_xe(t.description):'')+'</div></div>'+
        '<div style="display:flex;gap:8px;">'+
          '<button onclick="editAptType('+t.id+')" style="background:#EFF6FF;color:#1E40AF;border:1px solid #BFDBFE;border-radius:6px;padding:5px 12px;font-size:12px;cursor:pointer;">Edit</button>'+
          '<button onclick="deleteAptType('+t.id+',\''+_xe(t.name)+'\')" style="background:#FEF2F2;color:#DC2626;border:1px solid #FCA5A5;border-radius:6px;padding:5px 12px;font-size:12px;cursor:pointer;">Remove</button>'+
        '</div></div>';
    }}).join("");
  }});
}}

function showAddAptType() {{
  document.getElementById("apt-form-title").textContent="Add Visit Type";
  document.getElementById("af-id").value="";
  document.getElementById("af-name").value="";
  document.getElementById("af-duration").value="30";
  document.getElementById("af-desc").value="";
  document.getElementById("af-msg").textContent="";
  document.getElementById("apt-form").style.display="block";
}}

function editAptType(id) {{
  var token=localStorage.getItem(TKEY);
  fetch("/api/"+SLUG+"/appointment-types",{{headers:{{"X-Clinic-Token":token}}}})
  .then(function(r){{return r.json();}})
  .then(function(d){{
    var t=(d.appointment_types||[]).find(function(x){{return x.id===id;}});
    if (!t) return;
    document.getElementById("apt-form-title").textContent="Edit Visit Type";
    document.getElementById("af-id").value=t.id;
    document.getElementById("af-name").value=t.name;
    document.getElementById("af-duration").value=t.duration_minutes||"30";
    document.getElementById("af-desc").value=t.description||"";
    document.getElementById("af-msg").textContent="";
    document.getElementById("apt-form").style.display="block";
    document.getElementById("apt-form").scrollIntoView({{behavior:"smooth",block:"nearest"}});
  }});
}}

function cancelAptForm(){{ document.getElementById("apt-form").style.display="none"; }}

function saveAptType() {{
  var token=localStorage.getItem(TKEY), id=document.getElementById("af-id").value;
  var name=(document.getElementById("af-name").value||"").trim();
  if (!name){{_showMsg("af-msg","Name is required.",false);return;}}
  var data={{
    name:name,
    duration_minutes:parseInt(document.getElementById("af-duration").value)||30,
    description:(document.getElementById("af-desc").value||"").trim()
  }};
  fetch(id?"/api/"+SLUG+"/appointment-types/"+id:"/api/"+SLUG+"/appointment-types",{{
    method:id?"PATCH":"POST",
    headers:{{"Content-Type":"application/json","X-Clinic-Token":token}},
    body:JSON.stringify(data)
  }})
  .then(function(r){{return r.json();}})
  .then(function(d){{
    if (d.error){{_showMsg("af-msg","Error: "+d.error,false);return;}}
    document.getElementById("apt-form").style.display="none";
    loadAptTypes();
  }}).catch(function(){{_showMsg("af-msg","Network error",false);}});
}}

function deleteAptType(id,name) {{
  if (!confirm("Remove visit type: "+name+"?")) return;
  var token=localStorage.getItem(TKEY);
  fetch("/api/"+SLUG+"/appointment-types/"+id,{{method:"DELETE",headers:{{"X-Clinic-Token":token}}}})
  .then(function(r){{return r.json();}})
  .then(function(){{loadAptTypes();}});
}}

// ========== Phase 2: Holidays ==========

var _holidays = [];

function loadHolidays() {{
  var token=localStorage.getItem(TKEY);
  fetch("/api/"+SLUG+"/holidays",{{headers:{{"X-Clinic-Token":token}}}})
  .then(function(r){{return r.json();}})
  .then(function(d){{
    _holidays = d.holidays||[];
    _renderHolTags();
  }});
}}

function _renderHolTags() {{
  var el=document.getElementById("hol-tags");
  if (!el) return;
  if (!_holidays.length){{el.innerHTML='<span style="font-size:12px;color:#9CA3AF;">No blocked dates yet.</span>';return;}}
  el.innerHTML=_holidays.map(function(h){{
    return '<span class="hol-tag">'+h.date+(h.reason?' &mdash; '+_xe(h.reason):'')+
           '<button onclick="deleteHoliday('+h.id+')">&#xd7;</button></span>';
  }}).join("");
}}

function addHoliday() {{
  var token=localStorage.getItem(TKEY);
  var date=(document.getElementById("hol-date").value||"").trim();
  var reason=(document.getElementById("hol-reason").value||"").trim();
  if (!date){{_showMsg("hol-msg","Pick a date first.",false);return;}}
  fetch("/api/"+SLUG+"/holidays",{{
    method:"POST",
    headers:{{"Content-Type":"application/json","X-Clinic-Token":token}},
    body:JSON.stringify({{date:date,reason:reason}})
  }})
  .then(function(r){{return r.json();}})
  .then(function(d){{
    if (d.error){{_showMsg("hol-msg",d.error,false);return;}}
    document.getElementById("hol-date").value="";
    document.getElementById("hol-reason").value="";
    _showMsg("hol-msg","Date blocked.",true);
    loadHolidays();
  }}).catch(function(){{_showMsg("hol-msg","Network error",false);}});
}}

function deleteHoliday(id) {{
  var token=localStorage.getItem(TKEY);
  fetch("/api/"+SLUG+"/holidays/"+id,{{method:"DELETE",headers:{{"X-Clinic-Token":token}}}})
  .then(function(r){{return r.json();}})
  .then(function(){{loadHolidays();}});
}}

// ========== Phase 2: Notification Preferences ==========

function loadNotifPrefs(p) {{
  var cb72=document.getElementById("notif-72h");
  var cb24=document.getElementById("notif-24h");
  var conf=document.getElementById("notif-confirm");
  if (cb72) cb72.checked = p.reminder_72h_enabled !== false;
  if (cb24) cb24.checked = p.reminder_24h_enabled !== false;
  if (conf) conf.value = p.custom_confirmation_msg || "";
}}

function saveNotifPrefs() {{
  var token=localStorage.getItem(TKEY);
  var body={{
    reminder_72h_enabled: document.getElementById("notif-72h").checked,
    reminder_24h_enabled: document.getElementById("notif-24h").checked,
    custom_confirmation_msg: (document.getElementById("notif-confirm").value||"").trim()
  }};
  fetch("/api/"+SLUG+"/profile",{{
    method:"PATCH",
    headers:{{"Content-Type":"application/json","X-Clinic-Token":token}},
    body:JSON.stringify(body)
  }})
  .then(function(r){{return r.json();}})
  .then(function(d){{
    if (!d.error) _showMsg("s-notif-msg","Saved!",true);
    else _showMsg("s-notif-msg","Error: "+d.error,false);
  }}).catch(function(){{_showMsg("s-notif-msg","Network error",false);}});
}}

"""

JS_ANCHOR = "function switchTab(name, btn) {{"
assert JS_ANCHOR in content, "phase2 JS anchor not found"
content = content.replace(JS_ANCHOR, PHASE2_JS + JS_ANCHOR, 1)
print("JS OK")

# ── 6. Wire phase-2 loaders into loadSetup() ─────────────────────────────────
# loadProviders() call is the last line of loadSetup(); replace globally (appears once)
OLD_LOADSETUP_TAIL = "  loadProviders();\n}}\n\nfunction _sv"
NEW_LOADSETUP_TAIL = "  loadProviders();\n  loadAptTypes();\n  loadHolidays();\n}}\n\nfunction _sv"
assert OLD_LOADSETUP_TAIL in content, "loadSetup tail not found"
content = content.replace(OLD_LOADSETUP_TAIL, NEW_LOADSETUP_TAIL, 1)
print("loadSetup wired")

# ── 7. Wire notif prefs into profile load ─────────────────────────────────────
# Find the .then(function(p) {{ ... }}) block in loadSetup that calls _sv(...)
# and add loadNotifPrefs(p) call at the end of it
OLD_NOTIF_HOOK = "    _buildInsChk(p.insurance_accepted || \"\");\n  }});"
NEW_NOTIF_HOOK = "    _buildInsChk(p.insurance_accepted || \"\");\n    loadNotifPrefs(p);\n  }});"
assert OLD_NOTIF_HOOK in content, "notif hook anchor not found"
content = content.replace(OLD_NOTIF_HOOK, NEW_NOTIF_HOOK, 1)
print("notif hook wired")

with open("backend/main.py", "w", encoding="utf-8") as f:
    f.write(content)
print("DONE")
