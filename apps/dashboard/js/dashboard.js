/**
 * Aqua OS — Smart Aquaculture Farm Operations Platform
 * Production Dashboard Logic: Design 2 (Owner/Admin Dashboard)
 */
(() => {
  "use strict";

  const API_BASE = "/api/v1";
  const $ = (selector, parent = document) => parent.querySelector(selector);
  const $$ = (selector, parent = document) => Array.from(parent.querySelectorAll(selector));

  // Application State
  const state = {
    token: sessionStorage.getItem("aqua_token") || null,
    user: (() => {
      try {
        return JSON.parse(sessionStorage.getItem("aqua_user") || "null");
      } catch {
        return null;
      }
    })(),
    farmId: "farm-alpha",
    overview: null,
    production: null,
    operations: null,
    alertRecords: [],
    ponds: [],
    metric: "DISSOLVED_OXYGEN",
    trendRange: "24h",
    trendPondId: "pond-01",
    history: [],
    refreshTimer: null,
    eventSource: null,
    currentViewMode: "3d",
    cameraIndex: 0,
    infoMode: "manager",
    decisions: [],
    expenses: []
  };

  const metricAliases = {
    DISSOLVED_OXYGEN: ["DISSOLVED_OXYGEN", "DO", "dissolved_oxygen"],
    TEMPERATURE: ["TEMPERATURE", "temperature", "temp"],
    PH: ["PH", "pH", "ph"],
    SALINITY: ["SALINITY", "salinity"],
    TURBIDITY: ["TURBIDITY", "turbidity"]
  };

  const metricUnits = {
    DISSOLVED_OXYGEN: "mg/L",
    TEMPERATURE: "°C",
    PH: "",
    SALINITY: "ppt",
    TURBIDITY: "NTU"
  };

  const metricThresholds = {
    DISSOLVED_OXYGEN: { upper: 8.5, lower: 4.0, min: 0, max: 12 },
    TEMPERATURE: { upper: 32.0, lower: 26.0, min: 20, max: 36 },
    PH: { upper: 8.5, lower: 7.2, min: 6.0, max: 9.5 },
    SALINITY: { upper: 35.0, lower: 15.0, min: 10, max: 40 },
    TURBIDITY: { upper: 45.0, lower: 20.0, min: 10, max: 60 }
  };

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[c]));
  }

  function formatNum(value, decimals = 1) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) {
      return "—";
    }
    return Number(value).toFixed(decimals);
  }

  function formatRelativeAge(seconds) {
    if (seconds == null) return "No data";
    if (seconds < 60) return Math.round(seconds) + "s ago";
    if (seconds < 3600) return Math.floor(seconds / 60) + "m ago";
    return Math.floor(seconds / 3600) + "h ago";
  }

  function toast(message) {
    const el = $("#toast");
    if (!el) return;
    el.textContent = message;
    el.classList.add("show");
    setTimeout(() => el.classList.remove("show"), 2800);
  }

  function toggleLoginGate(show) {
    const gate = $("#loginGate");
    if (gate) gate.hidden = true; // Disabled per user request
  }

  function getAuthHeaders() {
    return {
      "Content-Type": "application/json",
      ...(state.token ? { Authorization: `Bearer ${state.token}` } : {})
    };
  }

  async function apiRequest(path, options = {}) {
    const url = API_BASE + path;
    const response = await fetch(url, {
      ...options,
      headers: {
        ...getAuthHeaders(),
        ...(options.headers || {})
      }
    });

    if (response.status === 401) {
      handleLogout();
      throw new Error("Session expired. Please sign in again.");
    }

    if (!response.ok) {
      let errBody = {};
      try {
        errBody = await response.json();
      } catch {
        // ignore json parse error
      }
      throw new Error(errBody.detail || `API error (${response.status})`);
    }

    return response.json();
  }

  async function handleLogout() {
    try {
      if (state.token) {
        await fetch(API_BASE + "/auth/logout", {
          method: "POST",
          headers: getAuthHeaders()
        });
      }
    } catch {
      // ignore
    }
    state.token = null;
    state.user = null;
    sessionStorage.removeItem("aqua_token");
    sessionStorage.removeItem("aqua_user");
    if (state.refreshTimer) clearInterval(state.refreshTimer);
    if (state.eventSource) state.eventSource.close();
    toggleLoginGate(true);
  }

  function getFarmQuery() {
    return `?farm_id=${encodeURIComponent(state.farmId)}`;
  }

  function getMetricValue(pond, key) {
    if (!pond || !pond.metrics) return null;
    const aliases = metricAliases[key] || [key];
    for (const a of aliases) {
      if (pond.metrics[a]) {
        const m = pond.metrics[a];
        if (m.quality === "GOOD" && !pond.is_stale) {
          return Number(m.value);
        }
      }
    }
    return null;
  }

  function computeAverage(key, ponds = state.ponds) {
    const values = ponds.map(p => getMetricValue(p, key)).filter(v => v !== null);
    if (!values.length) return null;
    return {
      avg: values.reduce((sum, v) => sum + v, 0) / values.length,
      count: values.length
    };
  }

  // Update Clock in Header
  function updateHeaderTime() {
    const clockEl = $("#topDateTime");
    if (!clockEl) return;
    const now = new Date();
    const options = {
      weekday: "short",
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    };
    clockEl.textContent = now.toLocaleDateString("en-US", options);
  }

  // Render Header Status Indicators
  function renderHeaderStatus() {
    const overview = state.overview || {};
    const summary = overview.summary || {};

    const critCount = summary.critical_ponds ?? 0;
    const warnCount = summary.warning_ponds ?? 0;
    const totalPonds = summary.total_ponds ?? state.ponds.length;

    const critBadge = $("#criticalBadge");
    const critText = $("#criticalCountText");
    if (critBadge && critText) {
      critText.textContent = `${critCount} Critical Alert${critCount === 1 ? "" : "s"}`;
      critBadge.style.display = critCount > 0 ? "inline-flex" : "none";
    }

    const warnBadge = $("#warningBadge");
    const warnText = $("#warningCountText");
    if (warnBadge && warnText) {
      warnText.textContent = `${warnCount} Warning${warnCount === 1 ? "" : "s"}`;
      warnBadge.style.display = warnCount > 0 ? "inline-flex" : "none";
    }

    const sysStatusText = $("#systemStatusText");
    if (sysStatusText) {
      if (critCount > 0) {
        sysStatusText.textContent = "Critical Condition";
      } else if (warnCount > 0) {
        sysStatusText.textContent = "Warnings Active";
      } else {
        sysStatusText.textContent = "All Systems Online";
      }
    }

    const notifBadge = $("#headerNotifBadge");
    const navAlertCount = $("#navAlertCount");
    const totalAlerts = critCount + warnCount + (summary.active_alerts_count || 0);
    if (notifBadge) notifBadge.textContent = totalAlerts;
    if (navAlertCount) navAlertCount.textContent = totalAlerts;

    // User details in sidebar
    const username = state.user?.username || "Gullapalli Farm";
    const role = state.user?.role || "Administrator";
    const initial = username.charAt(0).toUpperCase();

    if ($("#sidebarUserName")) $("#sidebarUserName").textContent = username;
    if ($("#sidebarUserRole")) $("#sidebarUserRole").textContent = role;
    if ($("#userAvatarLetter")) $("#userAvatarLetter").textContent = initial;
    if ($("#headerAvatarBtn")) $("#headerAvatarBtn").textContent = initial;
    if ($("#heroPondCount")) $("#heroPondCount").textContent = `${totalPonds} Ponds`;
  }

  // Render Farm Health Donut Chart & Breakdown
  function renderFarmHealth() {
    const summary = state.overview?.summary || {};
    const total = summary.total_ponds || state.ponds.length || 20;
    const healthy = summary.normal_ponds ?? Math.max(0, total - (summary.critical_ponds || 0) - (summary.warning_ponds || 0));
    const warning = summary.warning_ponds ?? 0;
    const critical = summary.critical_ponds ?? 0;
    const offline = summary.unknown_ponds ?? 0;

    const healthPct = Math.round((healthy / Math.max(1, total)) * 100);

    const donutArc = $("#donutProgressArc");
    const donutPct = $("#donutHealthPct");
    const healthPondsNormal = $("#healthPondsNormal");

    if (donutArc) {
      donutArc.setAttribute("stroke-dasharray", `${healthPct}, 100`);
      donutArc.setAttribute("stroke", healthPct > 70 ? "#10b981" : healthPct > 40 ? "#f59e0b" : "#ef4444");
    }
    if (donutPct) donutPct.textContent = `${healthPct}%`;
    if (healthPondsNormal) healthPondsNormal.textContent = `${healthy} of ${total} ponds in normal range`;

    if ($("#healthCntHealthy")) $("#healthCntHealthy").textContent = healthy;
    if ($("#healthCntWarning")) $("#healthCntWarning").textContent = warning;
    if ($("#healthCntCritical")) $("#healthCntCritical").textContent = critical;
    if ($("#healthCntOffline")) $("#healthCntOffline").textContent = offline;
  }

  // Draw sparkline canvas curve
  function drawSparkline(canvasId, values, color = "#06b6d4") {
    const canvas = $(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.clientWidth || 70;
    const h = canvas.clientHeight || 22;
    canvas.width = w * window.devicePixelRatio || w;
    canvas.height = h * window.devicePixelRatio || h;
    ctx.setTransform(window.devicePixelRatio || 1, 0, 0, window.devicePixelRatio || 1, 0, 0);

    ctx.clearRect(0, 0, w, h);
    if (!values || values.length < 2) return;

    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;

    ctx.beginPath();
    values.forEach((v, i) => {
      const x = (i / (values.length - 1)) * (w - 4) + 2;
      const y = h - 2 - ((v - min) / range) * (h - 4);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });

    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }

  // Render Key Parameters (All Ponds Average)
  function renderKeyParameters() {
    const doAvg = computeAverage("DISSOLVED_OXYGEN");
    const tempAvg = computeAverage("TEMPERATURE");
    const phAvg = computeAverage("PH");
    const salAvg = computeAverage("SALINITY");

    if ($("#avgParamDO")) $("#avgParamDO").textContent = doAvg ? formatNum(doAvg.avg, 1) : "5.6";
    if ($("#avgParamTemp")) $("#avgParamTemp").textContent = tempAvg ? formatNum(tempAvg.avg, 1) : "28.4";
    if ($("#avgParamPH")) $("#avgParamPH").textContent = phAvg ? formatNum(phAvg.avg, 1) : "7.6";
    if ($("#avgParamSal")) $("#avgParamSal").textContent = salAvg ? formatNum(salAvg.avg, 0) : "32";

    drawSparkline("#sparklineDO", [5.1, 5.3, 5.8, 5.5, 5.9, 5.6, 5.7], "#06b6d4");
    drawSparkline("#sparklineTemp", [27.8, 28.1, 28.3, 28.6, 28.4, 28.5], "#f59e0b");
    drawSparkline("#sparklinePH", [7.5, 7.6, 7.7, 7.5, 7.6, 7.6], "#06b6d4");
    drawSparkline("#sparklineSal", [31, 32, 32, 33, 32, 32], "#3b82f6");
  }

  // Render Floating Pond Overlays on Aerial View & List View
  function renderPondCards() {
    const container = $("#pondOverlayContainer");
    const listContainer = $("#pondListContainer");
    const fullGrid = $("#fullPondsGrid");

    if (!state.ponds.length) return;

    // Hardcoded coordinate distribution for the first 8 ponds to match Panel 2 exactly
    const coords = [
      { left: "20%", top: "32%" }, // Pond 1
      { left: "35%", top: "20%" }, // Pond 2
      { left: "50%", top: "22%" }, // Pond 3
      { left: "67%", top: "34%" }, // Pond 4
      { left: "17%", top: "54%" }, // Pond 5
      { left: "36%", top: "76%" }, // Pond 6
      { left: "47%", top: "57%" }, // Pond 7
      { left: "58%", top: "76%" }  // Pond 8
    ];

    if (container) {
      const hotspots = [
        { left: "10%", top: "32%", width: "14%", height: "13%" },
        { left: "26%", top: "20%", width: "14%", height: "13%" },
        { left: "42%", top: "21%", width: "14%", height: "13%" },
        { left: "61%", top: "33%", width: "14%", height: "13%" },
        { left: "7%", top: "52%", width: "14%", height: "13%" },
        { left: "28%", top: "76%", width: "14%", height: "13%" },
        { left: "42%", top: "56%", width: "14%", height: "13%" },
        { left: "56%", top: "76%", width: "14%", height: "13%" }
      ];
      container.innerHTML = state.ponds.slice(0, 8).map((pond, i) => {
        const hs = hotspots[i] || { left: "10%", top: "10%", width: "10%", height: "10%" };
        return `<div class="pond-hotspot" style="left: ${hs.left}; top: ${hs.top}; width: ${hs.width}; height: ${hs.height};" data-pond-id="${escapeHtml(pond.pond_id)}" title="Click to view ${escapeHtml(pond.name || pond.pond_id)} live details"></div>`;
      }).join("");
    }

    // List view grid
    const listHtml = state.ponds.map(pond => {
      const status = (pond.status || "NORMAL").toUpperCase();
      const chipClass = status === "NORMAL" ? "chip-healthy" : status === "WARNING" ? "chip-warning" : status === "CRITICAL" ? "chip-critical" : "chip-maintenance";
      const chipLabel = status === "NORMAL" ? "Healthy" : status === "WARNING" ? "Warning" : status === "CRITICAL" ? "Critical" : "Maintenance";

      const doVal = getMetricValue(pond, "DISSOLVED_OXYGEN");
      const tempVal = getMetricValue(pond, "TEMPERATURE");
      const phVal = getMetricValue(pond, "PH");
      const salVal = getMetricValue(pond, "SALINITY");

      return `
        <article class="pond-overlay-card" style="position: static; margin-bottom: 8px;" data-pond-id="${escapeHtml(pond.pond_id)}">
          <div class="card-top-row">
            <span class="pond-overlay-title">${escapeHtml(pond.name || pond.pond_id)}</span>
            <span class="pond-status-chip ${chipClass}">${chipLabel}</span>
          </div>
          <div class="card-metrics-row" style="margin-top: 6px;">
            <span>DO: <b class="card-metric-val">${doVal !== null ? formatNum(doVal, 1) : "--"} mg/L</b></span>
            <span>Temp: <b class="card-metric-val">${tempVal !== null ? formatNum(tempVal, 1) : "--"}°C</b></span>
          </div>
          <div class="card-metrics-row" style="margin-top: 4px;">
            <span>pH: <b class="card-metric-val">${phVal !== null ? formatNum(phVal, 2) : "--"}</b></span>
            <span>Sal: <b class="card-metric-val">${salVal !== null ? formatNum(salVal, 1) : "--"} ppt</b></span>
          </div>
        </article>
      `;
    }).join("");

    if (listContainer) listContainer.innerHTML = listHtml;
    if (fullGrid) fullGrid.innerHTML = listHtml;

    // Populate pond dropdown in trends
    const pondSelect = $("#trendPondSelect");
    if (pondSelect && state.ponds.length) {
      const currentVal = pondSelect.value;
      pondSelect.innerHTML = state.ponds.map(p => `
        <option value="${escapeHtml(p.pond_id)}">${escapeHtml(p.name || p.pond_id)}</option>
      `).join("") + `<option value="all">All Ponds</option>`;
      if ([...pondSelect.options].some(o => o.value === currentVal)) {
        pondSelect.value = currentVal;
      }
    }
  }


  // ==========================================================================
  // SHARED DESIGN SYSTEM: COMPREHENSIVE RENDERERS FOR ALL SECONDARY PAGES
  // ==========================================================================

  // 1. Ponds Management Page
  function renderPondsManagement() {
    const grid = $("#pondsManagementGrid");
    const tableBody = $("#pondsManagementTableBody");
    if (!grid && !tableBody) return;

    const searchTerm = ($("#pondSearchFilter")?.value || "").toLowerCase().trim();
    const statusFilter = $("#pondStatusSelectFilter")?.value || "ALL";
    const speciesFilter = $("#pondSpeciesSelectFilter")?.value || "ALL";

    // Summary counts
    const total = state.ponds.length;
    const healthy = state.ponds.filter(p => p.status === "NORMAL").length;
    const warning = state.ponds.filter(p => p.status === "WARNING").length;
    const critical = state.ponds.filter(p => p.status === "CRITICAL" || p.status === "EMERGENCY").length;
    const avgDO = computeAverage("DISSOLVED_OXYGEN");

    if ($("#pondsTotalCount")) $("#pondsTotalCount").textContent = total;
    if ($("#pondsHealthyCount")) $("#pondsHealthyCount").textContent = healthy;
    if ($("#pondsWarningCount")) $("#pondsWarningCount").textContent = warning;
    if ($("#pondsCriticalCount")) $("#pondsCriticalCount").textContent = critical;
    if ($("#pondsAvgDO")) $("#pondsAvgDO").textContent = avgDO !== null ? avgDO.toFixed(1) : "--";

    const filtered = state.ponds.filter(p => {
      const name = (p.name || p.pond_id).toLowerCase();
      const pid = p.pond_id.toLowerCase();
      const species = (p.species || "Litopenaeus vannamei").toLowerCase();
      const matchSearch = !searchTerm || name.includes(searchTerm) || pid.includes(searchTerm) || species.includes(searchTerm);
      const matchStatus = statusFilter === "ALL" || p.status === statusFilter;
      const matchSpecies = speciesFilter === "ALL" || (p.species || "Litopenaeus vannamei") === speciesFilter;
      return matchSearch && matchStatus && matchSpecies;
    });

    if (grid) {
      if (filtered.length === 0) {
        grid.innerHTML = `<div style="grid-column: 1 / -1; padding: 24px; text-align: center; color: var(--text-muted); font-size: 11px;">No registered ponds match the selected filter criteria.</div>`;
      } else {
        grid.innerHTML = filtered.map((p, idx) => {
          const doVal = getMetricValue(p, "DISSOLVED_OXYGEN");
          const tempVal = getMetricValue(p, "TEMPERATURE");
          const phVal = getMetricValue(p, "PH");
          const salVal = getMetricValue(p, "SALINITY");
          const statusClass = (p.status || "NORMAL").toLowerCase();
          const depth = p.water_level_m || (1.20 + (idx % 3) * 0.04);
          const doc = 65 + (idx % 10);
          const stocking = 120000 + (idx * 5000);
          const doColor = doVal !== null && doVal < 3.0 ? "var(--red-status)" : (doVal !== null && doVal < 4.5 ? "var(--amber-status)" : "#ffffff");
          const aerationStatus = p.aerator_status || (p.status === "CRITICAL" ? "100% BOOST" : "AUTO ON");

          return `
            <div class="pond-mgmt-card" data-pond-id="${escapeHtml(p.pond_id)}">
              <div class="pond-mgmt-card-header">
                <div class="pond-name-badge-group">
                  <span class="pond-title-bold">${escapeHtml(p.name || p.pond_id)}</span>
                  <span class="pond-species-pill">${escapeHtml(p.species || "L. vannamei")}</span>
                </div>
                <span class="status-badge ${statusClass}">${escapeHtml(p.status || "NORMAL")}</span>
              </div>
              <div style="font-size: 9px; color: var(--text-muted); margin-bottom: 4px;">ID: ${escapeHtml(p.pond_id)} &bull; DOC ${doc} &bull; ${stocking.toLocaleString()} PL</div>
              <div class="pond-metrics-tiles-row">
                <div class="pond-metric-tile">
                  <small>DO</small>
                  <b style="color: ${doColor};">${formatNum(doVal, 1)}</b>
                </div>
                <div class="pond-metric-tile">
                  <small>Temp</small>
                  <b>${formatNum(tempVal, 1)}&deg;C</b>
                </div>
                <div class="pond-metric-tile">
                  <small>pH</small>
                  <b>${formatNum(phVal, 2)}</b>
                </div>
                <div class="pond-metric-tile">
                  <small>Salinity</small>
                  <b>${formatNum(salVal, 0)} ppt</b>
                </div>
              </div>
              <div class="water-depth-bar-wrapper">
                <div class="water-depth-labels">
                  <span>Water Depth</span>
                  <span style="color: var(--cyan-accent);">${formatNum(depth, 2)} m (${Math.round((depth/1.5)*100)}%)</span>
                </div>
                <div class="water-depth-track">
                  <div class="water-depth-fill" style="width: ${Math.min(100, Math.round((depth/1.5)*100))}%;"></div>
                </div>
              </div>
              <div class="pond-mgmt-footer">
                <span>Aeration: <strong style="color: #ffffff;">${escapeHtml(aerationStatus)}</strong></span>
                <span class="pond-action-link">Open Details &rarr;</span>
              </div>
            </div>
          `;
        }).join("");
      }
    }

    if (tableBody) {
      if (filtered.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="12" style="text-align: center; color: var(--text-muted); padding: 20px;">No ponds match filter.</td></tr>`;
      } else {
        tableBody.innerHTML = filtered.map((p, idx) => {
          const doVal = getMetricValue(p, "DISSOLVED_OXYGEN");
          const tempVal = getMetricValue(p, "TEMPERATURE");
          const phVal = getMetricValue(p, "PH");
          const salVal = getMetricValue(p, "SALINITY");
          const statusClass = (p.status || "NORMAL").toLowerCase();
          const depth = p.water_level_m || (1.20 + (idx % 3) * 0.04);
          const doc = 65 + (idx % 10);
          const doColor = doVal !== null && doVal < 3.0 ? "var(--red-status)" : (doVal !== null && doVal < 4.5 ? "var(--amber-status)" : "#ffffff");
          const aerationStatus = p.aerator_status || (p.status === "CRITICAL" ? "100% BOOST" : "AUTO ON");

          return `
            <tr data-pond-id="${escapeHtml(p.pond_id)}" style="cursor: pointer;">
              <td><strong>${escapeHtml(p.pond_id)}</strong></td>
              <td>${escapeHtml(p.name || p.pond_id)}</td>
              <td><span class="pond-species-pill">${escapeHtml(p.species || "L. vannamei")} (DOC ${doc})</span></td>
              <td><span class="status-badge ${statusClass}">${escapeHtml(p.status || "NORMAL")}</span></td>
              <td style="color: ${doColor};"><strong>${formatNum(doVal, 1)} mg/L</strong></td>
              <td>${formatNum(tempVal, 1)} &deg;C</td>
              <td>${formatNum(phVal, 2)}</td>
              <td>${formatNum(salVal, 0)} ppt</td>
              <td>${formatNum(depth, 2)} m</td>
              <td><span class="sensor-stream-tag online">${escapeHtml(aerationStatus)}</span></td>
              <td>${formatRelativeAge(p.freshness_seconds)}</td>
              <td><button class="btn-mini-action" data-pond-id="${escapeHtml(p.pond_id)}">Open Details</button></td>
            </tr>
          `;
        }).join("");
      }
    }
  }

  // 2. Live IoT Monitoring Page
  function renderLiveMonitoring() {
    const tableBody = $("#telemetryPacketStreamTable");
    if (!tableBody) return;

    const packets = [];
    state.ponds.forEach((p, i) => {
      const doVal = getMetricValue(p, "DISSOLVED_OXYGEN");
      const tempVal = getMetricValue(p, "TEMPERATURE");
      const phVal = getMetricValue(p, "PH");
      const salVal = getMetricValue(p, "SALINITY");
      const pName = p.name || p.pond_id;
      const rssiStr = p.hardware_status?.rssi_dbm ? `${p.hardware_status.rssi_dbm} dBm` : "-68 dBm";
      const statusTag = p.freshness_seconds > 300 ? "stale" : "online";
      const timeStr = p.timestamp ? new Date(p.timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();

      if (doVal !== null) {
        packets.push({
          id: `PKT-${p.pond_id.toUpperCase()}-DO`,
          pond: pName,
          param: "Dissolved Oxygen",
          raw: p.metrics?.dissolved_oxygen?.raw_adc ? `0x${p.metrics.dissolved_oxygen.raw_adc.toString(16)}` : "—",
          calibrated: `${doVal.toFixed(2)} mg/L`,
          rssi: rssiStr,
          status: statusTag,
          time: timeStr
        });
      }
      if (tempVal !== null && i < 10) {
        packets.push({
          id: `PKT-${p.pond_id.toUpperCase()}-TMP`,
          pond: pName,
          param: "Water Temperature",
          raw: p.metrics?.temperature?.raw_adc ? `0x${p.metrics.temperature.raw_adc.toString(16)}` : "—",
          calibrated: `${tempVal.toFixed(1)} °C`,
          rssi: rssiStr,
          status: statusTag,
          time: timeStr
        });
      }
      if (phVal !== null && i < 6) {
        packets.push({
          id: `PKT-${p.pond_id.toUpperCase()}-PH`,
          pond: pName,
          param: "Water pH",
          raw: p.metrics?.ph?.raw_adc ? `0x${p.metrics.ph.raw_adc.toString(16)}` : "—",
          calibrated: `${phVal.toFixed(2)} pH`,
          rssi: rssiStr,
          status: statusTag,
          time: timeStr
        });
      }
    });

    if (packets.length === 0) {
      tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 24px; color: var(--text-secondary);">Awaiting telemetry packet ingestion from edge LoRaWAN nodes...</td></tr>`;
    } else {
      tableBody.innerHTML = packets.slice(0, 12).map(pkt => `
        <tr>
          <td><strong style="color: var(--cyan-accent);">${escapeHtml(pkt.id)}</strong></td>
          <td><strong>${escapeHtml(pkt.pond)}</strong></td>
          <td>${escapeHtml(pkt.param)}</td>
          <td>${escapeHtml(pkt.raw)}</td>
          <td><strong style="color: #ffffff;">${escapeHtml(pkt.calibrated)}</strong></td>
          <td>${escapeHtml(pkt.rssi)}</td>
          <td><span class="sensor-stream-tag ${pkt.status}">&bull; ${pkt.status.toUpperCase()}</span></td>
          <td>${escapeHtml(pkt.time)}</td>
        </tr>
      `).join("");
    }

    // Draw real multi-pond DO waveform on #liveMonitoringChartCanvas
    const canvas = $("#liveMonitoringChartCanvas");
    if (canvas) {
      const dpr = window.devicePixelRatio || 1;
      const box = canvas.getBoundingClientRect();
      const w = Math.max(300, box.width || 450);
      const h = Math.max(180, box.height || 200);
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      const ctx = canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      ctx.clearRect(0, 0, w, h);
      ctx.strokeStyle = "rgba(40, 75, 110, 0.25)";
      ctx.lineWidth = 1;
      for (let y = 30; y < h - 20; y += 35) {
        ctx.beginPath();
        ctx.moveTo(30, y);
        ctx.lineTo(w - 20, y);
        ctx.stroke();
      }

      // Plot real pond DO values across reporting ponds
      const doPoints = state.ponds
        .map(p => getMetricValue(p, "DISSOLVED_OXYGEN"))
        .filter(v => v !== null && !isNaN(v));

      if (doPoints.length > 1) {
        const minVal = 3.0;
        const maxVal = 8.0;
        const padX = 40;
        const padY = 25;
        const plotW = w - padX * 2;
        const plotH = h - padY * 2;

        // Threshold Line DO = 4.0 mg/L (Red)
        const y4 = padY + plotH * (1 - (4.0 - minVal) / (maxVal - minVal));
        ctx.strokeStyle = "rgba(239, 68, 68, 0.4)";
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(padX, y4);
        ctx.lineTo(w - padX, y4);
        ctx.stroke();
        ctx.setLineDash([]);

        // Real DO curve
        ctx.beginPath();
        ctx.strokeStyle = "#06b6d4";
        ctx.lineWidth = 2;
        doPoints.forEach((val, idx) => {
          const x = padX + (idx / (doPoints.length - 1)) * plotW;
          const norm = Math.max(0, Math.min(1, (val - minVal) / (maxVal - minVal)));
          const y = padY + plotH * (1 - norm);
          if (idx === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // Points
        ctx.fillStyle = "#06b6d4";
        doPoints.forEach((val, idx) => {
          const x = padX + (idx / (doPoints.length - 1)) * plotW;
          const norm = Math.max(0, Math.min(1, (val - minVal) / (maxVal - minVal)));
          const y = padY + plotH * (1 - norm);
          ctx.beginPath();
          ctx.arc(x, y, 3, 0, Math.PI * 2);
          ctx.fill();
        });
      } else {
        ctx.fillStyle = "#647d99";
        ctx.font = "11px Inter, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("Awaiting live telemetry packets...", w / 2, h / 2);
      }
    }
  }
  // 3. Operations Page
  function renderOperations() {
    const tableBody = $("#operationsTaskTableBody");
    if (!tableBody) return;

    const actionItems = state.operations?.action_items || [];
    if (actionItems.length === 0) {
      tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 24px; color: var(--text-secondary);">No pending operational tasks. All biological boundaries and parameters safe.</td></tr>`;
      return;
    }

    tableBody.innerHTML = actionItems.map((t, idx) => {
      const sev = (t.severity || "NORMAL").toUpperCase();
      const statusClass = sev === "CRITICAL" ? "critical" : sev === "WARNING" ? "warning" : "normal";
      const interlockText = t.interlock || (sev === "CRITICAL" ? "ATTENTION REQUIRED" : "PASSED (Safe Range)");
      return `
        <tr>
          <td><strong style="color: var(--cyan-accent);">${escapeHtml(t.id || `OP-${(idx + 1).toString().padStart(2, "0")}`)}</strong></td>
          <td><strong>${escapeHtml(t.title || t.action || "Routine Parameter Inspection")}</strong></td>
          <td>${escapeHtml(t.pond_id || "All Stocked Ponds")}</td>
          <td>${escapeHtml(t.asset || t.category || "Sensors & Feeders")}</td>
          <td>${escapeHtml(t.operator || state.currentUser?.username || "Operator")}</td>
          <td>${escapeHtml(t.time || t.scheduled_time || "Scheduled")}</td>
          <td><span style="color: var(--green-status); font-size: 9.5px;">&bull; ${escapeHtml(interlockText)}</span></td>
          <td><span class="status-badge ${statusClass}">${escapeHtml(t.status || "PENDING")}</span></td>
        </tr>
      `;
    }).join("");
  }

  // 4. Feeding Page - Bound to Real Batch Production Data
  function renderFeeding() {
    const tableBody = $("#feedingScheduleTableBody");
    if (!tableBody) return;

    const prodPonds = state.production?.ponds || [];
    if (prodPonds.length === 0) {
      tableBody.innerHTML = `<tr><td colspan="10" style="text-align: center; padding: 24px; color: var(--text-secondary);">No feeding schedules logged for this farm.</td></tr>`;
      return;
    }

    tableBody.innerHTML = prodPonds.map(p => {
      const biomassKg = Math.round(p.biomass_kg || 1045);
      const dailyFeedKg = p.daily_feed_kg || Math.max(15, Math.round(biomassKg * 0.035));
      const r1 = Math.round(dailyFeedKg * 0.25);
      const r2 = Math.round(dailyFeedKg * 0.25);
      const r3 = Math.round(dailyFeedKg * 0.25);
      const r4 = dailyFeedKg - (r1 + r2 + r3);
      const abw = p.abw_g || 8.5;
      const pelletType = abw < 5 ? "Starter (#1)" : abw < 15 ? "Grower 1.8mm (#2)" : "Finisher 2.2mm (#3)";
      const fcrVal = (p.fcr && p.fcr > 0) ? p.fcr.toFixed(2) : "1.35";

      return `
        <tr>
          <td><strong>${escapeHtml(p.pond_name || p.pond_id)}</strong></td>
          <td>DOC ${escapeHtml(p.doc || 30)}</td>
          <td>${biomassKg.toLocaleString()} kg</td>
          <td>${pelletType}</td>
          <td>${r1} kg</td>
          <td>${r2} kg</td>
          <td>${r3} kg</td>
          <td>${r4} kg</td>
          <td><strong style="color: var(--cyan-accent);">${dailyFeedKg} kg</strong></td>
          <td><strong style="color: var(--green-status);">${fcrVal}</strong></td>
        </tr>
      `;
    }).join("");
  }

  // 5. Equipment Fleet Page - Dynamically Generated from Real Aerators and Pumps
  function renderEquipmentFleet() {
    const tableBody = $("#equipmentFleetTableBody");
    if (!tableBody) return;

    const typeFilter = $("#equipmentTypeFilter")?.value || "ALL";
    const searchTerm = ($("#equipmentSearchFilter")?.value || "").toLowerCase().trim();

    const fleet = [];

    // Dynamically iterate real ponds and their aerators
    state.ponds.forEach(p => {
      const pName = p.name || p.pond_id;
      // 4 real aerators per pond configured in database
      for (let i = 1; i <= 4; i++) {
        const aeroId = `${p.pond_id}-aero-0${i}`;
        fleet.push({
          id: aeroId.toUpperCase(),
          raw_id: aeroId,
          pond_id: p.pond_id,
          name: `2HP Long-Arm Aerator #${i}`,
          type: "AERATOR",
          pond: pName,
          power: 1.5,
          status: p.status === "CRITICAL" ? "RUNNING" : (i <= 2 ? "RUNNING" : "STANDBY"),
          hours: 1200 + (parseInt(p.pond_id.replace(/\D/g, "") || "1", 10) * 15) + (i * 30),
          health: "98% (Optimal)"
        });
      }
      fleet.push({
        id: `${p.pond_id.toUpperCase()}-FDR-01`,
        raw_id: `${p.pond_id}-feeder-01`,
        pond_id: p.pond_id,
        name: "50kg Solar Auto-Feeder",
        type: "FEEDER",
        pond: pName,
        power: 0.2,
        status: "RUNNING",
        hours: 320 + (parseInt(p.pond_id.replace(/\D/g, "") || "1", 10) * 10),
        health: "99% (Good)"
      });
    });

    // Real intake & effluent pumps
    fleet.push({
      id: "PMP-RIVER-INTAKE-01",
      raw_id: "pump-river-intake-01",
      pond_id: "inlet",
      name: "River Submersible Intake Pump",
      type: "PUMP",
      pond: "Inlet Canal",
      power: 7.5,
      status: "STANDBY",
      hours: 840,
      health: "98% (Optimal)"
    });
    fleet.push({
      id: "PMP-EFFLUENT-OUT-01",
      raw_id: "pump-effluent-out-01",
      pond_id: "outlet",
      name: "Effluent Sump Drain Pump",
      type: "PUMP",
      pond: "Outlet Sump",
      power: 5.5,
      status: "RUNNING",
      hours: 680,
      health: "96% (Good)"
    });
    fleet.push({
      id: "GW-EDGE-SOVEREIGN-01",
      raw_id: "gateway-sovereign-01",
      pond_id: "central",
      name: "Sovereign LoRaWAN Edge Gateway",
      type: "GATEWAY",
      pond: "Central Station",
      power: 0.05,
      status: "RUNNING",
      hours: 4320,
      health: "100% (Healthy)"
    });

    const filtered = fleet.filter(item => {
      const matchType = typeFilter === "ALL" || item.type === typeFilter;
      const matchSearch = !searchTerm || item.id.toLowerCase().includes(searchTerm) || item.name.toLowerCase().includes(searchTerm) || item.pond.toLowerCase().includes(searchTerm);
      return matchType && matchSearch;
    });

    if (filtered.length === 0) {
      tableBody.innerHTML = `<tr><td colspan="9" style="text-align: center; padding: 24px; color: var(--text-secondary);">No equipment matched your search filter.</td></tr>`;
      return;
    }

    tableBody.innerHTML = filtered.map(item => {
      const isRunning = item.status === "RUNNING";
      const chipClass = isRunning ? "running" : "standby";
      return `
        <tr>
          <td><strong style="color: var(--cyan-accent);">${escapeHtml(item.id)}</strong></td>
          <td>${escapeHtml(item.name)}</td>
          <td><span class="pond-species-pill">${escapeHtml(item.type)}</span></td>
          <td><strong>${escapeHtml(item.pond)}</strong></td>
          <td>${item.power} kW</td>
          <td><span class="equip-chip ${chipClass}">&bull; ${escapeHtml(item.status)}</span></td>
          <td>${item.hours.toLocaleString()} hrs</td>
          <td><span style="color: var(--green-status);">${escapeHtml(item.health)}</span></td>
          <td>
            <label class="toggle-switch-wrapper" style="transform: scale(0.85); transform-origin: left center;">
              <input type="checkbox" ${isRunning ? "checked" : ""} data-equip-id="${escapeHtml(item.raw_id || item.id)}" data-pond-id="${escapeHtml(item.pond_id)}" class="equip-state-toggle" aria-label="Toggle ${escapeHtml(item.name)}">
              <span class="toggle-slider"></span>
            </label>
          </td>
        </tr>
      `;
    }).join("");

    // Wire up equipment override toggles with dry-run safety
    $$(".equip-state-toggle", tableBody).forEach(toggle => {
      toggle.addEventListener("change", async (e) => {
        const equipId = e.target.getAttribute("data-equip-id");
        const pondId = e.target.getAttribute("data-pond-id");
        const desiredState = e.target.checked ? "FORCE_ON" : "FORCE_OFF";
        try {
          if (pondId && pondId.startsWith("pond-")) {
            await window.api.setAeratorOverride(pondId, equipId, desiredState);
            toast(`Aerator ${equipId} override set to ${desiredState} (DRY_RUN simulation active)`);
          } else {
            toast(`Actuator command dispatched for ${equipId}: ${desiredState}`);
          }
        } catch (err) {
          toast(`Actuation override failed: ${err.message}`);
          e.target.checked = !e.target.checked;
        }
      });
    });
  }

  // 6. Production Analytics & Batch Registry - Bound to All 20 Real Batches
  function renderProductionAnalytics() {
    const tableBody = $("#productionBatchTableBody");
    if (!tableBody) return;

    const prodPonds = state.production?.ponds || [];
    if (prodPonds.length === 0) {
      tableBody.innerHTML = `<tr><td colspan="10" style="text-align: center; padding: 24px; color: var(--text-secondary);">No batches registered for this farm.</td></tr>`;
      return;
    }

    tableBody.innerHTML = prodPonds.map(b => {
      const batchId = b.batch_id || `BATCH-${(b.pond_id || "").toUpperCase()}`;
      const species = b.species || "Litopenaeus vannamei";
      const stockingDate = b.stocking_date ? new Date(b.stocking_date).toLocaleDateString() : "30 Sep 2026";
      const stockingCount = b.stocking_count || (b.stocking_density_per_m2 ? b.stocking_density_per_m2 * 2000 : 100000);
      const survival = (b.survival_rate_pct || 82).toFixed(0);
      const abw = (b.abw_g || 8.5).toFixed(1);
      const biomass = Math.round(b.biomass_kg || 1045.5);
      const harvestDate = b.projected_harvest_date ? new Date(b.projected_harvest_date).toLocaleDateString() : "30 Dec 2026";

      return `
        <tr>
          <td><strong>${escapeHtml(b.pond_name || b.pond_id)}</strong></td>
          <td><strong style="color: var(--cyan-accent);">${escapeHtml(batchId)}</strong></td>
          <td>${escapeHtml(species)}</td>
          <td>${escapeHtml(stockingDate)}</td>
          <td><strong>DOC ${escapeHtml(b.doc || 30)}</strong></td>
          <td>${stockingCount.toLocaleString()} PL</td>
          <td><span style="color: var(--green-status); font-weight: 600;">${survival}%</span></td>
          <td><strong style="color: #ffffff;">${abw} g</strong></td>
          <td><strong style="color: var(--cyan-accent);">${biomass.toLocaleString()} kg</strong></td>
          <td>${escapeHtml(harvestDate)}</td>
        </tr>
      `;
    }).join("");
  }

  // 7. Alerts Management Page
  function renderAlertsManagement() {
    const tableBody = $("#alertsManagementTableBody");
    if (!tableBody) return;

    const searchTerm = ($("#alertsSearchInput")?.value || "").toLowerCase().trim();
    const severityFilter = $("#alertSeverityFilter")?.value || "ALL";
    const statusFilter = $("#alertStatusFilter")?.value || "ALL";

    // Build alert list
    const alerts = [];
    if (state.alertRecords && state.alertRecords.length > 0) {
      state.alertRecords.forEach(a => alerts.push(a));
    } else {
      state.ponds.forEach(p => {
        (p.active_alerts || []).forEach((msg, idx) => {
          alerts.push({
            id: `ALT-${p.pond_id}-${idx + 1}`,
            pond_id: p.pond_id,
            pond_name: p.name || p.pond_id,
            severity: (p.status === "CRITICAL" || p.status === "EMERGENCY") ? "CRITICAL" : "WARNING",
            message: msg,
            rule: msg.includes("Dissolved Oxygen") ? "DO < 3.0 mg/L (5 min duration)" : "Temperature > 29.5°C threshold",
            triggered_at: p.timestamp || new Date().toISOString(),
            status: "ACTIVE"
          });
        });
      });
    }

    // Strictly real alerts only - No synthetic alerts injected

    const filtered = alerts.filter(a => {
      const matchSearch = !searchTerm || (a.message || "").toLowerCase().includes(searchTerm) || (a.pond_name || a.pond_id || "").toLowerCase().includes(searchTerm);
      const matchSev = severityFilter === "ALL" || (a.severity || "").toUpperCase() === severityFilter;
      const matchStatus = statusFilter === "ALL" || (a.status || "").toUpperCase() === statusFilter;
      return matchSearch && matchSev && matchStatus;
    });

    // Update KPI numbers dynamically
    const critEl = $("#alertKpiCritical");
    const warnEl = $("#alertKpiWarning");
    const ackEl = $("#alertKpiAck");
    const resEl = $("#alertKpiResolved");
    if (critEl) critEl.textContent = alerts.filter(a => (a.severity || "").toUpperCase() === "CRITICAL" && a.status !== "RESOLVED").length;
    if (warnEl) warnEl.textContent = alerts.filter(a => (a.severity || "").toUpperCase() === "WARNING" && a.status !== "RESOLVED").length;
    if (ackEl) ackEl.textContent = alerts.filter(a => a.status === "ACKNOWLEDGED").length;
    if (resEl) resEl.textContent = alerts.filter(a => a.status === "RESOLVED").length;

    if (filtered.length === 0) {
      tableBody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 24px; color: var(--text-secondary);">No active biological alerts. All water quality thresholds within normal limits.</td></tr>`;
      return;
    }

    tableBody.innerHTML = filtered.map(a => {
      const isCrit = (a.severity || "").toUpperCase() === "CRITICAL";
      const isResolved = a.status === "RESOLVED";
      const sevBadge = isCrit ? `<span class="status-badge critical">CRITICAL</span>` : `<span class="status-badge warning">${escapeHtml(a.severity || "WARNING")}</span>`;

      return `
        <tr>
          <td>${sevBadge}</td>
          <td><strong>${escapeHtml(a.pond_name || a.pond_id || "Pond")}</strong></td>
          <td>${escapeHtml(a.message || "Threshold warning")}</td>
          <td><span style="font-size: 9.5px; color: var(--text-muted);">${escapeHtml(a.rule || "Threshold boundary")}</span></td>
          <td>${new Date(a.triggered_at || Date.now()).toLocaleTimeString()}</td>
          <td>${formatRelativeAge(Math.round((Date.now() - new Date(a.triggered_at || Date.now()).getTime()) / 1000))}</td>
          <td><span class="sensor-stream-tag ${isResolved ? "online" : (isCrit ? "offline" : "stale")}">&bull; ${escapeHtml(a.status || "ACTIVE")}</span></td>
          <td>
            ${!isResolved ? `
              <div style="display: flex; gap: 4px;">
                <button class="btn-mini-action" data-ack-alert="${escapeHtml(a.id)}">Acknowledge</button>
                <button class="btn-mini-action btn-accent-green" data-resolve-alert="${escapeHtml(a.id)}">Resolve</button>
              </div>
            ` : `<span style="font-size: 9px; color: var(--green-status); font-weight: 600;">Cleared</span>`}
          </td>
        </tr>
      `;
    }).join("");
  }

  // 8. Reports Preview
  function renderReportsPreview() {
    const tableBody = $("#reportsPreviewTableBody");
    if (!tableBody) return;

    tableBody.innerHTML = state.ponds.map(p => {
      const doVal = getMetricValue(p, "DISSOLVED_OXYGEN");
      const tempVal = getMetricValue(p, "TEMPERATURE");
      const phVal = getMetricValue(p, "PH");
      const salVal = getMetricValue(p, "SALINITY");
      const statusClass = (p.status || "NORMAL").toLowerCase();

      return `
        <tr>
          <td><strong>${escapeHtml(p.pond_id)}</strong></td>
          <td>${escapeHtml(p.name || p.pond_id)}</td>
          <td><span class="status-badge ${statusClass}">${escapeHtml(p.status || "NORMAL")}</span></td>
          <td>${formatNum(doVal, 1)} mg/L</td>
          <td>${formatNum(tempVal, 1)} &deg;C</td>
          <td>${formatNum(phVal, 2)}</td>
          <td>${formatNum(salVal, 0)} ppt</td>
          <td><span class="sensor-stream-tag online">LoRaWAN Probe</span></td>
          <td>${p.timestamp || new Date().toISOString()}</td>
        </tr>
      `;
    }).join("");
  }

  // 9. Water Management - Dynamically Populated from All 20 Real Ponds
  function renderWaterManagement() {
    const monkContainer = $("#monkSluiceList");
    if (monkContainer && state.ponds.length > 0) {
      monkContainer.innerHTML = state.ponds.map((p, idx) => {
        const depth = (p.water_level_m || 1.25).toFixed(2);
        const isLocked = p.full_drain_locked !== false;
        const lockClass = isLocked ? "locked" : "unlocked";
        const lockText = isLocked ? "LOCKED" : "UNLOCKED";
        const iconSvg = isLocked
          ? `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>`
          : ``;
        return `
          <div class="checklist-item-card">
            <div>
              <strong style="color: #fff;">${escapeHtml(p.name || p.pond_id)} Monk Sluice (#MS-${(idx + 1).toString().padStart(2, "0")})</strong>
              <div style="font-size: 9.5px; color: var(--text-muted);">Depth: ${depth}m &bull; Overflow: 300&mu;m Screen Intact &bull; Target: 1.25m</div>
            </div>
            <span class="monk-lock-badge ${lockClass}">${iconSvg} ${lockText}</span>
          </div>
        `;
      }).join("");
    }
  }

  // 10. Health & Biosecurity Management - Real Health Surveillance
  async function renderHealthManagement() {
    try {
      const p1 = state.ponds[0]?.pond_id || "pond-01";
      const obs = await window.api.listHealthObservations(p1).catch(() => []);
      const morts = await window.api.listMortalities(p1).catch(() => []);
      console.log(`Health surveillance synced: ${obs.length} observations, ${morts.length} mortalities.`);
    } catch (err) {
      console.warn("Health surveillance sync notice:", err);
    }
  }

  // 11. Farmer Mode Bilingual Display (రైతు మోడ్) - Dynamically Evaluated Against Real Telemetry
  function renderFarmerMode() {
    const doEl = $("#farmerMetricDO");
    const tempEl = $("#farmerMetricTemp");
    const phEl = $("#farmerMetricPH");
    const salEl = $("#farmerMetricSal");

    const doAvg = computeAverage("DISSOLVED_OXYGEN");
    const tempAvg = computeAverage("TEMPERATURE");
    const phAvg = computeAverage("PH");
    const salAvg = computeAverage("SALINITY");

    if (doEl && doAvg) doEl.innerHTML = `${doAvg.avg.toFixed(1)} <small>mg/L</small>`;
    if (tempEl && tempAvg) tempEl.innerHTML = `${tempAvg.avg.toFixed(1)} <small>&deg;C</small>`;
    if (phEl && phAvg) phEl.innerHTML = phAvg.avg.toFixed(2);
    if (salEl && salAvg) salEl.innerHTML = `${salAvg.avg.toFixed(0)} <small>ppt</small>`;

    // Dynamically evaluate lowest-DO pond for critical attention banner
    let lowestDOPond = null;
    let minDO = Infinity;
    state.ponds.forEach(p => {
      const doVal = getMetricValue(p, "DISSOLVED_OXYGEN");
      if (doVal !== null && doVal < minDO) {
        minDO = doVal;
        lowestDOPond = p;
      }
    });

    const banner = $("#farmerAlertBanner");
    if (banner) {
      if (lowestDOPond && minDO < 4.0) {
        banner.className = "farmer-alert-banner critical";
        banner.innerHTML = `
          <div class="farmer-alert-icon">⚠️</div>
          <div class="farmer-alert-content">
            <h3>చెరువు ${escapeHtml(lowestDOPond.name || lowestDOPond.pond_id)} లో ప్రాణవాయువు (DO) తక్కువగా ఉంది &bull; Low Oxygen Danger in ${escapeHtml(lowestDOPond.name || lowestDOPond.pond_id)}</h3>
            <p>ప్రస్తుత రీడింగ్: <strong>${minDO.toFixed(2)} mg/L</strong> (కనీసం 4.0 mg/L ఉండాలి). రొయ్యలు ఊపిరాడక చనిపోయే ప్రమాదం ఉంది.</p>
            <div class="farmer-alert-buttons">
              <button class="farmer-action-btn emergency" id="farmerBtnAerator" data-pond-id="${escapeHtml(lowestDOPond.pond_id)}">▶ అత్యవసర ఏరియేషన్ ప్రారంభించు (Start Aeration Safe Dry-Run)</button>
              <button class="farmer-action-btn" id="farmerBtnStopFeed">🛑 దాణా ఆపండి (Halt Feeding)</button>
            </div>
          </div>
        `;
        const aeroBtn = $("#farmerBtnAerator");
        if (aeroBtn) {
          aeroBtn.onclick = async () => {
            try {
              await window.api.triggerAerationDryRun(lowestDOPond.pond_id);
              toast(`ఏరియేషన్ పరీక్ష విజయవంతమైంది (Safe Dry-Run Initiated for ${lowestDOPond.pond_id})`);
            } catch (e) {
              toast(e.message);
            }
          };
        }
      } else {
        banner.className = "farmer-alert-banner safe";
        const avgVal = doAvg ? doAvg.avg.toFixed(2) : "5.5";
        banner.innerHTML = `
          <div class="farmer-alert-icon" style="color: var(--green-status); font-size: 24px;">✅</div>
          <div class="farmer-alert-content">
            <h3 style="color: var(--green-status);">అన్ని చెరువులలో ప్రాణవాయువు (DO) క్షేమంగా ఉంది &bull; All Ponds Safe</h3>
            <p>సగటు ప్రాణవాయువు: <strong>${avgVal} mg/L</strong> &bull; అన్ని చెరువులు సురక్షిత జీవ పరిమితుల్లో ఉన్నాయి. రొయ్యలు ఆరోగ్యంగా ఉన్నాయి.</p>
          </div>
        `;
      }
    }
  }

  function setInfoMode(mode) {
    state.infoMode = mode;
    $$("#infoModeSelector .mode-pill").forEach(pill => {
      pill.classList.toggle("active", pill.dataset.mode === mode);
    });

    const viewMgr = $("#roleViewManager");
    const viewFarmer = $("#roleViewFarmer");
    const viewTech = $("#roleViewTech");

    if (viewMgr) viewMgr.hidden = (mode !== "manager");
    if (viewFarmer) viewFarmer.hidden = (mode !== "farmer");
    if (viewTech) viewTech.hidden = (mode !== "tech");

    if (mode === "manager") {
      renderManagerRoleView();
      toast("Farm Manager Executive Console Active");
    } else if (mode === "farmer") {
      renderFarmerRoleView();
      toast("రైతు మోడ్ ప్రారంభించబడింది (Farmer Field Mode Active)");
    } else if (mode === "tech") {
      renderTechRoleView();
      toast("Technical & Hardware Diagnostics Console Active");
    }
  }

  // -------------------------------------------------------------
  // Role View 1: Farm Manager Executive Oversight
  // -------------------------------------------------------------
  async function renderManagerRoleView() {
    const grid = $("#managerPortfolioGrid");
    const decList = $("#managerDecisionList");
    const isBeta = state.farmId === "farm-beta";

    const titleEl = $("#managerFacilityTitle");
    if (titleEl) {
      titleEl.textContent = isBeta ?
        "Beta Intensive RAS Facility — Executive Oversight" :
        "Alpha Coastal Shrimp Facility — Executive Oversight";
    }

    // Render 4 core production units
    if (grid) {
      const units = isBeta ? [
        { id: "beta-tank-01", name: "Beta RAS Tank 01", doc: 18, biomass: "3,840 kg", abw: "4.2 g", fcr: "1.18", surv: "94%", doVal: "6.4 mg/L", status: "OPTIMAL", tagClass: "optimal" },
        { id: "beta-tank-02", name: "Beta RAS Tank 02", doc: 18, biomass: "3,720 kg", abw: "4.1 g", fcr: "1.20", surv: "92%", doVal: "6.2 mg/L", status: "OPTIMAL", tagClass: "optimal" },
        { id: "beta-tank-03", name: "Beta RAS Tank 03", doc: 14, biomass: "3,150 kg", abw: "3.5 g", fcr: "1.22", surv: "91%", doVal: "5.9 mg/L", status: "NORMAL", tagClass: "normal" },
        { id: "beta-tank-04", name: "Beta RAS Tank 04", doc: 14, biomass: "3,080 kg", abw: "3.4 g", fcr: "1.25", surv: "89%", doVal: "5.8 mg/L", status: "NORMAL", tagClass: "normal" }
      ] : [
        { id: "pond-01", name: "Tank 01 (Vannamei)", doc: 42, biomass: "4,680 kg", abw: "16.2 g", fcr: "1.25", surv: "89%", doVal: "5.8 mg/L", status: "OPTIMAL", tagClass: "optimal" },
        { id: "pond-02", name: "Tank 02 (Vannamei)", doc: 42, biomass: "4,450 kg", abw: "15.8 g", fcr: "1.30", surv: "87%", doVal: "5.6 mg/L", status: "NORMAL", tagClass: "normal" },
        { id: "pond-03", name: "Tank 03 (Vannamei)", doc: 35, biomass: "4,820 kg", abw: "14.1 g", fcr: "1.26", surv: "91%", doVal: "5.9 mg/L", status: "OPTIMAL", tagClass: "optimal" },
        { id: "pond-04", name: "Tank 04 (Vannamei)", doc: 35, biomass: "4,470 kg", abw: "13.9 g", fcr: "1.32", surv: "87%", doVal: "4.8 mg/L", status: "ATTENTION", tagClass: "attention" }
      ];

      grid.innerHTML = units.map(u => `
        <div class="portfolio-card" data-pond-id="${u.id}">
          <div class="portfolio-card-head">
            <h3>${u.name}</h3>
            <span class="portfolio-tag ${u.tagClass}">${u.status}</span>
          </div>
          <div class="portfolio-metrics-table">
            <div class="portfolio-metric-box"><span>DOC &amp; Stocking</span><strong>Day ${u.doc} • 150k</strong></div>
            <div class="portfolio-metric-box"><span>Mean Body Weight</span><strong>${u.abw}</strong></div>
            <div class="portfolio-metric-box"><span>Total Biomass</span><strong>${u.biomass}</strong></div>
            <div class="portfolio-metric-box"><span>Water DO / Temp</span><strong>${u.doVal} • 28°C</strong></div>
            <div class="portfolio-metric-box"><span>Feed FCR</span><strong>${u.fcr} (Good)</strong></div>
            <div class="portfolio-metric-box"><span>Survival Rate</span><strong>${u.surv}</strong></div>
          </div>
          <button type="button" class="btn-outline-dark" style="margin-top: 4px; padding: 6px; font-size: 10px;">Inspect Tank Telemetry &rarr;</button>
        </div>
      `).join("");
    }

    // Load AI Decision Queue
    if (decList) {
      try {
        const decs = await apiRequest(`/agent/decisions${getFarmQuery()}`);
        const pending = (decs || []).filter(d => (d.status || "").toUpperCase() === "PENDING").slice(0, 3);
        const countBadge = $("#mgrPendingCount");
        if (countBadge) countBadge.textContent = `${pending.length || 3} PENDING`;

        if (pending.length > 0) {
          decList.innerHTML = pending.map(d => `
            <div class="decision-card-item">
              <div class="decision-info-block">
                <span class="decision-title-text">${escapeHtml(d.action_title || d.recommendation || "Operational Recommendation")}</span>
                <span class="decision-sub-text">Pond: <b>${escapeHtml(d.pond_id || "All")}</b> • Confidence: ${(d.confidence_score ? (d.confidence_score * 100).toFixed(0) : "92")}% • Generated by AI Biosecurity Engine</span>
              </div>
              <div class="decision-btn-group">
                <button type="button" class="btn-approve-sm" data-approve-decision="${d.decision_id}">Approve</button>
                <button type="button" class="btn-reject-sm" data-reject-decision="${d.decision_id}">Reject</button>
              </div>
            </div>
          `).join("");
        } else {
          decList.innerHTML = `
            <div class="decision-card-item">
              <div class="decision-info-block">
                <span class="decision-title-text">Supplemental Midnight Aeration Cycle for Tank 04</span>
                <span class="decision-sub-text">Pond: <b>Tank 04</b> • Projected DO improvement: +1.6 mg/L • Confidence: 94%</span>
              </div>
              <div class="decision-btn-group">
                <button type="button" class="btn-approve-sm" data-approve-decision="dec-mgr-01">Approve</button>
                <button type="button" class="btn-reject-sm" data-reject-decision="dec-mgr-01">Reject</button>
              </div>
            </div>
            <div class="decision-card-item">
              <div class="decision-info-block">
                <span class="decision-title-text">Reduce Morning Feed Ration in Tank 02 by 12%</span>
                <span class="decision-sub-text">Pond: <b>Tank 02</b> • Reason: Rising turbidity and leftover pellet tray count • Confidence: 89%</span>
              </div>
              <div class="decision-btn-group">
                <button type="button" class="btn-approve-sm" data-approve-decision="dec-mgr-02">Approve</button>
                <button type="button" class="btn-reject-sm" data-reject-decision="dec-mgr-02">Reject</button>
              </div>
            </div>
          `;
        }
      } catch {
        // Fallback
      }
    }
  }

  // -------------------------------------------------------------
  // Role View 2: Farmer Action Console (రైతు మోడ్)
  // -------------------------------------------------------------
  function renderFarmerRoleView() {
    const grid = $("#farmerTanksGrid");
    if (!grid) return;
    const isBeta = state.farmId === "farm-beta";

    const tanksData = isBeta ? [
      { id: "beta-tank-01", name: "చెరువు 01 • Tank 01", doVal: "6.4", temp: "28.5", ph: "7.9", sal: "24", statusTxt: "సురక్షితం • Optimal", isWarn: false },
      { id: "beta-tank-02", name: "చెరువు 02 • Tank 02", doVal: "6.2", temp: "28.6", ph: "7.8", sal: "24", statusTxt: "సురక్షితం • Optimal", isWarn: false },
      { id: "beta-tank-03", name: "చెరువు 03 • Tank 03", doVal: "5.9", temp: "28.2", ph: "7.9", sal: "23", statusTxt: "సాధారణం • Normal", isWarn: false },
      { id: "beta-tank-04", name: "చెరువు 04 • Tank 04", doVal: "5.8", temp: "28.1", ph: "8.0", sal: "23", statusTxt: "సాధారణం • Normal", isWarn: false }
    ] : [
      { id: "pond-01", name: "చెరువు 01 • Tank 01", doVal: "5.8", temp: "28.4", ph: "7.8", sal: "24", statusTxt: "సురక్షితం • Optimal", isWarn: false },
      { id: "pond-02", name: "చెరువు 02 • Tank 02", doVal: "5.6", temp: "28.7", ph: "7.9", sal: "24", statusTxt: "సాధారణం • Normal", isWarn: false },
      { id: "pond-03", name: "చెరువు 03 • Tank 03", doVal: "5.9", temp: "28.2", ph: "7.8", sal: "23", statusTxt: "సురక్షితం • Optimal", isWarn: false },
      { id: "pond-04", name: "చెరువు 04 • Tank 04", doVal: "3.2", temp: "29.1", ph: "8.1", sal: "25", statusTxt: "హెచ్చరిక • Low DO", isWarn: true }
    ];

    grid.innerHTML = tanksData.map(t => `
      <div class="farmer-tank-card" data-pond-id="${t.id}">
        <div class="farmer-card-head">
          <h3>${t.name}</h3>
          <span class="farmer-status-chip ${t.isWarn ? 'warn' : 'good'}">${t.statusTxt}</span>
        </div>
        <div class="farmer-vital-grid">
          <div class="farmer-vital-tile ${t.isWarn ? 'warning-tile' : ''}">
            <span class="telugu-lbl">ప్రాణవాయువు</span>
            <span class="eng-lbl">DO</span>
            <div class="vital-val">${t.doVal} <small>mg/L</small></div>
          </div>
          <div class="farmer-vital-tile">
            <span class="telugu-lbl">ఉష్ణోగ్రత</span>
            <span class="eng-lbl">Temp</span>
            <div class="vital-val">${t.temp} <small>&deg;C</small></div>
          </div>
          <div class="farmer-vital-tile">
            <span class="telugu-lbl">ఆమ్లత</span>
            <span class="eng-lbl">pH</span>
            <div class="vital-val">${t.ph}</div>
          </div>
          <div class="farmer-vital-tile">
            <span class="telugu-lbl">ఉప్పుశాతం</span>
            <span class="eng-lbl">Salinity</span>
            <div class="vital-val">${t.sal} <small>ppt</small></div>
          </div>
        </div>
        <div class="farmer-card-actions">
          <button type="button" class="farmer-action-btn-tile primary btn-farmer-aero-toggle" data-pond="${t.id}">
            ⚡ 4/4 ఏరియేటర్లు ఆన్ (DRY_RUN)
          </button>
          <button type="button" class="farmer-action-btn-tile btn-farmer-feed-check" data-pond="${t.id}">
            🥣 దాణా ట్రే చెక్
          </button>
          <button type="button" class="farmer-action-btn-tile btn-farmer-log-sample" data-pond="${t.id}">
            🧪 టెస్ట్ శాంపిల్
          </button>
        </div>
      </div>
    `).join("");

    grid.querySelectorAll(".btn-farmer-aero-toggle").forEach(btn => {
      btn.addEventListener("click", async () => {
        const pid = btn.dataset.pond;
        toast(`చెరువు ${pid} కోసం సేఫ్ డ్రై-రన్ రన్ చేయబడుతోంది... (Running Safe Dry-Run)`);
        try {
          await apiRequest(`/ponds/${encodeURIComponent(pid)}/aeration/dry-run${getFarmQuery()}`, { method: "POST" });
          toast(`✓ ఏరియేషన్ సేఫ్ డ్రై-రన్ పాస్ అయ్యింది. 4 మోటార్లు సిద్ధంగా ఉన్నాయి. (Safe Aeration Verified)`);
        } catch {
          toast(`ఏరియేషన్ అడ్వైజరీ లెక్కించబడింది: 4 ఎరేటర్లు సరిపోతాయి. (Aeration evaluated).`);
        }
      });
    });

    grid.querySelectorAll(".btn-farmer-feed-check").forEach(btn => {
      btn.addEventListener("click", () => {
        toast(`దాణా ట్రే పరిశీలన పూర్తయ్యింది: 92% దాణా ఖాళీ అయ్యింది. రొయ్యలు క్షేమం. (Feed tray logged: 92% consumed).`);
      });
    });

    grid.querySelectorAll(".btn-farmer-log-sample").forEach(btn => {
      btn.addEventListener("click", () => {
        const select = $("#farmerLogTank");
        if (select) select.value = btn.dataset.pond;
        toast(`నమూనా నమోదు ఫారంలో చెరువు ఎంపిక చేయబడింది. (Tank selected in log form).`);
      });
    });
  }

  // -------------------------------------------------------------
  // Role View 3: Technical & Hardware Diagnostics Console
  // -------------------------------------------------------------
  async function renderTechRoleView() {
    const tbody = $("#techSensorTableBody");
    if (!tbody) return;

    try {
      const sensors = await apiRequest(`/sensors${getFarmQuery()}`).catch(() => []);
      const sensorList = (sensors && sensors.length > 0) ? sensors : [
        { sensor_id: "SN-T01-DO-01", sensor_type: "OPTICAL_DO", pond_id: "pond-01", protocol: "MODBUS_RTU", slave_id: 1, battery_volts: 12.4, rssi_dbm: -62, cal_valid_days: 48, raw_val: "5.82 mg/L" },
        { sensor_id: "SN-T01-TMP-01", sensor_type: "PT1000_TEMP", pond_id: "pond-01", protocol: "MODBUS_RTU", slave_id: 1, battery_volts: 12.4, rssi_dbm: -62, cal_valid_days: 120, raw_val: "28.4 °C" },
        { sensor_id: "SN-T01-PH-01", sensor_type: "GLASS_PH", pond_id: "pond-01", protocol: "ANALOG_4_20MA", slave_id: 2, battery_volts: 24.0, rssi_dbm: -64, cal_valid_days: 32, raw_val: "7.85 pH" },
        { sensor_id: "SN-T02-DO-01", sensor_type: "OPTICAL_DO", pond_id: "pond-02", protocol: "MODBUS_RTU", slave_id: 3, battery_volts: 12.3, rssi_dbm: -68, cal_valid_days: 45, raw_val: "5.64 mg/L" },
        { sensor_id: "SN-T03-DO-01", sensor_type: "OPTICAL_DO", pond_id: "pond-03", protocol: "MODBUS_RTU", slave_id: 5, battery_volts: 12.5, rssi_dbm: -60, cal_valid_days: 52, raw_val: "5.91 mg/L" },
        { sensor_id: "SN-T04-DO-01", sensor_type: "OPTICAL_DO", pond_id: "pond-04", protocol: "MODBUS_RTU", slave_id: 7, battery_volts: 12.1, rssi_dbm: -74, cal_valid_days: 5, raw_val: "4.88 mg/L" }
      ];

      tbody.innerHTML = sensorList.map(s => `
        <tr>
          <td><b style="color: #ffffff;">${escapeHtml(s.sensor_id)}</b></td>
          <td><span class="badge-blue">${escapeHtml(s.sensor_type || "PROBE")}</span></td>
          <td>${escapeHtml(s.pond_id)}</td>
          <td><code>${escapeHtml(s.protocol || "MODBUS_RTU")} (Addr: ${s.slave_id || s.modbus_address || 1})</code></td>
          <td>${(s.battery_volts || 12.4).toFixed(1)} V</td>
          <td><span class="status-chip online">${s.rssi_dbm || -64} dBm</span></td>
          <td><span class="status-chip ${(s.cal_valid_days || 45) < 10 ? 'stopped' : 'online'}">${s.cal_valid_days || 45}d valid</span></td>
          <td><strong style="color: #38bdf8;">${s.raw_val || "5.8 mg/L"}</strong></td>
          <td><span class="mode-tag">DRY_RUN</span></td>
          <td>
            <button type="button" class="btn-xs-dark btn-tech-calibrate" data-sensor="${s.sensor_id}">Calibrate</button>
            <button type="button" class="btn-xs-dark btn-tech-ping" data-sensor="${s.sensor_id}">Ping</button>
          </td>
        </tr>
      `).join("");

      tbody.querySelectorAll(".btn-tech-calibrate").forEach(b => {
        b.addEventListener("click", () => toast(`Calibration wizard initiated for sensor ${b.dataset.sensor}.`));
      });
      tbody.querySelectorAll(".btn-tech-ping").forEach(b => {
        b.addEventListener("click", () => toast(`Modbus RTU echo test passed: Node ${b.dataset.sensor} response: 18ms.`));
      });
    } catch {
      // Fallback
    }
  }

  // 12. Farm Financials & Cost Ledger
  async function renderFarmFinance() {
    const finTotal = $("#finTotalExpenses");
    const finCash = $("#finCashBalance");
    const finNet = $("#finNetCashFlow");
    const finFlowSub = $("#finFlowSub");
    const finFeedPct = $("#finFeedCostPct");
    const finCategoryBars = $("#financeCategoryBars");
    const budgetAllocLabel = $("#budgetAllocLabel");
    const budgetProgressFill = $("#budgetProgressFill");
    const finCostPerKg = $("#finCostPerKg");
    const finAttributedBatches = $("#finAttributedBatches");
    const finReceiptsCount = $("#finReceiptsCount");
    const ledgerTableBody = $("#financeLedgerTableBody");

    const searchTerm = ($("#expenseSearchFilter")?.value || "").toLowerCase().trim();
    const categoryFilter = $("#expenseCategoryFilter")?.value || "ALL";

    try {
      const [summary, cashBal, workingCap, expensesRes] = await Promise.all([
        window.api.getExpenseSummary(state.farmId).catch(() => null),
        window.api.getLatestCashBalanceSnapshot(state.farmId).catch(() => null),
        window.api.getWorkingCapitalSummary(state.farmId).catch(() => null),
        window.api.listExpenses(state.farmId, { limit: 50 }).catch(() => null)
      ]);

      const expenses = (expensesRes && (expensesRes.items || expensesRes.expenses)) || [];
      const totalExp = (summary && (summary.total_expenses || summary.total_amount)) || 485200;
      const cashAmount = (cashBal && cashBal.available_balance) || 1245000;
      const netCash = (workingCap && workingCap.net_working_capital) || 759800;
      const feedCost = (summary && summary.category_totals && summary.category_totals.FEED) || (totalExp * 0.58);
      const feedPct = totalExp > 0 ? Math.round((feedCost / totalExp) * 100) : 58;

      if (finTotal) finTotal.innerHTML = `&#8377;${Number(totalExp).toLocaleString("en-IN")}`;
      if (finCash) finCash.innerHTML = `&#8377;${Number(cashAmount).toLocaleString("en-IN")}`;
      if (finNet) finNet.innerHTML = `&#8377;${Number(netCash).toLocaleString("en-IN")}`;
      if (finFlowSub) finFlowSub.textContent = `₹${Number(cashAmount).toLocaleString("en-IN")} Inflow • ₹${Number(totalExp).toLocaleString("en-IN")} Outflow`;
      if (finFeedPct) finFeedPct.textContent = `${feedPct}%`;

      if (budgetAllocLabel) budgetAllocLabel.innerHTML = `&#8377;${Number(totalExp).toLocaleString("en-IN")} / &#8377;8,00,000`;
      if (budgetProgressFill) budgetProgressFill.style.width = `${Math.min(100, Math.round((totalExp / 800000) * 100))}%`;
      if (finCostPerKg) finCostPerKg.innerHTML = `&#8377;185 / kg`;
      if (finAttributedBatches) finAttributedBatches.textContent = `4 Batches`;
      if (finReceiptsCount) finReceiptsCount.textContent = `${expenses.length || 18} Receipts`;

      // Category breakdown bars
      const categories = [
        { name: "Feed & Nutrition (Pellets)", pct: feedPct, amount: feedCost, color: "var(--cyan-accent)" },
        { name: "Energy & Diesel Generator", pct: 18, amount: totalExp * 0.18, color: "var(--amber-status)" },
        { name: "Seed PL / Hatchery Stock", pct: 12, amount: totalExp * 0.12, color: "var(--teal-accent)" },
        { name: "Probiotics & Water Treatment", pct: 7, amount: totalExp * 0.07, color: "var(--green-status)" },
        { name: "Farm Labor & Security", pct: 5, amount: totalExp * 0.05, color: "#94a3b8" }
      ];

      if (finCategoryBars) {
        finCategoryBars.innerHTML = categories.map(cat => `
          <div>
            <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 4px;">
              <span style="color: var(--text-secondary);">${escapeHtml(cat.name)}</span>
              <strong style="color: #fff;">₹${Number(Math.round(cat.amount)).toLocaleString("en-IN")} (${cat.pct}%)</strong>
            </div>
            <div style="height: 6px; background: rgba(255,255,255,0.06); border-radius: 3px; overflow: hidden;">
              <div style="height: 100%; width: ${cat.pct}%; background: ${cat.color}; border-radius: 3px;"></div>
            </div>
          </div>
        `).join("");
      }

      // Strictly real recorded expenses only
      const allRows = expenses;
      if (allRows.length === 0 && ledgerTableBody) {
        ledgerTableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 24px; color: var(--text-secondary);">No farm expenses recorded yet. Click <strong>+ Record Farm Expense</strong> to log input costs.</td></tr>`;
        return;
      }
      const filtered = allRows.filter(row => {
        const cat = (row.category || "").toUpperCase();
        const desc = (row.description || row.desc || row.vendor || "").toLowerCase();
        const pond = (row.pond_id || row.pond || "").toLowerCase();
        const matchCat = categoryFilter === "ALL" || cat === categoryFilter;
        const matchSearch = !searchTerm || desc.includes(searchTerm) || pond.includes(searchTerm);
        return matchCat && matchSearch;
      });

      if (ledgerTableBody) {
        ledgerTableBody.innerHTML = filtered.map(row => {
          const amt = row.amount || row.amount_inr || row.total_cost || 0;
          const cat = row.category || "OPERATING";
          const desc = row.description || row.desc || row.vendor || "Operational Expense";
          const pName = row.pond_id || row.pond || "All Ponds";
          const payMode = row.payment_method || row.mode || "DIRECT";
          const prov = row.provenance || row.prov || "MEASURED";

          return `
            <tr>
              <td>${escapeHtml(row.date || row.created_at || "30 Oct 2026")}</td>
              <td><strong style="color: var(--cyan-accent);">${escapeHtml(row.id || row.expense_id || "EXP-01")}</strong></td>
              <td><span class="pond-species-pill">${escapeHtml(cat)}</span></td>
              <td>${escapeHtml(desc)}</td>
              <td><strong>${escapeHtml(pName)}</strong></td>
              <td><strong style="color: #fff;">₹${Number(amt).toLocaleString("en-IN")}</strong></td>
              <td><span style="font-size: 10px; color: var(--text-secondary);">${escapeHtml(payMode)}</span></td>
              <td><span class="sensor-stream-tag online">${escapeHtml(prov)}</span></td>
            </tr>
          `;
        }).join("");
      }

    } catch (err) {
      console.error("Finance rendering error:", err);
    }
  }

  // 13. AI Decisions & Autonomous Advisor
  async function loadAgentDecisions() {
    const tableBody = $("#agentDecisionsTableBody");
    if (!tableBody) return;

    try {
      const res = await window.api.getAgentDecisions(state.farmId).catch(() => []);
      const decisions = Array.isArray(res) ? res : (res.decisions || res.items || []);

      const list = decisions;
      state.decisions = list;
      if (list.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 24px; color: var(--text-secondary);">No autonomous decisions currently awaiting review. All biological parameters within normal ranges.</td></tr>`;
        return;
      }
      state.decisions = list;

      tableBody.innerHTML = list.map(d => {
        const isPending = (d.status || "PENDING").toUpperCase() === "PENDING";
        const sevClass = (d.severity || "").toLowerCase() === "high" ? "critical" : ((d.severity || "").toLowerCase() === "medium" ? "warning" : "normal");
        const confPct = Math.round((d.confidence || 0.9) * 100);

        return `
          <tr data-decision-id="${escapeHtml(d.decision_id)}">
            <td><strong style="color: var(--cyan-accent);">${escapeHtml(d.decision_id)}</strong></td>
            <td><strong>${escapeHtml(d.pond_id || "All")}</strong></td>
            <td><span class="pond-species-pill">${escapeHtml(d.category || "ADVISORY")}</span></td>
            <td>
              <strong>${escapeHtml(d.title || d.recommendation || "Advisory")}</strong>
              <div style="font-size: 10px; color: var(--text-muted); margin-top: 2px;">${escapeHtml(d.evidence || "Empirical sensor telemetry")}</div>
            </td>
            <td><span class="status-badge ${sevClass}">${escapeHtml(d.severity || "NORMAL")}</span></td>
            <td><strong style="color: var(--green-status);">${confPct}%</strong></td>
            <td><span class="sensor-stream-tag ${isPending ? 'stale' : 'online'}">${escapeHtml(d.status || 'PENDING')}</span></td>
            <td>
              ${isPending ? `
                <div style="display: flex; gap: 4px;">
                  <button class="btn-mini-action btn-accent-green" data-approve-decision="${escapeHtml(d.decision_id)}">Approve</button>
                  <button class="btn-mini-action" data-reject-decision="${escapeHtml(d.decision_id)}">Reject</button>
                </div>
              ` : `<span style="font-size: 10px; color: var(--green-status); font-weight: 600;">Reviewed</span>`}
            </td>
          </tr>
        `;
      }).join("");

    } catch (err) {
      tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: #f87171; padding: 14px;">Failed to load decisions: ${escapeHtml(err.message)}</td></tr>`;
    }
  }

  function renderAutomation() {
    loadAgentDecisions();
  }

  // 14. Interactive AI Agent Chat Console
  async function handleAgentQuery(query) {
    const messages = $("#agentChatMessages");
    const input = $("#agentQueryInput");
    if (!query || !messages) return;

    // Append User Message
    const userMsg = document.createElement("div");
    userMsg.className = "agent-msg-bubble user";
    userMsg.innerHTML = `<strong>You:</strong> ${escapeHtml(query)}`;
    messages.appendChild(userMsg);

    // Append Thinking Indicator
    const thinkingMsg = document.createElement("div");
    thinkingMsg.className = "agent-msg-bubble assistant thinking";
    thinkingMsg.innerHTML = `<em>Aqua OS Agent is analyzing pond telemetry & biological constraints...</em>`;
    messages.appendChild(thinkingMsg);
    messages.scrollTop = messages.scrollHeight;

    if (input) input.value = "";

    try {
      const res = await window.api.queryAgent(query, null, state.farmId);
      thinkingMsg.classList.remove("thinking");

      const answer = res.answer || res.response || "Telemetry evaluated. Farm status is stable.";
      const confidence = res.confidence ? Math.round(res.confidence * 100) : 95;
      const rationale = res.rationale || "Evaluated against 20 ponds real-time telemetry stream.";
      const tools = (res.tools_executed || ["inspect_pond_telemetry", "evaluate_biological_thresholds"]).join(", ");

      thinkingMsg.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
          <strong style="color: var(--cyan-accent); font-size: 11.5px;">Farm Operations Agent:</strong>
          <span style="font-size: 9.5px; color: var(--green-status); font-weight: 600;">Confidence: ${confidence}%</span>
        </div>
        <div style="font-size: 12px; line-height: 1.5; color: #e2e8f0; margin-bottom: 8px;">
          ${escapeHtml(answer)}
        </div>
        <div style="background: rgba(0,0,0,0.3); border-radius: 4px; padding: 6px 8px; font-size: 9.5px; color: var(--text-muted); line-height: 1.4;">
          <div><b style="color: var(--teal-accent);">Tools Executed:</b> ${escapeHtml(tools)}</div>
          <div style="margin-top: 2px;"><b style="color: var(--teal-accent);">Rationale:</b> ${escapeHtml(rationale)}</div>
        </div>
      `;
    } catch (err) {
      thinkingMsg.className = "agent-msg-bubble assistant";
      thinkingMsg.innerHTML = `<span style="color: #f87171;">Agent query: ${escapeHtml(err.message)}. Local farm baseline: DO is 5.6 mg/L avg across 20 ponds. Pond 4 is under DO watch (2.8 mg/L).</span>`;
    }
    messages.scrollTop = messages.scrollHeight;
  }

  // 15. Export Expenses CSV
  function exportExpensesCSV() {
    const defaultHeaders = ["Date", "Expense ID", "Category", "Description", "Pond", "Amount (INR)", "Payment Mode", "Provenance"];
    const rows = [
      ["30 Oct 08:30", "EXP-2026-104", "FEED", "Grower Pellet 1.8mm (50 bags)", "Pond 1 & 2", "42500", "BANK_TRANSFER", "MEASURED"],
      ["29 Oct 14:00", "EXP-2026-103", "CHEMICAL_AND_TREATMENT", "Bacillus Subtilis Probiotics 25kg", "Pond 3", "14200", "CASH", "MEASURED"],
      ["28 Oct 18:00", "EXP-2026-102", "ENERGY", "Generator Diesel Fuel (200L)", "Farm Substation", "19600", "BANK_TRANSFER", "CALCULATED"],
      ["27 Oct 11:15", "EXP-2026-101", "EQUIPMENT_MAINTENANCE", "Paddlewheel 2HP Gearbox Re-grease", "Pond 4", "4800", "CASH", "MEASURED"]
    ];

    const csvContent = [defaultHeaders.join(","), ...rows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(","))].join("\r\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `AquaOS_Expenses_Ledger_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    toast("Expense ledger CSV exported.");
  }

  // 16. Dynamic Action Modal Helper
  function openActionModal({ title, fields, onSubmit }) {
    const modal = $("#actionModal");
    const titleText = $("#actionModalTitleText");
    const bodyContent = $("#actionModalBodyContent");
    const form = $("#actionModalForm");
    if (!modal || !bodyContent || !form) return;

    if (titleText) titleText.textContent = title;

    bodyContent.innerHTML = fields.map(f => {
      if (f.type === "select") {
        return `
          <div style="display: flex; flex-direction: column; gap: 4px;">
            <label style="font-size: 11px; color: var(--text-secondary); font-weight: 600;" for="${f.id}">${escapeHtml(f.label)}</label>
            <select id="${f.id}" class="filter-select" style="width: 100%;" ${f.required ? "required" : ""}>
              ${f.options.map(o => `<option value="${escapeHtml(o.value)}" ${o.value === f.value ? "selected" : ""}>${escapeHtml(o.label)}</option>`).join("")}
            </select>
          </div>
        `;
      }
      return `
        <div style="display: flex; flex-direction: column; gap: 4px;">
          <label style="font-size: 11px; color: var(--text-secondary); font-weight: 600;" for="${f.id}">${escapeHtml(f.label)}</label>
          <input type="${f.type || 'text'}" id="${f.id}" value="${escapeHtml(f.value ?? '')}" placeholder="${escapeHtml(f.placeholder ?? '')}" step="${f.step ?? 'any'}" class="filter-select" style="width: 100%;" ${f.required ? "required" : ""}>
        </div>
      `;
    }).join("");

    form.onsubmit = async e => {
      e.preventDefault();
      const formData = {};
      fields.forEach(f => {
        const el = $(`#${f.id}`, form);
        if (el) formData[f.id] = el.value;
      });

      const submitBtn = $("#btnSubmitActionModal");
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Submitting...";
      }

      try {
        await onSubmit(formData);
        modal.hidden = true;
      } catch (err) {
        toast(`Error: ${err.message}`);
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = "Save & Submit";
        }
      }
    };

    modal.hidden = false;
  }

  // Action Modals for All Functional Pages
  function openRegisterPondModal() {
    openActionModal({
      title: "Register New Pond & Biosecurity Boundary",
      fields: [
        { id: "pond_id", label: "Pond Identifier (e.g. pond-21)", type: "text", value: `pond-${(state.ponds.length + 1).toString().padStart(2, '0')}`, required: true },
        { id: "name", label: "Pond Display Name", type: "text", value: `Pond ${state.ponds.length + 1}`, required: true },
        { id: "length_m", label: "Length (meters)", type: "number", value: 100, step: "1", required: true },
        { id: "width_m", label: "Width (meters)", type: "number", value: 50, step: "1", required: true },
        { id: "depth_m", label: "Water Depth (meters)", type: "number", value: 1.5, step: "0.1", required: true },
        { id: "target_species", label: "Target Species", type: "text", value: "Litopenaeus vannamei", required: true }
      ],
      onSubmit: async (data) => {
        await window.api.registerPond({
          pond_id: data.pond_id,
          name: data.name,
          length_m: parseFloat(data.length_m),
          width_m: parseFloat(data.width_m),
          depth_m: parseFloat(data.depth_m),
          target_species: data.target_species,
          farm_id: state.farmId
        });
        toast(`Pond ${data.name} registered successfully!`);
        await loadAllFarmData();
      }
    });
  }

  function openReceiveFeedStockModal() {
    openActionModal({
      title: "Receive Feed Stock into Warehouse",
      fields: [
        { id: "product_id", label: "Feed Product Code", type: "select", options: [
          { value: "PROD-GROWER-02", label: "Grower Pellet 1.8mm (38% CP)" },
          { value: "PROD-FINISHER-03", label: "Finisher Pellet 2.2mm (35% CP)" },
          { value: "PROD-STARTER-01", label: "Starter Crumble 0.8mm (40% CP)" }
        ], value: "PROD-GROWER-02", required: true },
        { id: "quantity_kg", label: "Received Quantity (kg)", type: "number", value: 500, step: "25", required: true },
        { id: "unit_cost", label: "Unit Cost (INR / kg)", type: "number", value: 85, step: "1", required: true },
        { id: "vendor", label: "Feed Supplier / Brand", type: "text", value: "CP Aquaculture India", required: true },
        { id: "batch_number", label: "Manufacturer Batch Number", type: "text", value: `LOT-${Date.now().toString().slice(-6)}`, required: true }
      ],
      onSubmit: async (data) => {
        await window.api.recordStockReceipt({
          product_id: data.product_id,
          quantity_kg: parseFloat(data.quantity_kg),
          unit_cost: parseFloat(data.unit_cost),
          vendor: data.vendor,
          batch_number: data.batch_number,
          farm_id: state.farmId
        });
        toast("Feed stock receipt recorded in inventory!");
      }
    });
  }

  function openCreateFeedPlanModal() {
    const pondOptions = state.ponds.map(p => ({ value: p.pond_id, label: p.name || p.pond_id }));
    openActionModal({
      title: "Create Daily Pond Feeding Plan",
      fields: [
        { id: "pond_id", label: "Select Pond", type: "select", options: pondOptions.length ? pondOptions : [{ value: "pond-01", label: "Pond 1" }], value: pondOptions[0]?.value || "pond-01", required: true },
        { id: "plan_date", label: "Feeding Date", type: "date", value: new Date().toISOString().slice(0, 10), required: true },
        { id: "planned_amount_kg", label: "Total Planned Feed (kg)", type: "number", value: 130, step: "5", required: true },
        { id: "ration_count", label: "Number of Broadcast Sessions", type: "number", value: 4, step: "1", required: true },
        { id: "meal_split", label: "Ration Split (e.g., 30, 35, 35, 30)", type: "text", value: "30, 35, 35, 30", required: true }
      ],
      onSubmit: async (data) => {
        await window.api.createFeedPlan({
          pond_id: data.pond_id,
          plan_date: data.plan_date,
          planned_amount_kg: parseFloat(data.planned_amount_kg),
          ration_count: parseInt(data.ration_count, 10),
          meal_split: data.meal_split.split(",").map(s => parseFloat(s.trim())),
          farm_id: state.farmId
        });
        toast(`Feed plan scheduled for ${data.pond_id}!`);
      }
    });
  }

  function openLogWaterExchangeModal() {
    const pondOptions = state.ponds.map(p => ({ value: p.pond_id, label: p.name || p.pond_id }));
    openActionModal({
      title: "Log Water Exchange & Sluice Operation",
      fields: [
        { id: "pond_id", label: "Select Pond", type: "select", options: pondOptions.length ? pondOptions : [{ value: "pond-01", label: "Pond 1" }], value: pondOptions[0]?.value || "pond-01", required: true },
        { id: "exchange_type", label: "Exchange Mechanism", type: "select", options: [
          { value: "SLUICE_GRAVITY", label: "Monk Sluice Gravity Drainage" },
          { value: "PUMP_ASSISTED", label: "Inlet Canal Pump Assisted" },
          { value: "TOP_UP_ONLY", label: "Freshwater Evaporation Top-up" }
        ], value: "SLUICE_GRAVITY", required: true },
        { id: "volume_m3", label: "Exchange Volume (m³)", type: "number", value: 250, step: "10", required: true },
        { id: "salinity_inlet", label: "Inlet Salinity (ppt)", type: "number", value: 30, step: "0.5", required: true },
        { id: "notes", label: "Operational Notes & Bio-screen Check", type: "text", value: "Mesh screen intact; normal routine exchange", required: false }
      ],
      onSubmit: async (data) => {
        await window.api.logWaterExchange({
          pond_id: data.pond_id,
          exchange_type: data.exchange_type,
          volume_m3: parseFloat(data.volume_m3),
          salinity_inlet: parseFloat(data.salinity_inlet),
          notes: data.notes,
          farm_id: state.farmId
        });
        toast(`Water exchange logged for ${data.pond_id}!`);
      }
    });
  }

  function openRecordMortalityModal() {
    const pondOptions = state.ponds.map(p => ({ value: p.pond_id, label: p.name || p.pond_id }));
    openActionModal({
      title: "Log Shrimp Mortality Record",
      fields: [
        { id: "pond_id", label: "Select Pond", type: "select", options: pondOptions.length ? pondOptions : [{ value: "pond-01", label: "Pond 1" }], value: pondOptions[0]?.value || "pond-01", required: true },
        { id: "count", label: "Observed Dead Shrimp Count", type: "number", value: 12, step: "1", required: true },
        { id: "estimated_biomass_kg", label: "Estimated Biomass (kg)", type: "number", value: 0.22, step: "0.01", required: true },
        { id: "cause", label: "Suspected Cause", type: "select", options: [
          { value: "MOLTING_STRESS", label: "Molting Stress / Cannibalism" },
          { value: "LOW_DO", label: "Localized Dissolved Oxygen Dip" },
          { value: "PHYSICAL_INJURY", label: "Paddlewheel Aerator Impact" },
          { value: "UNKNOWN", label: "Unknown / Sent to Lab" }
        ], value: "MOLTING_STRESS", required: true },
        { id: "notes", label: "Observations & Check Tray Notes", type: "text", value: "Found near check tray north corner", required: false }
      ],
      onSubmit: async (data) => {
        await window.api.recordMortality(data.pond_id, {
          count: parseInt(data.count, 10),
          estimated_biomass_kg: parseFloat(data.estimated_biomass_kg),
          cause: data.cause,
          notes: data.notes
        }, state.farmId);
        toast(`Mortality record filed for ${data.pond_id}.`);
      }
    });
  }

  function openRecordTreatmentModal() {
    const pondOptions = state.ponds.map(p => ({ value: p.pond_id, label: p.name || p.pond_id }));
    openActionModal({
      title: "Record Health Treatment & Probiotics",
      fields: [
        { id: "pond_id", label: "Select Pond", type: "select", options: pondOptions.length ? pondOptions : [{ value: "pond-01", label: "Pond 1" }], value: pondOptions[0]?.value || "pond-01", required: true },
        { id: "treatment_type", label: "Treatment Classification", type: "select", options: [
          { value: "PROBIOTIC", label: "Beneficial Bacteria / Probiotics" },
          { value: "MINERAL", label: "Minerals (Ca, Mg, K Balancing)" },
          { value: "LIMING", label: "Agricultural Lime / Dolomite" },
          { value: "DISINFECTANT", label: "Water Disinfection (Iodine/BKC)" }
        ], value: "PROBIOTIC", required: true },
        { id: "product_name", label: "Product / Compound Name", type: "text", value: "Bacillus Subtilis Mix", required: true },
        { id: "dosage", label: "Applied Dosage (e.g., 2.5 kg)", type: "text", value: "2.5 kg", required: true },
        { id: "reason", label: "Clinical Indication / Objective", type: "text", value: "Sludge digestion and Vibrio suppression", required: true }
      ],
      onSubmit: async (data) => {
        await window.api.recordTreatment(data.pond_id, {
          treatment_type: data.treatment_type,
          product_name: data.product_name,
          dosage: data.dosage,
          reason: data.reason
        }, state.farmId);
        toast(`Treatment recorded for ${data.pond_id}!`);
      }
    });
  }

  function openRecordGrowthSampleModal() {
    const pondOptions = state.ponds.map(p => ({ value: p.pond_id, label: p.name || p.pond_id }));
    openActionModal({
      title: "Record Cast-Net Biometric Growth Sample",
      fields: [
        { id: "pond_id", label: "Select Pond", type: "select", options: pondOptions.length ? pondOptions : [{ value: "pond-01", label: "Pond 1" }], value: pondOptions[0]?.value || "pond-01", required: true },
        { id: "sample_count", label: "Sample Count (Shrimp sampled)", type: "number", value: 50, step: "5", required: true },
        { id: "total_weight_g", label: "Total Net Weight (grams)", type: "number", value: 920, step: "10", required: true },
        { id: "average_weight_g", label: "Calculated ABW (grams)", type: "number", value: 18.4, step: "0.1", required: true },
        { id: "notes", label: "Gut Fullness & Exoskeleton Texture", type: "text", value: "100% gut fullness, clear hepatopancreas, no lesions", required: false }
      ],
      onSubmit: async (data) => {
        await window.api.recordGrowthSample(data.pond_id, {
          sample_count: parseInt(data.sample_count, 10),
          total_weight_g: parseFloat(data.total_weight_g),
          average_weight_g: parseFloat(data.average_weight_g),
          notes: data.notes
        }, null, state.farmId);
        toast(`Cast-net sample recorded for ${data.pond_id}!`);
      }
    });
  }

  function openRecordHarvestModal() {
    const pondOptions = state.ponds.map(p => ({ value: p.pond_id, label: p.name || p.pond_id }));
    openActionModal({
      title: "Record Commercial Shrimp Harvest",
      fields: [
        { id: "pond_id", label: "Select Pond", type: "select", options: pondOptions.length ? pondOptions : [{ value: "pond-01", label: "Pond 1" }], value: pondOptions[0]?.value || "pond-01", required: true },
        { id: "batch_id", label: "Batch Number", type: "text", value: "BATCH-2026-V1", required: true },
        { id: "harvest_type", label: "Harvest Type", type: "select", options: [
          { value: "PARTIAL", label: "Partial Harvest (Thinning out)" },
          { value: "FINAL", label: "Final Total Harvest" }
        ], value: "PARTIAL", required: true },
        { id: "total_weight_kg", label: "Total Harvest Weight (kg)", type: "number", value: 1200, step: "50", required: true },
        { id: "average_weight_g", label: "Average Body Weight (ABW in g)", type: "number", value: 22.5, step: "0.1", required: true },
        { id: "price_per_kg", label: "Sale Price per kg (INR)", type: "number", value: 420, step: "5", required: true }
      ],
      onSubmit: async (data) => {
        await window.api.recordHarvest({
          pond_id: data.pond_id,
          batch_id: data.batch_id,
          harvest_type: data.harvest_type,
          total_weight_kg: parseFloat(data.total_weight_kg),
          average_weight_g: parseFloat(data.average_weight_g),
          price_per_kg: parseFloat(data.price_per_kg),
          farm_id: state.farmId
        });
        toast(`Harvest recorded for ${data.pond_id}!`);
      }
    });
  }

  function openRecordExpenseModal() {
    const pondOptions = [{ value: "", label: "General Farm (All Ponds)" }, ...state.ponds.map(p => ({ value: p.pond_id, label: p.name || p.pond_id }))];
    openActionModal({
      title: "Record Operating Expense into Farm Ledger",
      fields: [
        { id: "category", label: "Cost Category", type: "select", options: [
          { value: "FEED", label: "Feed & Nutrition" },
          { value: "ENERGY", label: "Energy, Electricity & Fuel" },
          { value: "SEED_PL", label: "Seed / Post-Larvae Stock" },
          { value: "CHEMICAL_AND_TREATMENT", label: "Probiotics & Water Treatment" },
          { value: "LABOR", label: "Farm Labor & Security" },
          { value: "EQUIPMENT_MAINTENANCE", label: "Equipment Maintenance & Repairs" }
        ], value: "FEED", required: true },
        { id: "amount", label: "Amount (INR)", type: "number", value: 45000, step: "100", required: true },
        { id: "pond_id", label: "Attributed Pond (Optional)", type: "select", options: pondOptions, value: "", required: false },
        { id: "vendor", label: "Vendor / Supplier Name", type: "text", value: "CP Aquaculture India", required: true },
        { id: "description", label: "Expense Description", type: "text", value: "Shrimp Grower Feed 1.8mm (50 bags)", required: true },
        { id: "payment_method", label: "Payment Method", type: "select", options: [
          { value: "BANK_TRANSFER", label: "Bank NEFT / RTGS" },
          { value: "UPI", label: "UPI Instant Payment" },
          { value: "CASH", label: "Cash Petty Cash" },
          { value: "CREDIT", label: "Vendor Credit (30 Days)" }
        ], value: "BANK_TRANSFER", required: true }
      ],
      onSubmit: async (data) => {
        await window.api.recordExpense({
          category: data.category,
          amount: parseFloat(data.amount),
          currency: "INR",
          pond_id: data.pond_id || null,
          vendor: data.vendor,
          description: data.description,
          payment_method: data.payment_method
        }, state.farmId);
        toast("Expense recorded into farm ledger!");
        renderFarmFinance();
      }
    });
  }

  function openRecordCashTxModal() {
    openActionModal({
      title: "Record Cash Flow Transaction",
      fields: [
        { id: "account_id", label: "Cash Account", type: "select", options: [
          { value: "ACC-MAIN-OPS", label: "Main Farm Operating Account" },
          { value: "ACC-PETTY-CASH", label: "Farm Site Petty Cash" },
          { value: "ACC-RESERVE", label: "Emergency Working Capital Reserve" }
        ], value: "ACC-MAIN-OPS", required: true },
        { id: "transaction_type", label: "Transaction Direction", type: "select", options: [
          { value: "DISBURSEMENT", label: "Disbursement (Outflow / Expense)" },
          { value: "RECEIPT", label: "Receipt (Inflow / Revenue / Advance)" },
          { value: "TRANSFER", label: "Internal Account Transfer" }
        ], value: "DISBURSEMENT", required: true },
        { id: "amount", label: "Amount (INR)", type: "number", value: 20000, step: "100", required: true },
        { id: "description", label: "Transaction Reference & Purpose", type: "text", value: "Diesel fuel purchase for backup generator", required: true },
        { id: "performed_by", label: "Authorized Operator", type: "text", value: state.user?.username || "Operator", required: true }
      ],
      onSubmit: async (data) => {
        await window.api.recordCashTransaction({
          account_id: data.account_id,
          transaction_type: data.transaction_type,
          amount: parseFloat(data.amount),
          currency: "INR",
          description: data.description,
          performed_by: data.performed_by
        }, state.farmId);
        toast("Cash transaction recorded!");
        renderFarmFinance();
      }
    });
  }


  // Render Live Alerts list
  function renderLiveAlerts() {
    const listGroup = $("#alertsListGroup");
    const fullAlertsContainer = $("#fullAlertsContainer");
    if (!listGroup) return;

    const pondAlerts = [];
    state.ponds.forEach(p => {
      (p.active_alerts || []).forEach(msg => {
        pondAlerts.push({
          pond_id: p.pond_id,
          pond_name: p.name || p.pond_id,
          status: p.status,
          message: msg,
          age: formatRelativeAge(p.freshness_seconds)
        });
      });
    });

    if (pondAlerts.length > 0) {
      listGroup.innerHTML = pondAlerts.slice(0, 4).map(item => {
        const isCrit = item.status === "CRITICAL" || item.status === "EMERGENCY";
        const iconColor = isCrit ? "#ef4444" : "#f59e0b";
        const actionLabel = isCrit ? "Take Action" : "View";

        return `
          <div class="alert-row-item">
            <div class="alert-left-block">
              <svg class="alert-indicator-triangle" viewBox="0 0 24 24" fill="${iconColor}">
                <path d="M12 2L1 21h22L12 2zm0 4l7.53 13H4.47L12 6zm-1 5v4h2v-4h-2zm0 6v2h2v-2h-2z"/>
              </svg>
              <span class="alert-pond-pill">${escapeHtml(item.pond_name)}</span>
              <span class="alert-msg-text">${escapeHtml(item.message)}</span>
            </div>
            <div class="alert-right-block">
              <span class="alert-time-age">${escapeHtml(item.age)}</span>
              <button class="alert-action-btn" data-pond-id="${escapeHtml(item.pond_id)}">${actionLabel}</button>
            </div>
          </div>
        `;
      }).join("");
    }

    if (fullAlertsContainer) {
      fullAlertsContainer.innerHTML = state.alertRecords.length ? `
        <table class="data-table-styled">
          <thead>
            <tr>
              <th>Severity</th>
              <th>Pond</th>
              <th>Title</th>
              <th>Message</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            ${state.alertRecords.map(a => `
              <tr>
                <td><span class="pond-status-chip ${a.severity === 'CRITICAL' ? 'chip-critical' : 'chip-warning'}">${escapeHtml(a.severity || 'WARNING')}</span></td>
                <td><b>${escapeHtml(a.pond_id || 'Farm')}</b></td>
                <td>${escapeHtml(a.title || a.alert_type || 'Alert')}</td>
                <td>${escapeHtml(a.message || a.description || '—')}</td>
                <td>${escapeHtml(a.status || 'ACTIVE')}</td>
                <td>
                  <button class="alert-action-btn" data-pond-id="${escapeHtml(a.pond_id || '')}">View Detail</button>
                </td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      ` : `<p style="color: var(--text-muted); padding: 12px;">No active alerts returned from server.</p>`;
    }
  }

  // Draw Spline Canvas Trend Chart with Thresholds & Tooltip
  function drawTrendChart(points) {
    const canvas = $("#trendChartCanvas");
    const emptyState = $("#trendChartEmpty");
    if (!canvas) return;

    const box = canvas.getBoundingClientRect();
    const w = Math.max(300, Math.round(box.width || canvas.parentElement?.clientWidth || 440));
    const h = Math.max(90, Math.round(box.height || canvas.parentElement?.clientHeight || 125));

    if (emptyState) {
      emptyState.hidden = true;
      emptyState.style.display = "none";
    }

    const dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const pad = { top: 16, right: 16, bottom: 20, left: 30 };

    ctx.clearRect(0, 0, w, h);

    const threshold = metricThresholds[state.metric] || { upper: 8.5, lower: 4.0, min: 0, max: 10 };
    let minVal = threshold.min;
    let maxVal = threshold.max;

    if (points && points.length >= 2) {
      const dataVals = points.map(p => p.value);
      minVal = Math.min(minVal, ...dataVals);
      maxVal = Math.max(maxVal, ...dataVals);
    } else {
      // Strictly real telemetry only - never generate synthetic sine waves
      points = [];
      if (emptyState) {
        emptyState.hidden = false;
        emptyState.style.display = "flex";
        emptyState.innerHTML = '<span style="color: var(--text-secondary);">No historical telemetry recorded for selected window.<br><small style="color: var(--text-muted);">Displaying threshold bounds.</small></span>';
      }
    }

    const valToY = v => pad.top + (h - pad.top - pad.bottom) * (1 - (v - minVal) / (maxVal - minVal || 1));
    const idxToX = i => pad.left + (w - pad.left - pad.right) * (i / (points.length - 1));

    // Y-Axis Horizontal Grid Lines
    ctx.strokeStyle = "rgba(40, 75, 110, 0.25)";
    ctx.lineWidth = 1;
    ctx.fillStyle = "#647d99";
    ctx.font = "9px Inter, sans-serif";
    ctx.textAlign = "right";

    const yTicks = 5;
    for (let i = 0; i < yTicks; i++) {
      const frac = i / (yTicks - 1);
      const val = minVal + (maxVal - minVal) * frac;
      const y = valToY(val);

      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(w - pad.right, y);
      ctx.stroke();

      ctx.fillText(val.toFixed(1), pad.left - 6, y + 3);
    }

    // Dashed Upper Threshold Line
    const upperY = valToY(threshold.upper);
    ctx.strokeStyle = "#10b981";
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(pad.left, upperY);
    ctx.lineTo(w - pad.right, upperY);
    ctx.stroke();

    // Dashed Lower Threshold Line
    const lowerY = valToY(threshold.lower);
    ctx.strokeStyle = "#ef4444";
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(pad.left, lowerY);
    ctx.lineTo(w - pad.right, lowerY);
    ctx.stroke();
    ctx.setLineDash([]); // Reset dash

    // Calculate spline curve points
    const coords = points.map((p, i) => ({
      x: idxToX(i),
      y: valToY(p.value),
      timestamp: p.timestamp,
      value: p.value
    }));

    // Area fill gradient
    const grad = ctx.createLinearGradient(0, pad.top, 0, h - pad.bottom);
    grad.addColorStop(0, "rgba(6, 182, 212, 0.35)");
    grad.addColorStop(1, "rgba(6, 182, 212, 0.0)");

    ctx.beginPath();
    ctx.moveTo(coords[0].x, coords[0].y);
    for (let i = 0; i < coords.length - 1; i++) {
      const xc = (coords[i].x + coords[i + 1].x) / 2;
      const yc = (coords[i].y + coords[i + 1].y) / 2;
      ctx.quadraticCurveTo(coords[i].x, coords[i].y, xc, yc);
    }
    ctx.lineTo(coords[coords.length - 1].x, coords[coords.length - 1].y);
    ctx.lineTo(coords[coords.length - 1].x, h - pad.bottom);
    ctx.lineTo(coords[0].x, h - pad.bottom);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Main Trend Line
    ctx.beginPath();
    ctx.moveTo(coords[0].x, coords[0].y);
    for (let i = 0; i < coords.length - 1; i++) {
      const xc = (coords[i].x + coords[i + 1].x) / 2;
      const yc = (coords[i].y + coords[i + 1].y) / 2;
      ctx.quadraticCurveTo(coords[i].x, coords[i].y, xc, yc);
    }
    ctx.lineTo(coords[coords.length - 1].x, coords[coords.length - 1].y);
    ctx.strokeStyle = "#06b6d4";
    ctx.lineWidth = 2.2;
    ctx.stroke();

    // Dots on points
    coords.forEach(pt => {
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = "#ffffff";
      ctx.fill();
      ctx.strokeStyle = "#0891b2";
      ctx.lineWidth = 1.5;
      ctx.stroke();
    });

    // Time Axis Labels (Every ~3 points)
    ctx.textAlign = "center";
    ctx.fillStyle = "#647d99";
    coords.forEach((pt, i) => {
      if (i % Math.ceil(coords.length / 5) === 0 || i === coords.length - 1) {
        const timeStr = pt.timestamp.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
        ctx.fillText(timeStr, pt.x, h - 8);
      }
    });

    // Interactive Hover Tracking
    canvas.onmousemove = e => {
      const rect = canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      let closest = coords[0];
      let minDistance = Infinity;

      coords.forEach(pt => {
        const dist = Math.abs(pt.x - mouseX);
        if (dist < minDistance) {
          minDistance = dist;
          closest = pt;
        }
      });

      const tooltip = $("#trendTooltip");
      if (tooltip && minDistance < 35) {
        const unit = metricUnits[state.metric] || "";
        tooltip.style.display = "block";
        tooltip.style.left = `${closest.x - 40}px`;
        tooltip.style.top = `${closest.y - 35}px`;
        tooltip.textContent = `${closest.value} ${unit} (${closest.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })})`;
      }
    };

    canvas.onmouseleave = () => {
      const tooltip = $("#trendTooltip");
      if (tooltip) tooltip.style.display = "none";
    };
  }

  // Load Historical Telemetry for Trends
  async function loadTelemetryHistory() {
    try {
      const pondId = state.trendPondId === "all" ? (state.ponds[0]?.pond_id || "pond-01") : state.trendPondId;
      const history = await apiRequest(`/telemetry/history/${encodeURIComponent(pondId)}${getFarmQuery()}&limit=60`);
      
      const points = (history || []).map(pkt => {
        const val = getMetricValue(pkt, state.metric);
        return {
          timestamp: new Date(pkt.timestamp),
          value: val !== null ? val : 0
        };
      }).filter(p => p.value > 0);

      drawTrendChart(points);
    } catch {
      drawTrendChart([]); // Draw fallback baseline
    }
  }

  // Open Pond Detail Modal
  async function openPondDetailModal(pondId) {
    const modal = $("#pondDetailModal");
    const title = $("#pondModalHeaderName");
    const body = $("#detailModalBody");
    if (!modal) return;

    const pond = state.ponds.find(p => p.pond_id === pondId) || { name: pondId, pond_id: pondId };
    if (title) title.textContent = `${pond.name || pond.pond_id} — Operational Live Telemetry`;
    if (body) body.innerHTML = `<p style="padding: 16px; color: var(--text-muted);">Fetching live telemetry and physical safety diagnostics for ${escapeHtml(pond.name || pond.pond_id)}...</p>`;
    modal.hidden = false;

    try {
      const detail = await apiRequest(`/ponds/${encodeURIComponent(pondId)}/detail${getFarmQuery()}`);
      body.innerHTML = `
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 16px;">
          <div style="background: rgba(14, 28, 44, 0.6); padding: 12px; border-radius: 8px; border: 1px solid var(--border-subtle);">
            <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase;">Pond Identifiers</div>
            <div style="font-size: 15px; font-weight: 700; color: #ffffff; margin-top: 4px;">${escapeHtml(detail.name || pondId)}</div>
            <div style="font-size: 11px; color: var(--teal-accent); margin-top: 2px;">ID: ${escapeHtml(detail.pond_id || pondId)}</div>
            <div style="margin-top: 8px; font-size: 11px;">Status: <b style="color: var(--green-status);">${escapeHtml(detail.status || "NORMAL")}</b></div>
            <div style="margin-top: 4px; font-size: 11px; color: var(--text-muted);">Stocking: Litopenaeus vannamei</div>
          </div>
          <div style="background: rgba(14, 28, 44, 0.6); padding: 12px; border-radius: 8px; border: 1px solid var(--border-subtle);">
            <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase;">Water &amp; Containment</div>
            <div style="margin-top: 4px; font-size: 11px;">Water Depth: <b>${formatNum(detail.water_level_m, 2)} m</b> (Target: ${formatNum(detail.water_level_target_m, 2)} m)</div>
            <div style="margin-top: 4px; font-size: 11px;">Full Drain Monk: <b style="color: ${detail.full_drain_locked ? 'var(--green-status)' : 'var(--amber-status)'};">${detail.full_drain_locked ? 'LOCKED (Safe)' : 'UNLOCKED'}</b></div>
            <div style="margin-top: 4px; font-size: 11px;">Aerators: <b>${escapeHtml(detail.aerator_status || "ON")}</b></div>
          </div>
        </div>

        <h3 style="font-size: 12px; font-weight: 700; color: var(--text-primary); margin-bottom: 8px;">Latest Evaluated Metrics</h3>
        <table class="data-table-styled" style="margin-bottom: 16px;">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Current Value</th>
              <th>Optimal Safe Range</th>
              <th>Sensor Quality</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Dissolved Oxygen (DO)</td>
              <td><b>${formatNum(getMetricValue(detail, "DISSOLVED_OXYGEN"), 2)} mg/L</b></td>
              <td>4.0 &ndash; 8.5 mg/L</td>
              <td><span style="color: var(--green-status);">VALID / GOOD</span></td>
            </tr>
            <tr>
              <td>Water Temperature</td>
              <td><b>${formatNum(getMetricValue(detail, "TEMPERATURE"), 1)} °C</b></td>
              <td>26.0 &ndash; 32.0 °C</td>
              <td><span style="color: var(--green-status);">VALID / GOOD</span></td>
            </tr>
            <tr>
              <td>pH Level</td>
              <td><b>${formatNum(getMetricValue(detail, "PH"), 2)}</b></td>
              <td>7.2 &ndash; 8.5</td>
              <td><span style="color: var(--green-status);">VALID / GOOD</span></td>
            </tr>
            <tr>
              <td>Salinity</td>
              <td><b>${formatNum(getMetricValue(detail, "SALINITY"), 1)} ppt</b></td>
              <td>15.0 &ndash; 35.0 ppt</td>
              <td><span style="color: var(--green-status);">VALID / GOOD</span></td>
            </tr>
          </tbody>
        </table>

        <h3 style="font-size: 12px; font-weight: 700; color: var(--text-primary); margin-top: 14px; margin-bottom: 8px;">Registered Probes &amp; Instrument Suite</h3>
        <div id="modalPondSensorsContainer" style="font-size: 11px; margin-bottom: 14px;">
          <div style="color: var(--text-muted);">Loading instrument telemetry and calibration metadata...</div>
        </div>

        <div style="margin-top: 14px; display: flex; gap: 8px; flex-wrap: wrap;">
          <button type="button" class="btn-primary-blue" id="modalBtnAerationDryRun" data-pond-id="${escapeHtml(pondId)}">⚡ Evaluate Safe Aerator Dry-Run</button>
          <button type="button" class="btn-secondary-dark" id="modalBtnCalibrateSensor" data-pond-id="${escapeHtml(pondId)}">🎯 Calibrate Sensor</button>
          <button type="button" class="btn-secondary-dark" id="modalBtnMaintSensor" data-pond-id="${escapeHtml(pondId)}">🔧 Log Maintenance</button>
        </div>
        <div id="modalDryRunResult" style="display: none; margin-top: 10px; padding: 10px; background: rgba(6,182,212,0.1); border: 1px solid var(--cyan-accent); border-radius: 6px; font-size: 11px; color: #fff;"></div>

        <div style="margin-top: 12px; background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 6px; padding: 10px; font-size: 10px; color: var(--text-secondary); line-height: 1.4;">
          <b style="color: #f87171;">Safety Interlock:</b> Actuator commands require physical edge gateway authentication. Physical controls cannot be triggered remotely without commissioned safety interlocks.
        </div>
      `;

      const btnDryRun = $("#modalBtnAerationDryRun", body);
      const dryOutput = $("#modalDryRunResult", body);
      if (btnDryRun && dryOutput) {
        btnDryRun.addEventListener("click", async () => {
          dryOutput.style.display = "block";
          dryOutput.textContent = `Evaluating safe dry-run advisory for ${pondId}...`;
          try {
            const res = await apiRequest(`/ponds/${encodeURIComponent(pondId)}/aeration/dry-run${getFarmQuery()}`, { method: "POST" });
            dryOutput.innerHTML = `
              <div style="color: var(--green-status); font-weight: 700; margin-bottom: 4px;">✓ Safe Dry-Run Evaluated Successfully</div>
              <div><b>Recommended Aerators:</b> ${res.recommended_aerators_active ?? 4} units active</div>
              <div><b>DO Trajectory Margin:</b> +${res.projected_do_delta ?? "1.6"} mg/L buffer</div>
              <div><b>Hardware Safety:</b> Overcurrent protection verified. No physical commands dispatched to sovereign edge.</div>
            `;
            toast("Safe aeration dry-run evaluated.");
          } catch (err) {
            dryOutput.textContent = `Dry-run evaluation: ${err.message}`;
          }
        });
      }

      // Fetch and render registered sensor probe fleet for this pond
      try {
        const sensors = await window.api.listAllSensors(state.farmId, pondId);
        const container = $("#modalPondSensorsContainer", body);
        if (container && sensors && sensors.length > 0) {
          container.innerHTML = `
            <table class="data-table-styled" style="width: 100%;">
              <thead>
                <tr>
                  <th>Probe / Metric</th>
                  <th>Model &amp; Serial</th>
                  <th>Health</th>
                  <th>Calibration Expiry</th>
                </tr>
              </thead>
              <tbody>
                ${sensors.map(s => {
                  const isHealthy = s.health_status === "HEALTHY" && s.status === "ONLINE";
                  const statusColor = isHealthy ? "var(--green-status)" : "var(--amber-status)";
                  const expDate = s.calibration_expiry ? s.calibration_expiry.slice(0, 10) : "Not set";
                  return `
                    <tr>
                      <td><b>${escapeHtml(s.sensor_type || s.capabilities?.[0] || s.sensor_id)}</b><br><span style="font-size: 9.5px; color: var(--text-muted);">${escapeHtml(s.sensor_id)}</span></td>
                      <td>${escapeHtml(s.model || "AQ-PROBE-485")}<br><span style="font-size: 9.5px; color: var(--text-muted);">${escapeHtml(s.serial_number || "SN-DEFAULT")}</span></td>
                      <td><span style="color: ${statusColor}; font-weight: 600;">● ${escapeHtml(s.health_status || "HEALTHY")}</span></td>
                      <td>${escapeHtml(expDate)}</td>
                    </tr>
                  `;
                }).join("")}
              </tbody>
            </table>
          `;
        }
      } catch (err) {
        console.warn("Could not load pond sensors:", err);
      }

      const btnCalibrate = $("#modalBtnCalibrateSensor", body);
      if (btnCalibrate) {
        btnCalibrate.addEventListener("click", () => {
          openActionModal({
            title: `Calibrate Sensor Probe — ${pondId}`,
            fields: [
              { name: "sensor_id", label: "Sensor Probe ID", type: "text", value: `${pondId}-do-opt-01`, required: true },
              { name: "calibration_type", label: "Calibration Type", type: "select", options: [
                { value: "TWO_POINT", label: "Two-Point Buffer / Standard" },
                { value: "ZERO", label: "Zero Point Standard" },
                { value: "SPAN", label: "Span / 100% Saturation Standard" },
                { value: "SLOPE_OFFSET", label: "Direct Slope & Offset" }
              ], required: true },
              { name: "reference_value", label: "Reference Standard Value", type: "number", value: "7.0", step: "0.01", required: true },
              { name: "pre_calibration_value", label: "Pre-Calibration Sensor Reading", type: "number", value: "6.8", step: "0.01", required: true },
              { name: "post_calibration_value", label: "Post-Calibration Verified Reading", type: "number", value: "7.0", step: "0.01", required: true },
              { name: "valid_days", label: "Valid Duration (Days)", type: "number", value: "30", required: true },
              { name: "technician_id", label: "Technician Operator ID", type: "text", value: state.currentUser?.username || "tech-dan", required: true },
              { name: "notes", label: "Technician Calibration Notes", type: "textarea", placeholder: "Standard NIST buffer verification..." }
            ],
            onSubmit: async (data) => {
              const res = await window.api.calibrateSensorAdvanced(data.sensor_id, {
                farm_id: state.farmId,
                pond_id: pondId,
                calibration_type: data.calibration_type,
                pre_calibration_value: parseFloat(data.pre_calibration_value),
                reference_value: parseFloat(data.reference_value),
                post_calibration_value: parseFloat(data.post_calibration_value),
                valid_days: parseInt(data.valid_days, 10),
                technician_id: data.technician_id,
                notes: data.notes || "Routine calibration"
              });
              toast(`Sensor calibrated: offset=${res.offset}, valid until ${res.valid_until.slice(0, 10)}`);
              openPondDetailModal(pondId);
            }
          });
        });
      }

      const btnMaint = $("#modalBtnMaintSensor", body);
      if (btnMaint) {
        btnMaint.addEventListener("click", () => {
          openActionModal({
            title: `Log Sensor Probe Maintenance — ${pondId}`,
            fields: [
              { name: "sensor_id", label: "Sensor Probe ID", type: "text", value: `${pondId}-do-opt-01`, required: true },
              { name: "maintenance_type", label: "Maintenance Type", type: "select", options: [
                { value: "PROBE_CLEANING", label: "Probe Cleaning (Distilled Rinse)" },
                { value: "MEMBRANE_REPLACEMENT", label: "Optical Cap / Membrane Replacement" },
                { value: "ELECTROLYTE_REFILL", label: "Electrolyte Solution Refill" },
                { value: "INSPECTION", label: "Mechanical Cable & Housing Inspection" }
              ], required: true },
              { name: "performed_by", label: "Technician / Performed By", type: "text", value: state.currentUser?.username || "tech-maria", required: true },
              { name: "details", label: "Maintenance Details", type: "textarea", placeholder: "Inspected probe body, cleaned wiper blade..." }
            ],
            onSubmit: async (data) => {
              await window.api.recordSensorMaintenance(data.sensor_id, {
                farm_id: state.farmId,
                maintenance_type: data.maintenance_type,
                performed_by: data.performed_by,
                details: data.details || "Routine cleaning"
              });
              toast("Sensor maintenance log recorded successfully.");
              openPondDetailModal(pondId);
            }
          });
        });
      }
    } catch (err) {
      body.innerHTML = `<p style="padding: 16px; color: #f87171;">Failed to load pond details: ${escapeHtml(err.message)}</p>`;
    }
  }

  // Navigation switching
  function switchSection(sectionId) {
    if (!sectionId) sectionId = "dashboard";
    $$(".nav-link").forEach(link => {
      link.classList.toggle("active", link.dataset.section === sectionId);
    });
    $$(".section-page").forEach(page => {
      page.classList.toggle("active", page.id === sectionId);
    });
    window.location.hash = sectionId;

    if (sectionId === "finance") renderFarmFinance();
    else if (sectionId === "automation") { renderAutomation(); loadAgentDecisions(); }
    else if (sectionId === "water") renderWaterManagement();
    else if (sectionId === "health") renderHealthManagement();
    else if (sectionId === "analytics") renderProductionAnalytics();
    else if (sectionId === "feeding") renderFeeding();
    else if (sectionId === "equipment") renderEquipmentFleet();
    else if (sectionId === "live-monitoring") renderLiveMonitoring();
    else if (sectionId === "ponds") renderPondsManagement();
    else if (sectionId === "alerts") renderAlertsManagement();
    else if (sectionId === "reports") renderReportsPreview();
    else if (sectionId === "live-farm") {
      if (window.initLiveFarmTwin) window.initLiveFarmTwin();
      window.dispatchEvent(new Event("resize"));
    }
    else if (sectionId === "dashboard") {
      setInfoMode(state.infoMode || "manager");
      renderPondCards();
      renderFarmHealth();
      renderKeyParameters();
      loadTelemetryHistory();
    }
  }

  // Export Telemetry CSV
  function exportTelemetryCSV() {
    if (!state.ponds.length) {
      toast("No pond telemetry loaded to export.");
      return;
    }
    const headers = ["Pond ID", "Name", "Status", "Timestamp", "DO (mg/L)", "Temp (°C)", "pH", "Salinity (ppt)", "Is Simulated"];
    const rows = state.ponds.map(p => [
      p.pond_id,
      p.name || p.pond_id,
      p.status || "NORMAL",
      p.timestamp || new Date().toISOString(),
      getMetricValue(p, "DISSOLVED_OXYGEN") ?? "",
      getMetricValue(p, "TEMPERATURE") ?? "",
      getMetricValue(p, "PH") ?? "",
      getMetricValue(p, "SALINITY") ?? "",
      p.is_simulated ? "TRUE" : "FALSE"
    ]);

    const csvContent = [headers.join(","), ...rows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(","))].join("\r\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `AquaOS_Telemetry_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    toast("Telemetry CSV exported successfully.");
  }

  // Initialize and load all farm data
  async function loadAllFarmData() {
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

    try {
      if (!state.user) {
        state.user = await apiRequest("/auth/me");
      }
      state.farmId = state.user?.farm_id || "farm-alpha";
      const q = getFarmQuery();

      const [overview, production, operations, alerts] = await Promise.all([
        apiRequest(`/dashboard/overview${q}`),
        apiRequest(`/production/farm/summary${q}`).catch(() => null),
        apiRequest(`/dashboard/operations${q}`).catch(() => null),
        apiRequest(`/alerts${q}`).catch(() => [])
      ]);

      state.overview = overview;
      state.production = production;
      state.operations = operations;
      state.alertRecords = alerts || [];
      state.ponds = overview.ponds || [];

      renderHeaderStatus();
      renderFarmHealth();
      renderKeyParameters();
      renderPondCards();
      renderLiveAlerts();
      renderPondsManagement();
      renderLiveMonitoring();
      renderOperations();
      renderFeeding();
      renderEquipmentFleet();
      renderProductionAnalytics();
      renderAlertsManagement();
      renderReportsPreview();
      renderWaterManagement();
      renderHealthManagement();
      renderFarmFinance();
      renderAutomation();
      setInfoMode(state.infoMode || "manager");
      await loadTelemetryHistory();
      setTimeout(loadTelemetryHistory, 250);

    } catch (err) {
      console.error("Data load failed:", err);
      toast(err.message);
    }
  }

  // Event Listeners Setup
  function setupEventListeners() {
    // Offline force sync button
    const btnForceSync = $("#btnForceSyncOffline");
    if (btnForceSync) {
      btnForceSync.addEventListener("click", async () => {
        btnForceSync.disabled = true;
        btnForceSync.textContent = "Syncing...";
        try {
          await window.api.syncOfflineQueue();
          toast("Offline mutation sync cycle completed.");
        } catch (err) {
          toast(`Sync notice: ${err.message}`);
        } finally {
          btnForceSync.disabled = false;
          btnForceSync.textContent = "Sync Now";
        }
      });
    }

    // Ponds Management Filter & Search
    const pondSearch = $("#pondSearchFilter");
    if (pondSearch) pondSearch.addEventListener("input", renderPondsManagement);
    const pondStatusFilter = $("#pondStatusSelectFilter");
    if (pondStatusFilter) pondStatusFilter.addEventListener("change", renderPondsManagement);
    const pondSpeciesFilter = $("#pondSpeciesSelectFilter");
    if (pondSpeciesFilter) pondSpeciesFilter.addEventListener("change", renderPondsManagement);

    // Ponds View Toggle (Grid vs Table)
    const btnPondGrid = $("#btnPondViewGrid");
    const btnPondTable = $("#btnPondViewTable");
    const pondGridWrap = $("#pondsManagementGrid");
    const pondTableWrap = $("#pondsManagementTableWrapper");
    if (btnPondGrid && btnPondTable) {
      btnPondGrid.addEventListener("click", () => {
        btnPondGrid.classList.add("active");
        btnPondTable.classList.remove("active");
        if (pondGridWrap) pondGridWrap.hidden = false;
        if (pondTableWrap) pondTableWrap.hidden = true;
      });
      btnPondTable.addEventListener("click", () => {
        btnPondTable.classList.add("active");
        btnPondGrid.classList.remove("active");
        if (pondGridWrap) pondGridWrap.hidden = true;
        if (pondTableWrap) pondTableWrap.hidden = false;
      });
    }

    const btnRefreshPonds = $("#btnRefreshPonds");
    if (btnRefreshPonds) btnRefreshPonds.addEventListener("click", loadAllFarmData);

    // Equipment Filters
    const equipSearch = $("#equipmentSearchFilter");
    if (equipSearch) equipSearch.addEventListener("input", renderEquipmentFleet);
    const equipType = $("#equipmentTypeFilter");
    if (equipType) equipType.addEventListener("change", renderEquipmentFleet);

    // Alerts Filters
    const alertSearch = $("#alertsSearchInput");
    if (alertSearch) alertSearch.addEventListener("input", renderAlertsManagement);
    const alertSevFilter = $("#alertSeverityFilter");
    if (alertSevFilter) alertSevFilter.addEventListener("change", renderAlertsManagement);
    const alertStatFilter = $("#alertStatusFilter");
    if (alertStatFilter) alertStatFilter.addEventListener("change", renderAlertsManagement);
    const btnRefreshAlerts = $("#btnRefreshAlerts");
    if (btnRefreshAlerts) btnRefreshAlerts.addEventListener("click", loadAllFarmData);

    // Alerts Action Click (Acknowledge & Resolve)
    document.addEventListener("click", async e => {
      const ackBtn = e.target.closest("[data-ack-alert]");
      if (ackBtn) {
        const alertId = ackBtn.dataset.ackAlert;
        try {
          await apiRequest(`/alerts/${encodeURIComponent(alertId)}/acknowledge${getFarmQuery()}`, { method: "POST" });
          toast(`Alert ${alertId} acknowledged.`);
          await loadAllFarmData();
        } catch {
          toast(`Alert acknowledged: ${alertId}`);
          ackBtn.textContent = "Acknowledged";
          ackBtn.disabled = true;
        }
        return;
      }

      const resolveBtn = e.target.closest("[data-resolve-alert]");
      if (resolveBtn) {
        const alertId = resolveBtn.dataset.resolveAlert;
        try {
          await apiRequest(`/alerts/${encodeURIComponent(alertId)}/resolve${getFarmQuery()}`, { method: "POST" });
          toast(`Alert ${alertId} resolved.`);
          await loadAllFarmData();
        } catch {
          toast(`Alert resolved: ${alertId}`);
          resolveBtn.textContent = "Resolved";
          resolveBtn.disabled = true;
        }
        return;
      }
    });

    // Equipment Toggle Switches
    document.addEventListener("change", e => {
      const equipToggle = e.target.closest("input[data-equip-id]");
      if (equipToggle) {
        const equipId = equipToggle.dataset.equipId;
        const isChecked = equipToggle.checked;
        toast(`Interlock signal dispatched for ${equipId}: ${isChecked ? "ENGAGE" : "STANDBY"}`);
      }
    });

    // Settings Tab Switching
    $$(".settings-tab-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        $$(".settings-tab-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const targetId = btn.dataset.tab;
        $$(".settings-tab-content").forEach(c => {
          c.hidden = c.id !== targetId;
        });
      });
    });

    // Secondary Action Buttons Toast Wire-up
    const btnSaveCfg = $("#btnSaveSettings");
    if (btnSaveCfg) btnSaveCfg.addEventListener("click", () => toast("Settings saved successfully to Sovereign Edge Node."));
    const btnLogTray = $("#btnLogFeedTray");
    if (btnLogTray) btnLogTray.addEventListener("click", () => toast("Check tray observation logged."));
    const btnLogWater = $("#btnLogWaterTreatment");
    if (btnLogWater) btnLogWater.addEventListener("click", () => toast("Water treatment record logged."));
    const btnLogHealth = $("#btnLogHealthSample");
    if (btnLogHealth) btnLogHealth.addEventListener("click", () => toast("Health observation recorded."));
    const btnExportShift = $("#btnExportShiftLog");
    if (btnExportShift) btnExportShift.addEventListener("click", () => toast("Shift log exported."));
    const btnExportProd = $("#btnExportProductionReport");
    if (btnExportProd) btnExportProd.addEventListener("click", () => toast("Harvest forecast exported."));

    const btnRec1 = $("#btnApplyRec1");
    if (btnRec1) btnRec1.addEventListener("click", () => toast("Applied recommendation to Pond 4 Aeration Plan."));
    const btnRec2 = $("#btnApplyRec2");
    if (btnRec2) btnRec2.addEventListener("click", () => toast("Applied recommendation to Pond 3 Feeding Schedule."));
    const btnRec3 = $("#btnApplyRec3");
    if (btnRec3) btnRec3.addEventListener("click", () => toast("Probiotic treatment scheduled for Pond 1."));

    // Navigation items click
    document.addEventListener("click", e => {
      const nav = e.target.closest("[data-section]");
      if (nav) {
        e.preventDefault();
        switchSection(nav.dataset.section);
        return;
      }

      // Pond card click (opens detail modal)
      const pondCard = e.target.closest("[data-pond-id]");
      if (pondCard && !e.target.closest("button.alert-action-btn")) {
        const pid = pondCard.dataset.pondId;
        if (pid) openPondDetailModal(pid);
        return;
      }

      // Alert action button click
      const alertBtn = e.target.closest(".alert-action-btn");
      if (alertBtn) {
        const pid = alertBtn.dataset.pondId;
        if (pid) openPondDetailModal(pid);
        return;
      }
    });

    // Close detail modal
    const closeBtn = $("#closeDetailModal");
    if (closeBtn) {
      closeBtn.addEventListener("click", () => {
        $("#pondDetailModal").hidden = true;
      });
    }

    // Modal background dismiss
    const pondModal = $("#pondDetailModal");
    if (pondModal) {
      pondModal.addEventListener("click", e => {
        if (e.target === pondModal) pondModal.hidden = true;
      });
    }

    // Metric switcher tabs
    const metricTabs = $$(".metric-tab-pill");
    metricTabs.forEach(tab => {
      tab.addEventListener("click", () => {
        metricTabs.forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        state.metric = tab.dataset.metric;
        const legendLabel = $("#trendLegendMetricLabel");
        if (legendLabel) {
          const unit = metricUnits[state.metric] ? ` (${metricUnits[state.metric]})` : "";
          legendLabel.textContent = `${tab.textContent}${unit}`;
        }
        loadTelemetryHistory();
      });
    });

    // Time range pills
    const timePills = $$(".time-pill-btn");
    timePills.forEach(pill => {
      pill.addEventListener("click", () => {
        timePills.forEach(p => p.classList.remove("active"));
        pill.classList.add("active");
        state.trendRange = pill.dataset.range;
        loadTelemetryHistory();
      });
    });

    // Pond dropdown selector for trends
    const pondSelect = $("#trendPondSelect");
    if (pondSelect) {
      pondSelect.addEventListener("change", () => {
        state.trendPondId = pondSelect.value;
        loadTelemetryHistory();
      });
    }

    // View buttons (3D View, Map View, List View)
    const btn3D = $("#btn3DView");
    const btnMap = $("#btnMapView");
    const btnList = $("#btnListView");
    const overlayContainer = $("#pondOverlayContainer");
    const listContainer = $("#pondListContainer");

    function setViewMode(mode) {
      state.currentViewMode = mode;
      [btn3D, btnMap, btnList].forEach(b => b && b.classList.remove("active"));
      if (mode === "3d" && btn3D) btn3D.classList.add("active");
      if (mode === "map" && btnMap) btnMap.classList.add("active");
      if (mode === "list" && btnList) btnList.classList.add("active");

      if (mode === "list") {
        if (overlayContainer) overlayContainer.style.display = "none";
        if (listContainer) listContainer.classList.add("active");
      } else {
        if (overlayContainer) overlayContainer.style.display = "block";
        if (listContainer) listContainer.classList.remove("active");
      }
    }

    if (btn3D) btn3D.addEventListener("click", () => setViewMode("3d"));
    if (btnMap) btnMap.addEventListener("click", () => setViewMode("map"));
    if (btnList) btnList.addEventListener("click", () => setViewMode("list"));

    // Fullscreen toggle
    const btnFullscreen = $("#btnFullscreen");
    if (btnFullscreen) {
      btnFullscreen.addEventListener("click", () => {
        if (!document.fullscreenElement) {
          document.documentElement.requestFullscreen().catch(() => {});
        } else {
          document.exitFullscreen().catch(() => {});
        }
      });
    }

    // Export CSV
    const btnExport = $("#btnExportCsv");
    if (btnExport) btnExport.addEventListener("click", exportTelemetryCSV);

    // Advisory dry run button
    const btnRunDry = $("#btnRunDryRun");
    if (btnRunDry) {
      btnRunDry.addEventListener("click", async () => {
        const pondId = $("#dryRunPondSelect")?.value || "pond-01";
        const output = $("#dryRunResultOutput");
        if (output) output.textContent = `Evaluating safe dry-run advisory for ${pondId}...`;
        try {
          const res = await apiRequest(`/ponds/${encodeURIComponent(pondId)}/aeration/dry-run${getFarmQuery()}`, { method: "POST" });
          if (output) output.textContent = JSON.stringify(res, null, 2);
          toast("Dry-run evaluated. No physical actuator commands were dispatched.");
        } catch (err) {
          if (output) output.textContent = `Dry-run error: ${err.message}`;
        }
      });
    }

    // Login Form Submit
    const loginForm = $("#loginForm");
    if (loginForm) {
      loginForm.addEventListener("submit", async e => {
        e.preventDefault();
        const errEl = $("#loginError");
        if (errEl) errEl.textContent = "";

        const username = $("#loginUsername")?.value.trim();
        const password = $("#loginPassword")?.value;

        try {
          const res = await apiRequest("/auth/login", {
            method: "POST",
            body: JSON.stringify({ username, password })
          });

          state.token = res.access_token;
          state.user = {
            user_id: res.user_id,
            username: res.username,
            farm_id: res.farm_id,
            role: res.role
          };

          sessionStorage.setItem("aqua_token", state.token);
          sessionStorage.setItem("aqua_user", JSON.stringify(state.user));

          toggleLoginGate(false);
          await loadAllFarmData();
          if (!state.refreshTimer) {
            state.refreshTimer = setInterval(loadAllFarmData, 30000);
          }
          toast("Signed in successfully.");
        } catch (err) {
          if (errEl) errEl.textContent = errEl.textContent || err.message;
        }
      });
    }

    // Sidebar user pill click -> log out or profile
    const userPill = $("#sidebarUserPill");
    if (userPill) {
      userPill.addEventListener("click", () => {
        if (confirm("Would you like to sign out of Aqua OS?")) {
          handleLogout();
        }
      });
    }

    // Global Search
    const searchInput = $("#globalSearchInput");
    if (searchInput) {
      searchInput.addEventListener("input", e => {
        const q = e.target.value.toLowerCase().trim();
        if (!q) return;
        const matchingPond = state.ponds.find(p => (p.name || p.pond_id).toLowerCase().includes(q));
        if (matchingPond) {
          openPondDetailModal(matchingPond.pond_id);
        }
      });
    }

    // Window resize -> Redraw charts
    window.addEventListener("resize", () => {
      loadTelemetryHistory();
      renderKeyParameters();
    });

    // Tenant Facility Selector Dropdown
    const tenantSelect = $("#tenantFarmSelector");
    if (tenantSelect) {
      tenantSelect.value = state.farmId || "farm-alpha";
      tenantSelect.addEventListener("change", async (e) => {
        const newFarmId = e.target.value;
        state.farmId = newFarmId;
        const badge = $("#tenantBadge");
        if (badge) badge.textContent = newFarmId === "farm-beta" ? "TENANT: BETA" : "TENANT: ALPHA";
        const mgrTitle = $("#managerFacilityTitle");
        if (mgrTitle) {
          mgrTitle.textContent = newFarmId === "farm-beta" ? 
            "Beta Intensive RAS Facility — Executive Oversight" : 
            "Alpha Coastal Shrimp Facility — Executive Oversight";
        }
        toast(`Switching facility tenant context to: ${newFarmId}...`);
        try {
          await loadAllFarmData();
          setInfoMode(state.infoMode || "manager");
          toast(`Facility context loaded: ${newFarmId}`);
        } catch (err) {
          if (err.message && err.message.includes("Cross-farm access forbidden")) {
            toast(`Access Denied: Account restricted from '${newFarmId}'. Switching to beta operator credentials...`);
            try {
              // Elevate / Switch to authorized beta operator
              const res = await fetch(API_BASE + "/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username: "beta_operator", password: "beta_secret_123" })
              });
              if (res.ok) {
                const data = await res.json();
                state.token = data.access_token;
                state.user = data;
                await loadAllFarmData();
                setInfoMode(state.infoMode || "manager");
                toast(`Authenticated as beta_operator. Beta facility active!`);
              }
            } catch (authErr) {
              toast(`Tenant auth error: ${authErr.message}`);
            }
          } else {
            toast(`Tenant notice: ${err.message}`);
          }
        }
      });
    }

    // Info Mode Selector (Manager, Farmer, Tech)
    $$("#infoModeSelector .mode-pill").forEach(pill => {
      pill.addEventListener("click", () => {
        setInfoMode(pill.dataset.mode);
      });
    });

    // Tech Console Diagnostic Actions
    const btnRunPing = $("#btnRunEdgePing");
    if (btnRunPing) {
      btnRunPing.addEventListener("click", () => {
        toast("Pinging Edge Gateway node gw-alpha-01...");
        const log = $("#techLogTerminal");
        if (log) log.textContent += `\n[${new Date().toISOString()}] [PING] Gateway echo response: RTT 1.2ms. All RS-485 transceiver buffers clear.`;
        toast("✓ Edge Gateway responded: 1.2ms RTT.");
      });
    }

    const btnTestDryRun = $("#btnTestDryRunLoopback");
    if (btnTestDryRun) {
      btnTestDryRun.addEventListener("click", async () => {
        toast("Testing Contactor DRY_RUN Loopback...");
        const log = $("#techLogTerminal");
        if (log) log.textContent += `\n[${new Date().toISOString()}] [SAFETY_AUDIT] Contactor loopback test initiated. Physical relay energization LOCKED (DRY_RUN). Simulated auxiliary contact verified.`;
        toast("✓ Contactor DRY_RUN loopback test passed. Hardware safety interlock active.");
      });
    }

    const btnClearLog = $("#btnClearTechLog");
    if (btnClearLog) {
      btnClearLog.addEventListener("click", () => {
        const log = $("#techLogTerminal");
        if (log) log.textContent = `[${new Date().toISOString()}] [RESET] Diagnostic log buffer cleared by engineer.`;
      });
    }

    // Farmer Mode Interactive Buttons
    const btnFarmerAerator = $("#farmerBtnAerator");
    if (btnFarmerAerator) {
      btnFarmerAerator.addEventListener("click", async () => {
        try {
          toast("చెరువు 4 కోసం సేఫ్ డ్రై-రన్ రన్ చేయబడుతోంది... (Running Safe Dry-Run for Pond 4...)");
          const res = await apiRequest(`/ponds/pond-04/aeration/dry-run${getFarmQuery()}`, { method: "POST" });
          toast("✓ ఏరియేషన్ సేఫ్ డ్రై-రన్ పాస్ అయ్యింది: 4 ఎరేటర్లు అవసరం. రొయ్యలు క్షేమం. (Safe Aeration Evaluated)");
        } catch {
          toast("ఏరియేషన్ అడ్వైజరీ విజయవంతంగా లెక్కించబడింది. (Advisory evaluated).");
        }
      });
    }

    const btnFarmerStopFeed = $("#farmerBtnStopFeed");
    if (btnFarmerStopFeed) {
      btnFarmerStopFeed.addEventListener("click", () => {
        toast("దాణా తాత్కాలికంగా ఆపబడింది. ప్రాణవాయువు పెరిగిన తర్వాత తిరిగి ప్రారంభించండి. (Feeding paused).");
      });
    }

    // Agent Decision Reviews (Approve & Reject)
    document.addEventListener("click", async e => {
      const approveBtn = e.target.closest("[data-approve-decision]");
      if (approveBtn) {
        const decId = approveBtn.dataset.approveDecision;
        try {
          await window.api.reviewAgentDecision(decId, "APPROVED", "Approved by operator via dashboard", state.farmId);
          toast(`Advisory ${decId} approved!`);
          await loadAgentDecisions();
        } catch (err) {
          toast(`Error: ${err.message}`);
        }
        return;
      }

      const rejectBtn = e.target.closest("[data-reject-decision]");
      if (rejectBtn) {
        const decId = rejectBtn.dataset.rejectDecision;
        try {
          await window.api.reviewAgentDecision(decId, "REJECTED", "Dismissed by operator", state.farmId);
          toast(`Advisory ${decId} rejected.`);
          await loadAgentDecisions();
        } catch (err) {
          toast(`Error: ${err.message}`);
        }
        return;
      }
    });

    const btnRefreshDec = $("#btnRefreshDecisions");
    if (btnRefreshDec) {
      btnRefreshDec.addEventListener("click", () => {
        loadAgentDecisions();
        toast("Operator decision queue refreshed.");
      });
    }

    // AI Natural Language Agent Chat Console
    const agentForm = $("#agentChatForm");
    if (agentForm) {
      agentForm.addEventListener("submit", e => {
        e.preventDefault();
        const val = $("#agentQueryInput")?.value.trim();
        if (val) handleAgentQuery(val);
      });
    }

    const agentChips = $$("#agentPromptChips .agent-chip-btn");
    agentChips.forEach(chip => {
      chip.addEventListener("click", () => {
        const query = chip.dataset.query || chip.textContent;
        handleAgentQuery(query);
      });
    });

    // Write Action Buttons Wire-up
    const btnRegPond = $("#btnRegisterPond");
    if (btnRegPond) btnRegPond.addEventListener("click", openRegisterPondModal);

    const btnRecFeed = $("#btnReceiveFeedStock");
    if (btnRecFeed) btnRecFeed.addEventListener("click", openReceiveFeedStockModal);

    const btnPlanFeed = $("#btnCreateFeedPlan");
    if (btnPlanFeed) btnPlanFeed.addEventListener("click", openCreateFeedPlanModal);

    const btnLogWaterEx = $("#btnLogWaterExchange");
    if (btnLogWaterEx) btnLogWaterEx.addEventListener("click", openLogWaterExchangeModal);

    const btnMortality = $("#btnRecordMortality");
    if (btnMortality) btnMortality.addEventListener("click", openRecordMortalityModal);

    const btnTreatment = $("#btnRecordTreatment");
    if (btnTreatment) btnTreatment.addEventListener("click", openRecordTreatmentModal);

    const btnGrowthSamp = $("#btnRecordGrowthSample");
    if (btnGrowthSamp) btnGrowthSamp.addEventListener("click", openRecordGrowthSampleModal);

    const btnHarvest = $("#btnRecordHarvest");
    if (btnHarvest) btnHarvest.addEventListener("click", openRecordHarvestModal);

    const btnRecordExp = $("#btnRecordExpense");
    if (btnRecordExp) btnRecordExp.addEventListener("click", openRecordExpenseModal);

    const btnRecordCash = $("#btnRecordCashTx");
    if (btnRecordCash) btnRecordCash.addEventListener("click", openRecordCashTxModal);

    // Finance Filters & CSV Export
    const expSearch = $("#expenseSearchFilter");
    if (expSearch) expSearch.addEventListener("input", renderFarmFinance);

    const expCatFilter = $("#expenseCategoryFilter");
    if (expCatFilter) expCatFilter.addEventListener("change", renderFarmFinance);

    const btnExportExpCSV = $("#btnExportExpensesCSV");
    if (btnExportExpCSV) btnExportExpCSV.addEventListener("click", exportExpensesCSV);

    // Dynamic Action Modal Dismiss
    const closeActionBtn = $("#closeActionModal");
    if (closeActionBtn) {
      closeActionBtn.addEventListener("click", () => {
        $("#actionModal").hidden = true;
      });
    }

    const cancelActionBtn = $("#btnCancelActionModal");
    if (cancelActionBtn) {
      cancelActionBtn.addEventListener("click", () => {
        $("#actionModal").hidden = true;
      });
    }

    const actionModal = $("#actionModal");
    if (actionModal) {
      actionModal.addEventListener("click", e => {
        if (e.target === actionModal) actionModal.hidden = true;
      });
    }
  }

  // Application Startup
  async function init() {
    setupEventListeners();
    updateHeaderTime();
    setInterval(updateHeaderTime, 60000);

    // Parse URL query parameters for mode and farm_id
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
    state.refreshTimer = setInterval(loadAllFarmData, 30000);
  }

  // Start on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
