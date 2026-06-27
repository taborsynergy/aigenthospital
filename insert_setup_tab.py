"""One-shot script to inject the Clinic Setup tab CSS+HTML+JS into the portal."""
import sys
sys.stdout.reconfigure(encoding="utf-8")

with open("backend/main.py", "r", encoding="utf-8") as f:
    content = f.read()

# Sanity-check nothing already inserted
if "tab-setup" in content:
    print("SKIP: tab-setup already present.")
    sys.exit(0)

# ── 1. CSS ────────────────────────────────────────────────────────────────────
SETUP_CSS = """
    /* setup tab */
    .setup-lbl { display:block;font-size:12px;font-weight:600;color:#374151;margin-bottom:4px; }
    .setup-inp { width:100%;padding:9px 12px;border:1px solid #E5E7EB;border-radius:8px;
                 font-size:13px;outline:none;box-sizing:border-box;background:#fff; }
    .setup-inp:focus { border-color:#1E40AF; }
    textarea.setup-inp { resize:vertical;font-family:inherit; }
    .setup-save-btn { background:#1E40AF;color:#fff;border:none;border-radius:8px;
                      padding:9px 20px;font-size:13px;font-weight:600;cursor:pointer; }
    .setup-save-btn:hover { background:#1E3A8A; }
    .setup-msg { font-size:12px;margin-left:10px;font-weight:600; }
    .setup-msg.ok  { color:#059669; }
    .setup-msg.err { color:#DC2626; }
    .provider-card { background:#F9FAFB;border:1px solid #E5E7EB;border-radius:10px;
                     padding:12px 16px;display:flex;align-items:center;justify-content:space-between; }
    .provider-card-name { font-weight:700;font-size:14px;color:#1F2937; }
    .provider-card-sub  { font-size:12px;color:#6B7280;margin-top:2px; }
    .hours-row { display:flex;align-items:center;gap:12px;flex-wrap:wrap; }
    .hours-row .day-lbl { font-size:13px;color:#374151;font-weight:500;width:90px; }
    .ins-check { display:flex;align-items:center;gap:7px;font-size:13px;color:#374151;
                 background:#F9FAFB;border:1px solid #E5E7EB;border-radius:8px;
                 padding:8px 10px;cursor:pointer; }
    .ins-check input { cursor:pointer; }
"""

CSS_ANCHOR = "  </style>"
first_style_pos = content.find(CSS_ANCHOR)
assert first_style_pos != -1, "CSS anchor not found"
content = content[:first_style_pos] + SETUP_CSS + "\n" + content[first_style_pos:]
print("CSS OK:", ".setup-lbl" in content)

