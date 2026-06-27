"""Simulate the EXACT flow: signup as trial clinic, then login via portal form."""
import sys, os, re
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DATABASE_URL'] = 'sqlite:///./test_trial_login.db'
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
client = TestClient(app, raise_server_exceptions=False)

# Step 1: Signup as a new trial clinic (exactly as a user would)
signup_r = client.post('/api/clinic-auth/signup', json={
    'email': 'newdoc@sunrise.com',
    'slug': 'sunrise-trial-test',
    'name': 'Sunrise Pediatrics',
    'specialty': 'Pediatrics',
    'password': 'SunrisePass123!'
})
print(f"=== SIGNUP ===")
print(f"Status: {signup_r.status_code}")
print(f"Response: {signup_r.json()}")

if signup_r.status_code != 200:
    print("SIGNUP FAILED - cannot continue")
    sys.exit(1)

slug = signup_r.json()['slug']
signup_token = signup_r.json().get('token', '')
print(f"\nClinic slug: {slug}")
print(f"Signup token: {signup_token[:8]}...")

# Step 2: Visit the portal page (like the user would after signup)
portal_r = client.get(f'/c/{slug}')
print(f"\n=== PORTAL PAGE ===")
print(f"Status: {portal_r.status_code}")
html = portal_r.text
print(f"HTML length: {len(html)}")

# Check for any JS errors or missing elements
script_blocks = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
script_js = max(script_blocks, key=len) if script_blocks else ''
print(f"Script length: {len(script_js)}")

# Look for the most critical things
print(f"doLogin present: {'function doLogin' in script_js}")
print(f"login-screen present: {'id=\"login-screen\"' in html}")
print(f"dash-screen present: {'id=\"dash-screen\"' in html}")

# Step 3: Login via the login API (simulating the doLogin JS fetch)
login_r = client.post('/api/clinic-auth/login', json={
    'email': 'newdoc@sunrise.com',
    'password': 'SunrisePass123!'
})
print(f"\n=== LOGIN ===")
print(f"Status: {login_r.status_code}")
print(f"Response: {login_r.json()}")

if login_r.status_code != 200:
    print(f"\nLOGIN FAILED! Error: {login_r.json()}")
    # Check is_active
    S = sessionmaker(bind=engine)
    db = S()
    clinic = db.query(Clinic).filter(Clinic.slug == slug).first()
    print(f"\nClinic in DB: slug={clinic.slug if clinic else 'NOT FOUND'}")
    if clinic:
        print(f"  is_active: {clinic.is_active}")
        print(f"  subscription_status: {clinic.subscription_status}")
        print(f"  plan: {clinic.plan}")
        print(f"  trial_ends_at: {clinic.trial_ends_at}")
    db.close()
else:
    token = login_r.json()['token']
    print(f"\nToken: {token[:8]}...")

    # Step 4: Verify token works
    verify_r = client.get('/api/clinic-auth/verify', headers={'X-Clinic-Token': token})
    print(f"\n=== TOKEN VERIFY ===")
    print(f"Status: {verify_r.status_code}")
    print(f"Response: {verify_r.json()}")

    # Step 5: Test the APIs that showDash() would trigger
    profile_r = client.get(f'/api/{slug}/profile', headers={'X-Clinic-Token': token})
    print(f"\n=== PROFILE API ===")
    print(f"Status: {profile_r.status_code}")
    if profile_r.status_code == 200:
        print(f"OK - {len(profile_r.json())} fields")
    else:
        print(f"ERROR: {profile_r.json()}")

# Cleanup
S = sessionmaker(bind=engine)
db = S()
db.query(Clinic).filter(Clinic.slug == slug).delete()
db.commit(); db.close()
print("\nDone.")
