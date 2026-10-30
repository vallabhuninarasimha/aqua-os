import subprocess
import time
import urllib.request
import os

PORT = 8000
URL = f"http://127.0.0.1:{PORT}/"
SCREENSHOT_PATH = os.path.abspath("apps/dashboard/assets/actual_dashboard_1536x864.png")
EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

print(f"Starting uvicorn server on port {PORT}...")
server_proc = subprocess.Popen(
    ["python", "-m", "uvicorn", "apps.api.src.main:app", "--port", str(PORT)],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

# Wait for server to start
server_ready = False
for attempt in range(20):
    time.sleep(1)
    try:
        req = urllib.request.urlopen(URL, timeout=2)
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
        # Step simulator
        step_req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/api/v1/simulator/step",
            data=b"{}",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
        )
        urllib.request.urlopen(step_req, timeout=3)
        print("Simulator stepped successfully!")
except Exception as ex:
    print("Simulator step note:", ex)

print("Running headless Edge with --virtual-time-budget=5000 to capture screenshot at 1536x864...")
edge_cmd = [
    EDGE_PATH,
    "--headless",
    "--disable-gpu",
    "--no-sandbox",
    "--virtual-time-budget=5000",
    "--window-size=1536,864",
    f"--screenshot={SCREENSHOT_PATH}",
    URL
]

res = subprocess.run(edge_cmd, capture_output=True, text=True, timeout=30)
print("Edge return code:", res.returncode)

# Terminate server
server_proc.terminate()
try:
    server_proc.wait(timeout=5)
except:
    server_proc.kill()

if os.path.exists(SCREENSHOT_PATH):
    from PIL import Image
    im = Image.open(SCREENSHOT_PATH)
    print(f"Screenshot successfully captured! File: {SCREENSHOT_PATH}, Dimensions: {im.size}")
else:
    print("Screenshot file was not found!")
