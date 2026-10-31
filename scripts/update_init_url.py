with open('apps/dashboard/js/dashboard.js', 'r', encoding='utf-8') as f:
    code = f.read()

target = """    // Initial section routing & browser back/forward support
    const initialHash = window.location.hash.slice(1);
    if (initialHash) switchSection(initialHash);
    window.addEventListener("hashchange", () => switchSection(window.location.hash.slice(1)));

    if (!state.token) {
      try {
        const res = await fetch(API_BASE + "/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: "operator", password: "operator_secret_123" })
        });
        if (res.ok) {
          const data = await res.json();
          state.token = data.access_token;
          state.user = {
            user_id: data.user_id,
            username: data.username,
            farm_id: data.farm_id,
            role: data.role
          };
          sessionStorage.setItem("aqua_token", state.token);
          sessionStorage.setItem("aqua_user", JSON.stringify(state.user));
        }
      } catch {
        // ignore
      }
    }

    toggleLoginGate(false);
    await loadAllFarmData();
    state.refreshTimer = setInterval(loadAllFarmData, 30000);"""

replacement = """    // Parse URL query parameters for mode and farm_id
    const urlParams = new URLSearchParams(window.location.search);
    const paramMode = urlParams.get("mode");
    const paramFarm = urlParams.get("farm_id");

    if (paramFarm) {
      state.farmId = paramFarm;
      const sel = $("#tenantFarmSelector");
      if (sel) sel.value = paramFarm;
      const badge = $("#tenantBadge");
      if (badge) badge.textContent = paramFarm === "farm-beta" ? "TENANT: BETA" : "TENANT: ALPHA";
      const mgrTitle = $("#managerFacilityTitle");
      if (mgrTitle) {
        mgrTitle.textContent = paramFarm === "farm-beta" ? 
          "Beta Intensive RAS Facility — Executive Oversight" : 
          "Alpha Coastal Shrimp Facility — Executive Oversight";
      }
    }
    if (paramMode) {
      state.infoMode = paramMode;
    }

    // Initial section routing & browser back/forward support
    const initialHash = window.location.hash.slice(1);
    if (initialHash) switchSection(initialHash);
    window.addEventListener("hashchange", () => switchSection(window.location.hash.slice(1)));

    if (!state.token) {
      const loginCreds = (state.farmId === "farm-beta") ?
        { username: "beta_operator", password: "beta_secret_123" } :
        { username: "operator", password: "operator_secret_123" };
      try {
        const res = await fetch(API_BASE + "/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(loginCreds)
        });
        if (res.ok) {
          const data = await res.json();
          state.token = data.access_token;
          state.user = {
            user_id: data.user_id,
            username: data.username,
            farm_id: data.farm_id,
            role: data.role
          };
          sessionStorage.setItem("aqua_token", state.token);
          sessionStorage.setItem("aqua_user", JSON.stringify(state.user));
        }
      } catch {
        // ignore
      }
    }

    toggleLoginGate(false);
    await loadAllFarmData();
    setInfoMode(state.infoMode || "manager");
    state.refreshTimer = setInterval(loadAllFarmData, 30000);"""

if target in code:
    code = code.replace(target, replacement)
    print("Direct match replaced!")
elif target.replace('\n', '\r\n') in code:
    code = code.replace(target.replace('\n', '\r\n'), replacement.replace('\n', '\r\n'))
    print("CRLF match replaced!")
else:
    print("Could not find target block!")

with open('apps/dashboard/js/dashboard.js', 'w', encoding='utf-8') as f:
    f.write(code)

print("dashboard.js init() updated successfully!")