# ── 2. HTML panel ─────────────────────────────────────────────────────────────
SETUP_HTML = """
    <!-- TAB: Clinic Setup -->
    <div id="tab-setup" class="tab-panel">
      <div class="share-card">
        <h2 style="margin-bottom:4px;">&#9881;&#65039; Clinic Setup</h2>
        <p style="color:#6B7280;font-size:13px;margin:0;">
          Everything Aria needs to book appointments, answer questions, and send reminders correctly.
          Fill in each section and hit Save &mdash; changes take effect immediately.
        </p>
      </div>

      <!-- Section 1: Practice Info -->
      <div class="share-card" style="margin-top:14px;">
        <h3 style="margin:0 0 16px;font-size:15px;color:#1E40AF;">Practice Information</h3>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
          <div><label class="setup-lbl">Practice Name</label>
               <input id="s-name" type="text" class="setup-inp" placeholder="Sunrise Pediatrics"/></div>
          <div><label class="setup-lbl">Specialty</label>
               <input id="s-specialty" type="text" class="setup-inp" placeholder="Pediatrics"/></div>
          <div><label class="setup-lbl">Street Address</label>
               <input id="s-address" type="text" class="setup-inp" placeholder="123 Main St, Suite 4"/></div>
          <div><label class="setup-lbl">City, State</label>
               <input id="s-city" type="text" class="setup-inp" placeholder="Miami, FL"/></div>
          <div><label class="setup-lbl">Phone</label>
               <input id="s-phone" type="text" class="setup-inp" placeholder="305-555-0100"/></div>
          <div><label class="setup-lbl">Website</label>
               <input id="s-website" type="text" class="setup-inp" placeholder="https://example.com"/></div>
          <div><label class="setup-lbl">Timezone</label>
               <select id="s-timezone" class="setup-inp">
                 <option value="US/Eastern">US/Eastern (ET)</option>
                 <option value="US/Central">US/Central (CT)</option>
                 <option value="US/Mountain">US/Mountain (MT)</option>
                 <option value="US/Pacific">US/Pacific (PT)</option>
                 <option value="US/Arizona">US/Arizona (MST, no DST)</option>
                 <option value="US/Hawaii">US/Hawaii (HST)</option>
                 <option value="US/Alaska">US/Alaska (AKT)</option>
               </select></div>
          <div><label class="setup-lbl">AI Assistant Name</label>
               <input id="s-agent" type="text" class="setup-inp" placeholder="Aria"/></div>
        </div>
        <div style="margin-top:14px;">
          <label class="setup-lbl">After-Hours Message</label>
          <textarea id="s-afterhours" class="setup-inp" rows="2"
            placeholder="Our office is closed. For emergencies call 911. We re-open Monday 8am."></textarea>
        </div>
        <div style="margin-top:10px;">
          <label class="setup-lbl">Cancellation Policy</label>
          <textarea id="s-cancellation" class="setup-inp" rows="2"
            placeholder="Please cancel at least 24 hours in advance to avoid a $50 fee."></textarea>
        </div>
        <div style="margin-top:10px;">
          <label class="setup-lbl">Services Offered (comma-separated)</label>
          <textarea id="s-services" class="setup-inp" rows="2"
            placeholder="Well-child visits, vaccinations, sick visits, sports physicals"></textarea>
        </div>
        <div style="margin-top:10px;">
          <label class="setup-lbl">HIPAA Identity Verification Method</label>
          <input id="s-hipaa" type="text" class="setup-inp"
            placeholder="Full name + date of birth + last 4 of SSN"/>
        </div>
        <div style="margin-top:10px;">
          <label class="setup-lbl">Escalation Contact</label>
          <input id="s-escalation" type="text" class="setup-inp"
            placeholder="Dr. Kim: 305-555-0911 | admin@clinic.com"/>
        </div>
        <div style="margin-top:16px;text-align:right;">
          <button class="setup-save-btn" onclick="savePracticeInfo()">Save Practice Info</button>
          <span id="s-info-msg" class="setup-msg"></span>
        </div>
      </div>

      <!-- Section 2: Office Hours -->
      <div class="share-card" style="margin-top:14px;">
        <h3 style="margin:0 0 6px;font-size:15px;color:#1E40AF;">Office Hours &amp; Scheduling</h3>
        <p style="color:#6B7280;font-size:12px;margin:0 0 16px;">
          Check each day your practice is open and set your hours.
        </p>
        <div id="hours-grid" style="display:flex;flex-direction:column;gap:10px;"></div>
        <div style="margin-top:14px;display:flex;align-items:center;gap:8px;">
          <label class="setup-lbl" style="margin:0;white-space:nowrap;">Default Slot Duration:</label>
          <select id="s-slot-duration" class="setup-inp" style="width:160px;">
            <option value="15">15 minutes</option>
            <option value="30" selected>30 minutes</option>
            <option value="45">45 minutes</option>
            <option value="60">60 minutes</option>
          </select>
        </div>
        <div style="margin-top:16px;text-align:right;">
          <button class="setup-save-btn" onclick="saveOfficeHours()">Save Office Hours</button>
          <span id="s-hours-msg" class="setup-msg"></span>
        </div>
      </div>

      <!-- Section 3: Providers -->
      <div class="share-card" style="margin-top:14px;">
        <h3 style="margin:0 0 6px;font-size:15px;color:#1E40AF;">Doctors / Providers</h3>
        <p style="color:#6B7280;font-size:12px;margin:0 0 14px;">
          Add each doctor in your practice. Aria will let patients request a specific provider.
        </p>
        <div id="providers-list" style="display:flex;flex-direction:column;gap:10px;margin-bottom:14px;"></div>
        <button onclick="showAddProvider()"
          style="background:#EFF6FF;color:#1E40AF;border:1px solid #BFDBFE;border-radius:8px;
                 padding:8px 16px;font-size:13px;font-weight:600;cursor:pointer;">
          + Add Doctor / Provider
        </button>
        <div id="provider-form" style="display:none;margin-top:16px;background:#F9FAFB;
             border:1px solid #E5E7EB;border-radius:10px;padding:16px;">
          <h4 style="margin:0 0 12px;font-size:14px;color:#374151;" id="provider-form-title">Add Provider</h4>
          <input type="hidden" id="pf-id" value=""/>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div><label class="setup-lbl">Full Name *</label>
                 <input id="pf-name" type="text" class="setup-inp" placeholder="Dr. Sarah Kim"/></div>
            <div><label class="setup-lbl">Specialty</label>
                 <input id="pf-specialty" type="text" class="setup-inp" placeholder="Pediatrics"/></div>
            <div><label class="setup-lbl">Email</label>
                 <input id="pf-email" type="email" class="setup-inp" placeholder="dr.kim@clinic.com"/></div>
            <div><label class="setup-lbl">Phone</label>
                 <input id="pf-phone" type="text" class="setup-inp" placeholder="305-555-0101"/></div>
            <div><label class="setup-lbl">NPI Number</label>
                 <input id="pf-npi" type="text" class="setup-inp" placeholder="1234567890"/></div>
            <div><label class="setup-lbl">License Number</label>
                 <input id="pf-license" type="text" class="setup-inp" placeholder="FL-MD-12345"/></div>
          </div>
          <div style="margin-top:10px;">
            <label class="setup-lbl">Bio / Credentials</label>
            <textarea id="pf-bio" class="setup-inp" rows="2"
              placeholder="Board-certified, 15 years experience"></textarea>
          </div>
          <div style="margin-top:12px;display:flex;gap:10px;justify-content:flex-end;">
            <button onclick="cancelProviderForm()"
              style="background:#F3F4F6;color:#374151;border:1px solid #D1D5DB;
                     border-radius:8px;padding:8px 16px;font-size:13px;cursor:pointer;">Cancel</button>
            <button onclick="saveProvider()" class="setup-save-btn">Save Provider</button>
          </div>
          <span id="pf-msg" class="setup-msg" style="display:block;margin-top:8px;text-align:right;"></span>
        </div>
      </div>

      <!-- Section 4: Insurance -->
      <div class="share-card" style="margin-top:14px;margin-bottom:4px;">
        <h3 style="margin:0 0 6px;font-size:15px;color:#1E40AF;">Insurance Accepted</h3>
        <p style="color:#6B7280;font-size:12px;margin:0 0 14px;">
          Check all plans you accept. Aria will tell patients which are covered.
        </p>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:14px;"
             id="insurance-checkboxes"></div>
        <div>
          <label class="setup-lbl">Additional Notes (copay amounts, self-pay rates, etc.)</label>
          <textarea id="s-insurance-extra" class="setup-inp" rows="2"
            placeholder="Aetna copay $25. Self-pay sliding scale $50-150."></textarea>
        </div>
        <div style="margin-top:16px;text-align:right;">
          <button class="setup-save-btn" onclick="saveInsurance()">Save Insurance</button>
          <span id="s-ins-msg" class="setup-msg"></span>
        </div>
      </div>

    </div><!-- /tab-setup -->
"""

