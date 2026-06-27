"""
Patch the portal page JS to:
1. Check for ?token= in URL and auto-login (for post-signup redirect)
2. Show a clearer "wrong email/password" hint below the Sign In button
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('backend/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# ── Patch 1: Add ?token= URL param auto-login to the init IIFE ───────────────
# The current init block just checks localStorage; extend it to also check URL
OLD_INIT = """(function() {{
  var token = localStorage.getItem(TKEY);
  if (!token) return;
  fetch("/api/clinic-auth/verify", {{ headers: {{ "X-Clinic-Token": token }} }})
    .then(function(r) {{
      if (r.ok) {{ try {{ showDash(); }} catch(e) {{ localStorage.removeItem(TKEY); }} }}
      else {{ localStorage.removeItem(TKEY); }}
    }})
    .catch(function() {{ localStorage.removeItem(TKEY); }});
}})();"""

NEW_INIT = """(function() {{
  // Check URL ?token= first (set by signup redirect / password-reset link)
  var urlParams = new URLSearchParams(window.location.search);
  var urlToken  = urlParams.get("token");
  if (urlToken) {{
    localStorage.setItem(TKEY, urlToken);
    // Clean URL so token doesn't persist in browser history
    history.replaceState(null, "", window.location.pathname);
  }}

  var token = localStorage.getItem(TKEY);
  if (!token) return;
  fetch("/api/clinic-auth/verify", {{ headers: {{ "X-Clinic-Token": token }} }})
    .then(function(r) {{
      if (r.ok) {{ try {{ showDash(); }} catch(e) {{ localStorage.removeItem(TKEY); }} }}
      else {{ localStorage.removeItem(TKEY); }}
    }})
    .catch(function() {{ localStorage.removeItem(TKEY); }});
}})();"""

if OLD_INIT not in content:
    print("ERROR: init IIFE not found — check anchor string")
    sys.exit(1)

content = content.replace(OLD_INIT, NEW_INIT, 1)
print("✓ Patched: ?token= URL auto-login added to init IIFE")

# ── Patch 2: Improve login error visibility ───────────────────────────────────
# Add scroll-into-view so users always see the error even on small screens
OLD_LOGIN_ERR = """      err.textContent = msg; err.classList.add("show");
      return;"""

NEW_LOGIN_ERR = """      err.textContent = msg; err.classList.add("show");
      err.scrollIntoView({{ behavior: "smooth", block: "nearest" }});
      return;"""

if OLD_LOGIN_ERR not in content:
    print("WARNING: login error anchor not found — skipping scroll patch")
else:
    content = content.replace(OLD_LOGIN_ERR, NEW_LOGIN_ERR, 1)
    print("✓ Patched: login error scrollIntoView added")

with open('backend/main.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("DONE — portal auto-login patch applied")
