import sys, os, re
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DATABASE_URL'] = 'sqlite:///./test_render_check.db'
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

slug = 'test-render-js'
existing = db.query(Clinic).filter(Clinic.slug == slug).first()
if existing:
    db.delete(existing); db.commit()

c = Clinic(slug=slug, name='Test Clinic', specialty='Fam', email='t@t.com', phone='111',
           subscription_status='active', plan='professional',
           customer_password_hash=hash_password('pass'), is_active=True,
           subscription_ends_at=datetime.utcnow() + timedelta(days=30))
db.add(c); db.commit()

client = TestClient(app, raise_server_exceptions=True)
r = client.get(f'/c/{slug}')
html = r.text
print('Status:', r.status_code)

# Find the <script> tag in the HTML output
script_start = html.find('<script>')
script_end = html.rfind('</script>')
script_block = html[script_start:script_end]
print('Script length:', len(script_block))

# Check SLUG definition
idx = script_block.find('var SLUG')
print('SLUG def:', repr(script_block[idx:idx+100]))

# Check for doLogin
idx2 = script_block.find('function doLogin')
print('doLogin found:', idx2 != -1)

# Check for \\S in output (should be \S for JS regex)
bs_s = script_block.count('\\S')
print('\\S occurrences in output JS:', bs_s)

# Check for double-backslash-S which would be wrong in JS
dbs_s = script_block.count('\\\\S')
print('\\\\S (double-backslash-S, wrong) occurrences:', dbs_s)

# Now test login API directly
login_r = client.post('/api/clinic-auth/login',
                      json={'email': 't@t.com', 'password': 'pass'})
print('\nLogin API status:', login_r.status_code)
print('Login API response:', login_r.json())

db.query(Clinic).filter(Clinic.slug == slug).delete(); db.commit(); db.close()
print('\nDone.')
