"""Check portal response headers for CSP issues and test login flow end-to-end."""
import sys, os, re
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DATABASE_URL'] = 'sqlite:///./test_csp.db'
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
slug = 'csp-test'
existing = db.query(Clinic).filter(Clinic.slug == slug).first()
if existing:
    db.delete(existing); db.commit()
c = Clinic(slug=slug, name='CSP Test', specialty='Fam', email='csp@t.com', phone='111',
           subscription_status='trial', plan='starter',
           customer_password_hash=hash_password('MyPass123!'), is_active=True,
           trial_ends_at=datetime.utcnow() + timedelta(days=14))
db.add(c); db.commit()

client = TestClient(app, raise_server_exceptions=True)

# Check portal page headers
r = client.get(f'/c/{slug}')
print("=== Portal page response headers ===")
for k, v in r.headers.items():
    print(f"  {k}: {v}")

print(f"\nStatus: {r.status_code}")
print(f"Content-Type: {r.headers.get('content-type', 'MISSING')}")

# Check if CSP blocks inline scripts
csp = r.headers.get('content-security-policy', '')
print(f"\nCSP: '{csp}'")
if csp and 'script-src' in csp and "'unsafe-inline'" not in csp and 'nonce' not in csp:
    print("ISSUE: CSP blocks inline scripts! 'unsafe-inline' missing from script-src")
elif not csp:
    print("No CSP header (inline scripts allowed)")
else:
    print("CSP allows inline scripts")

# Check the form HTML
html = r.text
form_match = re.search(r'<form[^>]*onsubmit[^>]*>.*?</form>', html, re.DOTALL)
if form_match:
    print(f"\n=== Login form HTML ===")
    print(form_match.group(0)[:500])

# Test login directly
login_r = client.post('/api/clinic-auth/login',
                      json={'email': 'csp@t.com', 'password': 'MyPass123!'})
print(f"\n=== Login API ===")
print(f"Status: {login_r.status_code}")
print(f"Response: {login_r.json()}")

# If login worked, test token verify
if login_r.status_code == 200:
    token = login_r.json()['token']
    verify_r = client.get('/api/clinic-auth/verify',
                          headers={'X-Clinic-Token': token})
    print(f"\n=== Token verify ===")
    print(f"Status: {verify_r.status_code}")
    print(f"Response: {verify_r.json()}")

    # Test profile API (the first call showDash would trigger via loadProviders/loadSetup)
    profile_r = client.get(f'/api/{slug}/profile',
                           headers={'X-Clinic-Token': token})
    print(f"\n=== Profile API ===")
    print(f"Status: {profile_r.status_code}")
    print(f"Response keys: {list(profile_r.json().keys()) if profile_r.status_code == 200 else profile_r.json()}")

db.query(Clinic).filter(Clinic.slug == slug).delete(); db.commit(); db.close()
print("\nDone.")
