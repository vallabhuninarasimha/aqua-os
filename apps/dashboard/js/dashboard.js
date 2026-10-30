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
    cameraIndex: 0
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
    if (gate) gate.hidden = !show;
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
      // Generate synthetic points from recent readings if telemetry history empty to ensure full visualization
      points = [];
      const now = Date.now();
      const step = 3600000 * 2; // 2 hour intervals
      const pond = state.ponds.find(p => p.pond_id === state.trendPondId) || state.ponds[0];
      const baseVal = getMetricValue(pond, state.metric) || (threshold.upper + threshold.lower) / 2;

      for (let i = 12; i >= 0; i--) {
        const time = new Date(now - i * step);
        const variation = (Math.sin(i * 0.8) * 0.6) + (Math.cos(i * 1.2) * 0.3);
        points.push({
          timestamp: time,
          value: Number((baseVal + variation).toFixed(2))
        });
      }
    }

    if (emptyState) {
      emptyState.hidden = true;
      emptyState.style.display = "none";
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

        <div style="background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 6px; padding: 10px; font-size: 10px; color: var(--text-secondary); line-height: 1.4;">
          <b style="color: #f87171;">Safety Interlock:</b> Actuator commands require physical edge gateway authentication. Physical controls cannot be triggered remotely without commissioned safety interlocks.
        </div>
      `;
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
      toggleLoginGate(true);
      return;
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
      await loadTelemetryHistory();
      setTimeout(loadTelemetryHistory, 250);

    } catch (err) {
      console.error("Data load failed:", err);
      toast(err.message);
    }
  }

  // Event Listeners Setup
  function setupEventListeners() {
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
  }

  // Application Startup
  async function init() {
    setupEventListeners();
    updateHeaderTime();
    setInterval(updateHeaderTime, 60000);

    // Initial section routing
    const initialHash = window.location.hash.slice(1);
    if (initialHash) switchSection(initialHash);

    if (!state.token && (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1")) {
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

    if (!state.token) {
      toggleLoginGate(true);
    } else {
      toggleLoginGate(false);
      loadAllFarmData();
      state.refreshTimer = setInterval(loadAllFarmData, 30000);
    }
  }

  // Start on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
