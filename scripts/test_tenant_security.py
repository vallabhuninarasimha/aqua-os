import urllib.request
import json

def login(u, p):
    req = urllib.request.Request(
        'http://127.0.0.1:8001/api/v1/auth/login',
        data=json.dumps({'username': u, 'password': p}).encode(),
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())['access_token']

admin_tok = login('admin', 'admin_secret_123')
op_tok = login('operator', 'operator_secret_123')
beta_tok = login('beta_operator', 'beta_secret_123')

# 1. Admin queries farm-beta
req1 = urllib.request.Request(
    'http://127.0.0.1:8001/api/v1/dashboard/overview?farm_id=farm-beta',
    headers={'Authorization': f'Bearer {admin_tok}'}
)
with urllib.request.urlopen(req1) as r1:
    data1 = json.loads(r1.read().decode())
    print('1. Admin querying farm-beta: SUCCESS. Ponds:', [p['pond_id'] for p in data1['ponds']])

# 2. Operator queries farm-beta (should be 403 Forbidden)
req2 = urllib.request.Request(
    'http://127.0.0.1:8001/api/v1/dashboard/overview?farm_id=farm-beta',
    headers={'Authorization': f'Bearer {op_tok}'}
)
try:
    urllib.request.urlopen(req2)
    print('2. Operator querying farm-beta: UNEXPECTED SUCCESS!')
except urllib.error.HTTPError as e:
    print('2. Operator querying farm-beta: EXPECTED 403:', e.code, e.read().decode())

# 3. Beta operator queries farm-beta
req3 = urllib.request.Request(
    'http://127.0.0.1:8001/api/v1/dashboard/overview?farm_id=farm-beta',
    headers={'Authorization': f'Bearer {beta_tok}'}
)
with urllib.request.urlopen(req3) as r3:
    data3 = json.loads(r3.read().decode())
    print('3. Beta Operator querying farm-beta: SUCCESS. Ponds:', [p['pond_id'] for p in data3['ponds']])

