"""Check the JS initialization block at end of portal script."""
import sys, os, re
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DATABASE_URL'] = 'sqlite:///./test_jsinit.db'
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
slug = 'jsinit-test'
existing = db.query(Clinic).filter(Clinic.slug == slug).first()
if existing:
    db.delete(existing); db.commit()
c = Clinic(slug=slug, name='Init Test', specialty='Fam', email='init@t.com', phone='111',
           subscription_status='trial', plan='starter',
           customer_password_hash=hash_password('pass'), is_active=True,
           trial_ends_at=datetime.utcnow() + timedelta(days=14))
db.add(c); db.commit()

client = TestClient(app, raise_server_exceptions=True)
r = client.get(f'/c/{slug}')
html = r.text

script_blocks = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
script_js = max(script_blocks, key=len)

print("=== Last 2000 chars of JS (init block) ===")
print(script_js[-2000:])
print()

print("=== URL param / auto-login checks ===")
for kw in ['URLSearchParams', 'location.search', 'location.hash', 'auto_token', 'autoLogin']:
    idx = script_js.find(kw)
    if idx != -1:
        print(f"{kw} at {idx}: {repr(script_js[max(0,idx-50):idx+200])}")
    else:
        print(f"{kw}: NOT FOUND")

db.query(Clinic).filter(Clinic.slug == slug).delete(); db.commit(); db.close()
print("\nDone.")