HTML_ANCHOR = "  </div><!-- /dash-body -->"
assert HTML_ANCHOR in content, "HTML anchor not found"
content = content.replace(HTML_ANCHOR, SETUP_HTML + "\n" + HTML_ANCHOR, 1)
print("HTML OK:", "tab-setup" in content)

# ── 3. JS ─────────────────────────────────────────────────────────────────────
# Inside main.py's Python f-string, {{ renders as { and }} renders as }
# So all JS curly braces must be doubled.
SETUP_JS = r"""
// ========== Clinic Setup tab ==========

var _DAYS = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"];
var _INS_LIST = [
  "Aetna","Anthem / BCBS","Cigna","UnitedHealthcare","Humana",
  "Medicare","Medicaid","Tricare","Molina","CareSource",
  "WellCare","Ambetter","Oscar Health","Kaiser","Self-Pay / Cash"
];

function loadSetup() {{
  var token = localStorage.getItem(TKEY);
  fetch("/api/" + SLUG + "/profile", {{headers: {{"X-Clinic-Token": token}}}})
  .then(function(r) {{ return r.json(); }})
  .then(function(p) {{
    _sv("s-name",         p.name || "");
    _sv("s-specialty",    p.specialty || "");
    _sv("s-address",      p.address || "");
    _sv("s-city",         p.city_state || "");
    _sv("s-phone",        p.phone || "");
    _sv("s-website",      p.website || "");
    _sv("s-agent",        p.agent_name || "Aria");
    _sv("s-afterhours",   p.after_hours_protocol || "");
    _sv("s-cancellation", p.cancellation_policy || "");
    _sv("s-services",     p.services_offered || "");
    _sv("s-hipaa",        p.hipaa_verify_method || "");
    _sv("s-escalation",   p.escalation_contact || "");
    var tzEl = document.getElementById("s-timezone");
    if (tzEl && p.timezone) tzEl.value = p.timezone;
    _buildHoursGrid(p.office_hours || "Mon-Fri 8am-5pm");
    _buildInsChk(p.insurance_accepted || "");
  }});
  loadProviders();
}}

function _sv(id, val) {{
  var el = document.getElementById(id);
  if (el) el.value = val;
}}

function _showMsg(id, text, ok) {{
  var el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.className = "setup-msg " + (ok ? "ok" : "err");
  setTimeout(function() {{ el.textContent = ""; el.className = "setup-msg"; }}, 3500);
}}

function savePracticeInfo() {{
  var token = localStorage.getItem(TKEY);
  var body = {{
    name:                 (document.getElementById("s-name").value||"").trim() || undefined,
    specialty:            (document.getElementById("s-specialty").value||"").trim() || undefined,
    address:              (document.getElementById("s-address").value||"").trim() || undefined,
    city_state:           (document.getElementById("s-city").value||"").trim() || undefined,
    phone:                (document.getElementById("s-phone").value||"").trim() || undefined,
    website:              (document.getElementById("s-website").value||"").trim() || undefined,
    timezone:             document.getElementById("s-timezone").value || undefined,
    agent_name:           (document.getElementById("s-agent").value||"").trim() || undefined,
    after_hours_protocol: (document.getElementById("s-afterhours").value||"").trim() || undefined,
    cancellation_policy:  (document.getElementById("s-cancellation").value||"").trim() || undefined,
    services_offered:     (document.getElementById("s-services").value||"").trim() || undefined,
    hipaa_verify_method:  (document.getElementById("s-hipaa").value||"").trim() || undefined,
    escalation_contact:   (document.getElementById("s-escalation").value||"").trim() || undefined
  }};
  Object.keys(body).forEach(function(k) {{ if (body[k] === undefined) delete body[k]; }});
  fetch("/api/" + SLUG + "/profile", {{
    method: "PATCH",
    headers: {{"Content-Type": "application/json", "X-Clinic-Token": token}},
    body: JSON.stringify(body)
  }})
  .then(function(r) {{ return r.json(); }})
  .then(function(d) {{
    if (!d.error) _showMsg("s-info-msg", "Saved! Aria will use these immediately.", true);
    else _showMsg("s-info-msg", "Error: " + d.error, false);
  }})
  .catch(function() {{ _showMsg("s-info-msg", "Network error", false); }});
}}

function _buildHoursGrid(hoursStr) {{
  var parsed = _parseHours(hoursStr);
  var container = document.getElementById("hours-grid");
  if (!container) return;
  container.innerHTML = "";
  _DAYS.forEach(function(day) {{
    var info = parsed[day] || {{open: false, start: "08:00", end: "17:00"}};
    var row = document.createElement("div");
    row.className = "hours-row";
    row.innerHTML =
      '<input type="checkbox" id="h-chk-' + day + '"' + (info.open ? " checked" : "") +
      ' onchange="toggleDayRow(this,\'' + day + '\')">' +
      '<label class="day-lbl" for="h-chk-' + day + '">' + day + '</label>' +
      '<input type="time" id="h-s-' + day + '" value="' + info.start + '" class="setup-inp" style="width:120px;"' +
      (info.open ? "" : " disabled") + '>' +
      '<span style="font-size:13px;color:#6B7280;">to</span>' +
      '<input type="time" id="h-e-' + day + '" value="' + info.end + '" class="setup-inp" style="width:120px;"' +
      (info.open ? "" : " disabled") + '>';
    container.appendChild(row);
  }});
}}

function toggleDayRow(chk, day) {{
  document.getElementById("h-s-" + day).disabled = !chk.checked;
  document.getElementById("h-e-" + day).disabled = !chk.checked;
}}

function _parseHours(s) {{
  var result = {{}};
  var shorts = {{mon:"Monday",tue:"Tuesday",wed:"Wednesday",thu:"Thursday",
                 fri:"Friday",sat:"Saturday",sun:"Sunday"}};
  var fulls  = {{monday:"Monday",tuesday:"Tuesday",wednesday:"Wednesday",
                 thursday:"Thursday",friday:"Friday",saturday:"Saturday",sunday:"Sunday"}};
  function toFull(d) {{ d = d.toLowerCase().trim(); return shorts[d] || fulls[d] || null; }}
  function toTime(t) {{
    t = t.toLowerCase().trim();
    var pm = t.indexOf("pm") >= 0, am = t.indexOf("am") >= 0;
    t = t.replace(/[apm]/g, "");
    var h = t.indexOf(":") >= 0 ? parseInt(t.split(":")[0]) : parseInt(t);
    if (pm && h < 12) h += 12; if (am && h === 12) h = 0;
    return (h < 10 ? "0" : "") + h + ":00";
  }}
  s.split(",").forEach(function(seg) {{
    seg = seg.trim();
    var m = seg.match(/^([A-Za-z]+)[ -]+([A-Za-z]+) +(\S+) *- *(\S+)$/);
    if (m) {{
      var s1 = toFull(m[1]), s2 = toFull(m[2]);
      if (!s1 || !s2) return;
      _DAYS.slice(_DAYS.indexOf(s1), _DAYS.indexOf(s2)+1).forEach(function(d) {{
        result[d] = {{open:true,start:toTime(m[3]),end:toTime(m[4])}};
      }});
      return;
    }}
    var m2 = seg.match(/^([A-Za-z]+) +(\S+) *- *(\S+)$/);
    if (m2) {{ var d = toFull(m2[1]); if (d) result[d] = {{open:true,start:toTime(m2[2]),end:toTime(m2[3])}}; }}
  }});
  return result;
}}

function _hoursToStr() {{
  var parts = [], sh = {{Monday:"Mon",Tuesday:"Tue",Wednesday:"Wed",Thursday:"Thu",
                          Friday:"Fri",Saturday:"Sat",Sunday:"Sun"}};
  var prev = null, gs = null;
  function flush(upTo) {{
    if (!prev||!gs) return;
    var si = _DAYS.indexOf(gs), ei = _DAYS.indexOf(upTo);
    var t = _h12(prev.s) + "-" + _h12(prev.e);
    parts.push(si===ei ? sh[gs]+" "+t : sh[gs]+"-"+sh[upTo]+" "+t);
  }}
  _DAYS.forEach(function(day, i) {{
    var chk = document.getElementById("h-chk-" + day);
    if (!chk||!chk.checked) {{ flush(_DAYS[i-1]); prev=null; gs=null; return; }}
    var cur = {{s:document.getElementById("h-s-"+day).value, e:document.getElementById("h-e-"+day).value}};
    if (prev&&prev.s===cur.s&&prev.e===cur.e) {{ prev=cur; }}
    else {{ if (prev) flush(_DAYS[i-1]); gs=day; prev=cur; }}
    if (i===_DAYS.length-1) flush(day);
  }});
  return parts.join(", ");
}}

function _h12(t) {{
  var p=t.split(":"), h=parseInt(p[0]), m=parseInt(p[1]||0);
  var suf=h>=12?"pm":"am";
  if (h===0) h=12; else if (h>12) h-=12;
  return h+(m?":"+(m<10?"0":"")+m:"")+suf;
}}

function saveOfficeHours() {{
  var token = localStorage.getItem(TKEY);
  var str = _hoursToStr();
  if (!str) {{ _showMsg("s-hours-msg","Select at least one open day.",false); return; }}
  fetch("/api/"+SLUG+"/profile",{{
    method:"PATCH",
    headers:{{"Content-Type":"application/json","X-Clinic-Token":token}},
    body:JSON.stringify({{office_hours:str}})
  }})
  .then(function(r){{return r.json();}})
  .then(function(d){{
    if (!d.error) _showMsg("s-hours-msg","Saved: "+str,true);
    else _showMsg("s-hours-msg","Error: "+d.error,false);
  }}).catch(function(){{_showMsg("s-hours-msg","Network error",false);}});
}}

function loadProviders() {{
  var token = localStorage.getItem(TKEY);
  fetch("/api/"+SLUG+"/providers",{{headers:{{"X-Clinic-Token":token}}}})
  .then(function(r){{return r.json();}})
  .then(function(d){{
    var list = document.getElementById("providers-list");
    if (!list) return;
    var ps = d.providers||[];
    if (!ps.length) {{
      list.innerHTML='<p style="font-size:13px;color:#9CA3AF;">No providers yet. Click + Add below.</p>';
      return;
    }}
    list.innerHTML = ps.map(function(p) {{
      return '<div class="provider-card">'+
        '<div><div class="provider-card-name">'+_xe(p.name)+'</div>'+
        '<div class="provider-card-sub">'+(p.specialty?_xe(p.specialty):'')+(p.email?' &bull; '+_xe(p.email):'')+(p.npi_number?' &bull; NPI: '+_xe(p.npi_number):'')+'</div></div>'+
        '<div style="display:flex;gap:8px;">'+
          '<button onclick="editProvider('+p.id+')" style="background:#EFF6FF;color:#1E40AF;border:1px solid #BFDBFE;border-radius:6px;padding:5px 12px;font-size:12px;cursor:pointer;">Edit</button>'+
          '<button onclick="deleteProvider('+p.id+',\''+_xe(p.name)+'\')" style="background:#FEF2F2;color:#DC2626;border:1px solid #FCA5A5;border-radius:6px;padding:5px 12px;font-size:12px;cursor:pointer;">Remove</button>'+
        '</div></div>';
    }}).join("");
  }});
}}

function _xe(s) {{
  return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}}

function showAddProvider() {{
  document.getElementById("provider-form-title").textContent="Add Provider";
  document.getElementById("pf-id").value="";
  ["pf-name","pf-specialty","pf-email","pf-phone","pf-npi","pf-license","pf-bio"]
    .forEach(function(id){{document.getElementById(id).value="";}});
  document.getElementById("pf-msg").textContent="";
  document.getElementById("provider-form").style.display="block";
}}

function editProvider(id) {{
  var token = localStorage.getItem(TKEY);
  fetch("/api/"+SLUG+"/providers/"+id,{{headers:{{"X-Clinic-Token":token}}}})
  .then(function(r){{return r.json();}})
  .then(function(p){{
    document.getElementById("provider-form-title").textContent="Edit Provider";
    document.getElementById("pf-id").value=p.id||"";
    document.getElementById("pf-name").value=p.name||"";
    document.getElementById("pf-specialty").value=p.specialty||"";
    document.getElementById("pf-email").value=p.email||"";
    document.getElementById("pf-phone").value=p.phone||"";
    document.getElementById("pf-npi").value=p.npi_number||"";
    document.getElementById("pf-license").value=p.license_number||"";
    document.getElementById("pf-bio").value=p.bio||"";
    document.getElementById("pf-msg").textContent="";
    document.getElementById("provider-form").style.display="block";
    document.getElementById("provider-form").scrollIntoView({{behavior:"smooth",block:"nearest"}});
  }});
}}

function cancelProviderForm() {{ document.getElementById("provider-form").style.display="none"; }}

function saveProvider() {{
  var token=localStorage.getItem(TKEY), id=document.getElementById("pf-id").value;
  var name=(document.getElementById("pf-name").value||"").trim();
  if (!name){{_showMsg("pf-msg","Name is required.",false);return;}}
  var data={{
    name:name,
    specialty:(document.getElementById("pf-specialty").value||"").trim(),
    email:(document.getElementById("pf-email").value||"").trim(),
    phone:(document.getElementById("pf-phone").value||"").trim(),
    npi_number:(document.getElementById("pf-npi").value||"").trim(),
    license_number:(document.getElementById("pf-license").value||"").trim(),
    bio:(document.getElementById("pf-bio").value||"").trim()
  }};
  fetch(id?"/api/"+SLUG+"/providers/"+id:"/api/"+SLUG+"/providers",{{
    method:id?"PATCH":"POST",
    headers:{{"Content-Type":"application/json","X-Clinic-Token":token}},
    body:JSON.stringify(data)
  }})
  .then(function(r){{return r.json();}})
  .then(function(d){{
    if (d.error){{_showMsg("pf-msg","Error: "+d.error,false);return;}}
    document.getElementById("provider-form").style.display="none";
    loadProviders(); _syncProviders();
  }}).catch(function(){{_showMsg("pf-msg","Network error",false);}});
}}

function deleteProvider(id,name) {{
  if (!confirm("Remove "+name+"?")) return;
  var token=localStorage.getItem(TKEY);
  fetch("/api/"+SLUG+"/providers/"+id,{{method:"DELETE",headers:{{"X-Clinic-Token":token}}}})
  .then(function(r){{return r.json();}})
  .then(function(){{loadProviders();_syncProviders();}});
}}

function _syncProviders() {{
  var token=localStorage.getItem(TKEY);
  fetch("/api/"+SLUG+"/providers",{{headers:{{"X-Clinic-Token":token}}}})
  .then(function(r){{return r.json();}})
  .then(function(d){{
    var names=(d.providers||[]).map(function(p){{return p.name;}}).join(", ");
    fetch("/api/"+SLUG+"/profile",{{
      method:"PATCH",
      headers:{{"Content-Type":"application/json","X-Clinic-Token":token}},
      body:JSON.stringify({{providers:names}})
    }});
  }});
}}

function _buildInsChk(existing) {{
  var el=document.getElementById("insurance-checkboxes");
  if (!el) return;
  var ex=existing.toLowerCase();
  el.innerHTML=_INS_LIST.map(function(ins){{
    var key=ins.replace(/[^a-z0-9]/gi,"_");
    var chk=ex.includes(ins.split(" ")[0].toLowerCase())?" checked":"";
    return '<label class="ins-check"><input type="checkbox" id="ins-'+key+'"'+chk+'> '+ins+'</label>';
  }}).join("");
}}

function saveInsurance() {{
  var token=localStorage.getItem(TKEY);
  var sel=_INS_LIST.filter(function(ins){{
    var el=document.getElementById("ins-"+ins.replace(/[^a-z0-9]/gi,"_"));
    return el&&el.checked;
  }});
  var extra=(document.getElementById("s-insurance-extra").value||"").trim();
  var combined=sel.join(", ")+(extra?". "+extra:"");
  fetch("/api/"+SLUG+"/profile",{{
    method:"PATCH",
    headers:{{"Content-Type":"application/json","X-Clinic-Token":token}},
    body:JSON.stringify({{insurance_accepted:combined}})
  }})
  .then(function(r){{return r.json();}})
  .then(function(d){{
    if (!d.error) _showMsg("s-ins-msg","Saved! Aria will reference this for patients.",true);
    else _showMsg("s-ins-msg","Error: "+d.error,false);
  }}).catch(function(){{_showMsg("s-ins-msg","Network error",false);}});
}}

"""

JS_ANCHOR = "function switchTab(name, btn) {{"
assert JS_ANCHOR in content, "JS anchor not found"
content = content.replace(JS_ANCHOR, SETUP_JS + JS_ANCHOR, 1)
print("JS OK:", "loadSetup" in content)

# ── 4. Wire loadSetup into switchTab ─────────────────────────────────────────
OLD_WIRE = '  if (name === "appts")      loadAppts();\n  if (name === "plan")       loadPlan();'
NEW_WIRE = '  if (name === "appts")      loadAppts();\n  if (name === "setup")      loadSetup();\n  if (name === "plan")       loadPlan();'
assert OLD_WIRE in content, "switchTab wire anchor not found"
content = content.replace(OLD_WIRE, NEW_WIRE, 1)
print("switchTab wired:", 'name === "setup"' in content)

with open("backend/main.py", "w", encoding="utf-8") as f:
    f.write(content)
print("DONE")
