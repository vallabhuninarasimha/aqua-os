import subprocess
import time
import os
from PIL import Image

PORT = 8001
EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
ARTIFACT_DIR = r"C:\Users\naras\.gemini\antigravity\brain\aa64cefb-1b87-4854-a6a9-6e0c332f3e9f"
DASHBOARD_ASSETS = r"apps\dashboard\assets"

targets = [
    {
        "name": "role_manager_view_1536x864",
        "url": f"http://127.0.0.1:{PORT}/?mode=manager#dashboard",
        "desc": "Manager Experience — Executive Crop Economics & 4-Tank Overview"
    },
    {
        "name": "role_farmer_view_1536x864",
        "url": f"http://127.0.0.1:{PORT}/?mode=farmer#dashboard",
        "desc": "Farmer Experience — Sunlight-Ready Bilingual Telugu/English Console"
    },
    {
        "name": "role_technical_view_1536x864",
        "url": f"http://127.0.0.1:{PORT}/?mode=tech#dashboard",
        "desc": "Technical Experience — IoT Hardware Diagnostics, Sensors & 3-Phase Electrical"
    },
    {
        "name": "live_farm_view_1536x864",
        "url": f"http://127.0.0.1:{PORT}/#live-farm",
        "desc": "Live Farm Digital Twin — Reservoir + Tanks 01 to 04 with Aeration & Water Flow"
    },
    {
        "name": "tenant_switch_view_1536x864",
        "url": f"http://127.0.0.1:{PORT}/?farm_id=farm-beta&mode=manager#dashboard",
        "desc": "Tenant Switching in Action — Beta Intensive RAS Facility (farm-beta)"
    }
]

for t in targets:
    filename = f"{t['name']}.png"
    artifact_path = os.path.join(ARTIFACT_DIR, filename)
    local_path = os.path.join(DASHBOARD_ASSETS, filename)
    
    print(f"\n--- Capturing: {t['desc']} ---")
    print(f"URL: {t['url']}")
    
    cmd = [
        EDGE_PATH,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--virtual-time-budget=4000",
        "--window-size=1536,864",
        f"--screenshot={artifact_path}",
        t["url"]
    ]
    
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    print("Return code:", res.returncode)
    
    if os.path.exists(artifact_path):
        im = Image.open(artifact_path)
        print(f"Saved to Artifacts: {artifact_path} ({im.size})")
        # Copy to dashboard assets as well
        im.save(local_path)
        print(f"Saved copy to: {local_path}")
    else:
        print(f"FAILED to capture {filename}")

print("\nAll screenshot captures complete!")

