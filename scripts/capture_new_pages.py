import subprocess
import time
import urllib.request
import os
import shutil

PORT = 8001
BASE_URL = f"http://127.0.0.1:{PORT}/"
EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
ARTIFACT_DIR = r"C:\Users\naras\.gemini\antigravity\brain\aa64cefb-1b87-4854-a6a9-6e0c332f3e9f"

print(f"Starting uvicorn server on port {PORT}...")
server_proc = subprocess.Popen(
    ["python", "-m", "uvicorn", "apps.api.src.main:app", "--port", str(PORT)],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

server_ready = False
for attempt in range(25):
    time.sleep(1)
    try:
        req = urllib.request.urlopen(BASE_URL, timeout=2)
        if req.status == 200:
            print("Server is UP and serving dashboard!")
            server_ready = True
            break
    except Exception as e:
        print(f"Waiting for server... ({e})")

if not server_ready:
    print("Server failed to start!")
    server_proc.kill()
    exit(1)

# Step simulation once to ensure live readings exist
try:
    login_req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/v1/auth/login",
        data=b'{"username":"operator","password":"operator_secret_123"}',
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(login_req, timeout=3) as resp:
        import json
        data = json.loads(resp.read().decode())
        token = data["access_token"]
        step_req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/api/v1/simulator/step",
            data=b"{}",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
        )
        urllib.request.urlopen(step_req, timeout=3)
        print("Simulator stepped successfully!")
except Exception as ex:
    print("Simulator step note:", ex)

pages = [
    ("#finance", "page_finance_1536x864.png"),
    ("#automation", "page_automation_agent_1536x864.png"),
    ("#dashboard", "page_dashboard_latest_1536x864.png"),
]

for section, filename in pages:
    target_url = f"{BASE_URL}{section}"
    local_path = os.path.abspath(f"apps/dashboard/assets/{filename}")
    print(f"Capturing {target_url} -> {filename}...")
    edge_cmd = [
        EDGE_PATH,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--virtual-time-budget=6000",
        "--window-size=1536,864",
        f"--screenshot={local_path}",
        target_url
    ]
    res = subprocess.run(edge_cmd, capture_output=True, text=True, timeout=30)
    print(f"Edge exited {res.returncode} for {filename}")
    if os.path.exists(local_path):
        art_path = os.path.join(ARTIFACT_DIR, filename)
        shutil.copyfile(local_path, art_path)
        print(f"Copied to artifact: {art_path}")

server_proc.terminate()
try:
    server_proc.wait(timeout=5)
except:
    server_proc.kill()

print("All screenshots completed!")

