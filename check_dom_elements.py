"""Check that all critical DOM elements exist in rendered portal HTML."""
import sys, os, re
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DATABASE_URL'] = 'sqlite:///./test_dom.db'
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
slug = 'dom-test'
existing = db.query(Clinic).filter(Clinic.slug == slug).first()
if existing:
    db.delete(existing); db.commit()
c = Clinic(slug=slug, name='DOM Test', specialty='Fam', email='dom@t.com', phone='111',
           subscription_status='trial', plan='starter',
           customer_password_hash=hash_password('pass'), is_active=True,
           trial_ends_at=datetime.utcnow() + timedelta(days=14))
db.add(c); db.commit()

client = TestClient(app, raise_server_exceptions=True)
r = client.get(f'/c/{slug}')
html = r.text

# Check all critical element IDs
critical_ids = [
    'login-screen', 'dash-screen', 'login-form', 'login-btn', 'login-err',
    'l-email', 'l-pass',
    'patient-url', 'qr-img', 'embed-code', 'invite-msg',
    'tab-setup', 'tab-appointments', 'tab-analytics',
    'dash-tabs',
]

print("=== Critical DOM element check ===")
all_ok = True
for eid in critical_ids:
    found = f'id="{eid}"' in html
    status = "OK" if found else "MISSING"
    if not found:
        all_ok = False
    print(f"  {status}: #{eid}")

print(f"\nAll critical elements: {'OK' if all_ok else 'MISSING SOME'}")

# Also check for dash-screen specifically
dash_count = html.count('id="dash-screen"')
login_count = html.count('id="login-screen"')
print(f"\ndash-screen occurrences: {dash_count}")
print(f"login-screen occurrences: {login_count}")

# Show what's around dash-screen in HTML
if 'id="dash-screen"' in html:
    idx = html.find('id="dash-screen"')
    print(f"\ndash-screen context: {repr(html[max(0,idx-100):idx+200])}")

# Show any JS syntax errors by checking for unbalanced braces in the script
script_blocks = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
script_js = max(script_blocks, key=len) if script_blocks else ''

# Count opening vs closing braces (rough check)
open_braces = script_js.count('{')
close_braces = script_js.count('}')
print(f"\nScript brace balance: open={open_braces} close={close_braces} diff={open_braces-close_braces}")

# Check template literals (backticks)
backtick_count = script_js.count('`')
print(f"Template literal backticks: {backtick_count} ({'balanced' if backtick_count % 2 == 0 else 'UNBALANCED - JS SYNTAX ERROR'})")

db.query(Clinic).filter(Clinic.slug == slug).delete(); db.commit(); db.close()
print("\nDone.")
