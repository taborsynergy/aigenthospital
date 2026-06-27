"""Extract the rendered portal JS and check for syntax issues."""
import sys, os, re
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DATABASE_URL'] = 'sqlite:///./test_jssyn.db'
os.environ['ADMIN_PASSWORD'] = 'test'
os.environ['ANTHROPIC_API_KEY'] = 'dummy'
os.environ['MOCK_MODE'] = '1'
os.environ['TESTING'] = '1'

from backend.main import app
from backend.db.database import Base, engine
from backend.db.models import Clinic
from backend.routers.clinic_auth import hash_password
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

Base.metadata.create_all(bind=engine)
S = sessionmaker(bind=engine)
db = S()
slug = 'jssyn-test'
existing = db.query(Clinic).filter(Clinic.slug == slug).first()
if existing:
    db.delete(existing); db.commit()

c = Clinic(slug=slug, name='JS Syntax Test', specialty='Fam', email='jssyn@t.com', phone='111',
           subscription_status='active', plan='professional',
           customer_password_hash=hash_password('pass'), is_active=True,
           subscription_ends_at=datetime.utcnow() + timedelta(days=30))
db.add(c); db.commit()

client = TestClient(app, raise_server_exceptions=True)
r = client.get(f'/c/{slug}')
html = r.text

# Extract the <script> block from rendered HTML
# There can be multiple script tags - find the BIG one
script_blocks = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
print(f"Script blocks found: {len(script_blocks)}")
for i, blk in enumerate(script_blocks):
    print(f"  Block {i}: length={len(blk)}, preview={repr(blk[:80])}")

# Use the largest one
script_js = max(script_blocks, key=len) if script_blocks else ""
print(f"\nUsing largest block: {len(script_js)} chars")

# Check key functions
print("doLogin present:", "function doLogin" in script_js)
print("showDash present:", "function showDash" in script_js)
print("SLUG present:", "var SLUG" in script_js)

# Count premature </script> closes inside the JS block
premature_closes = list(re.finditer(r'<\/?\s*script', script_js, re.IGNORECASE))
print(f"\n<script>/<\/script> tags inside JS block (should be 0): {len(premature_closes)}")
for m in premature_closes:
    print(f"  [{m.start()}] context: {repr(script_js[max(0,m.start()-50):m.start()+60])}")

# Check for \S in JS
bs_s_locs = list(re.finditer(r'\\S', script_js))
print(f"\n\\S occurrences in output JS: {len(bs_s_locs)}")
for m in bs_s_locs:
    print(f"  [{m.start()}] context: {repr(script_js[max(0,m.start()-30):m.start()+30])}")

# Test login API
login_r = client.post('/api/clinic-auth/login',
                      json={'email': 'jssyn@t.com', 'password': 'pass'})
print(f"\nLogin API: {login_r.status_code} -> {login_r.json()}")

# Check DOMContentLoaded handler
idx = script_js.find('DOMContentLoaded')
if idx != -1:
    print(f"\nDOMContentLoaded: {repr(script_js[idx:idx+300])}")
else:
    print("\nDOMContentLoaded: NOT FOUND")

# Check window.onload
idx2 = script_js.find('window.onload')
if idx2 != -1:
    print(f"\nwindow.onload: {repr(script_js[idx2:idx2+200])}")
else:
    print("\nwindow.onload: NOT FOUND")

db.query(Clinic).filter(Clinic.slug == slug).delete(); db.commit(); db.close()
print("\nDone.")
