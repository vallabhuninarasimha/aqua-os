/**
 * Aqua OS - Real-Time Dashboard Controller
 * Orchestrates 20-pond overview, live SSE streaming updates, SVG trends, and simulator actions.
 */

const state = {
  ponds: {}, // map of pond_id -> pondCard object
  summary: null,
  activePondId: null,
  activeMetricTab: "dissolved_oxygen",
  trendChart: null,
  historyCache: {}, // pond_id -> list of historical packets
  simulatorRunning: false,
  filterStatus: "ALL",
};

const METRIC_CONFIG = {
  dissolved_oxygen: { name: "Dissolved Oxygen", unit: "mg/L", color: "#38bdf8", thresholds: { min_critical: 3.0, min_warning: 4.0 } },
  temperature: { name: "Temperature", unit: "°C", color: "#fb923c", thresholds: { min_warning: 26.0, max_warning: 32.0 } },
  ph: { name: "pH", unit: "pH", color: "#a855f7", thresholds: { min_warning: 7.5, max_warning: 8.5 } },
  salinity: { name: "Salinity", unit: "ppt", color: "#34d399", thresholds: { min_warning: 15.0, max_warning: 35.0 } },
};

document.addEventListener("DOMContentLoaded", () => {
  initApp();
});

async function initApp() {
  setupEventListeners();

  if (!api.isAuthenticated()) {
    showLoginModal();
    return;
  }

  updateUserUI();
  await loadOverview();
  initStream();
  startFreshnessTimer();
}

function setupEventListeners() {
  // Top Navigation Module Tabs
  document.querySelectorAll(".nav-tab-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      document.querySelectorAll(".nav-tab-btn").forEach((b) => b.classList.remove("active"));
      e.currentTarget.classList.add("active");
      const targetId = e.currentTarget.getAttribute("data-target");
      if (targetId) {
        const targetEl = document.getElementById(targetId);
        if (targetEl) {
          targetEl.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      }
    });
  });

  // Pond Matrix Status Filters
  document.querySelectorAll(".pond-filter-pill").forEach((pill) => {
    pill.addEventListener("click", (e) => {
      document.querySelectorAll(".pond-filter-pill").forEach((p) => p.classList.remove("active"));
      e.currentTarget.classList.add("active");
      state.filterStatus = e.currentTarget.getAttribute("data-filter") || "ALL";
      applyPondFilter();
    });
  });

  // Login form
  const loginForm = document.getElementById("loginForm");
  if (loginForm) {
    loginForm.addEventListener("submit", handleLoginSubmit);
  }

  // Simulator controls
  const btnToggleSim = document.getElementById("btnToggleSim");
  if (btnToggleSim) btnToggleSim.addEventListener("click", toggleSimulator);

  const btnStepSim = document.getElementById("btnStepSim");
  if (btnStepSim) btnStepSim.addEventListener("click", stepSimulator);

  const btnApplyScenario = document.getElementById("btnApplyScenario");
  if (btnApplyScenario) btnApplyScenario.addEventListener("click", applyScenario);

  const btnResetScenarios = document.getElementById("btnResetScenarios");
  if (btnResetScenarios) btnResetScenarios.addEventListener("click", resetAllScenarios);

  // Logout button
  const btnLogout = document.getElementById("btnLogout");
  if (btnLogout) btnLogout.addEventListener("click", handleLogout);

  // Modal close
  const btnCloseModal = document.getElementById("btnCloseDetailModal");
  if (btnCloseModal) btnCloseModal.addEventListener("click", closeDetailModal);

  // Metric tab clicks inside detail modal
  // Metric tab clicks inside detail modal
  const metricTabs = document.querySelectorAll(".chart-tab-btn");
  metricTabs.forEach((tab) => {
    tab.addEventListener("click", (e) => {
      const metric = e.target.getAttribute("data-metric");
      switchMetricTab(metric);
    });
  });

  // Modal navigation tabs
  const modalTabBtns = document.querySelectorAll(".modal-tab-btn");
  modalTabBtns.forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const tabId = e.target.getAttribute("data-tab");
      switchModalTab(tabId);
    });
  });

  // Hardware sensor calibration
  const btnSaveCalib = document.getElementById("btnSaveCalibration");
  if (btnSaveCalib) btnSaveCalib.addEventListener("click", handleSaveCalibration);

  // Dry-run aeration evaluation
  const btnRunDryRun = document.getElementById("btnRunDryRun");
  if (btnRunDryRun) btnRunDryRun.addEventListener("click", handleRunDryRun);

  // Stocking & biomass update
  const btnUpdateStock = document.getElementById("btnUpdateStocking");
  if (btnUpdateStock) btnUpdateStock.addEventListener("click", handleUpdateStocking);

  // Manual feeding log and view controls
  const btnLogFeed = document.getElementById("btnLogFeeding");
  if (btnLogFeed) btnLogFeed.addEventListener("click", handleLogFeeding);

  const btnViewFeedLogs = document.getElementById("btnViewFeedLogs");
  if (btnViewFeedLogs) btnViewFeedLogs.addEventListener("click", () => switchFeedingView("logs"));

  const btnViewDailySummaries = document.getElementById("btnViewDailySummaries");
  if (btnViewDailySummaries) btnViewDailySummaries.addEventListener("click", () => switchFeedingView("daily"));

  const btnFilterFeedLogs = document.getElementById("btnFilterFeedLogs");
  if (btnFilterFeedLogs) btnFilterFeedLogs.addEventListener("click", handleFilterFeedLogs);

  const btnResetFeedFilter = document.getElementById("btnResetFeedFilter");
  if (btnResetFeedFilter) btnResetFeedFilter.addEventListener("click", handleResetFeedFilter);

  // Growth sampling submission
  const btnLogSample = document.getElementById("btnLogSample");
  if (btnLogSample) btnLogSample.addEventListener("click", handleLogSample);

  // Harvest plan update
  const btnSaveHarvest = document.getElementById("btnSaveHarvestPlan");
  if (btnSaveHarvest) btnSaveHarvest.addEventListener("click", handleSaveHarvestPlan);

  // Close / Harvest active batch
  const btnCloseBatch = document.getElementById("btnCloseActiveBatch");
  if (btnCloseBatch) btnCloseBatch.addEventListener("click", handleCloseActiveBatch);

  // Health, Mortality & Treatments
  const btnLogMort = document.getElementById("btnLogMortality");
  if (btnLogMort) btnLogMort.addEventListener("click", handleLogMortality);

  const btnLogObs = document.getElementById("btnLogObservation");
  if (btnLogObs) btnLogObs.addEventListener("click", handleLogObservation);

  const btnLogTreat = document.getElementById("btnLogTreatment");
  if (btnLogTreat) btnLogTreat.addEventListener("click", handleLogTreatment);

  // Water Management event listeners
  const btnSaveWaterTargets = document.getElementById("btnSaveWaterTargets");
  if (btnSaveWaterTargets) btnSaveWaterTargets.addEventListener("click", handleSaveWaterTargets);

  const btnSetNormalClosed = document.getElementById("btnSetNormalClosed");
  if (btnSetNormalClosed) btnSetNormalClosed.addEventListener("click", () => handleSetNormalOutlet("CLOSED"));

  const btnSetNormalOpen = document.getElementById("btnSetNormalOpen");
  if (btnSetNormalOpen) btnSetNormalOpen.addEventListener("click", () => handleSetNormalOutlet("OPEN"));

  const btnToggleFullDrainLock = document.getElementById("btnToggleFullDrainLock");
  if (btnToggleFullDrainLock) btnToggleFullDrainLock.addEventListener("click", handleToggleFullDrainLock);

  const btnLogExchange = document.getElementById("btnLogExchange");
  if (btnLogExchange) btnLogExchange.addEventListener("click", handleLogWaterExchange);

  const btnUpdatePumpTx = document.getElementById("btnUpdatePumpTx");
  if (btnUpdatePumpTx) btnUpdatePumpTx.addEventListener("click", handleUpdatePumpFeeder);

  const btnTogglePumpSim = document.getElementById("btnTogglePumpSim");
  if (btnTogglePumpSim) btnTogglePumpSim.addEventListener("click", handleTogglePumpSim);

  const btnEvalAdvisory = document.getElementById("btnEvalAdvisory");
  if (btnEvalAdvisory) btnEvalAdvisory.addEventListener("click", handleEvaluatePumpAdvisory);
}

function switchModalTab(tabId) {
  document.querySelectorAll(".modal-tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-tab") === tabId);
  });
  document.querySelectorAll(".modal-tab-pane").forEach((pane) => {
    pane.classList.toggle("active", pane.id === tabId);
  });
}

function updateUserUI() {
  const user = api.currentUser;
  const userLabel = document.getElementById("userLabel");
  if (userLabel && user) {
    userLabel.innerHTML = `<strong>${user.user_id}</strong> (${user.role}) &bull; ${user.farm_id}`;
  }
}

async function loadPowerSummary() {
  try {
    const powerData = await api.getFarmPower();
    if (!powerData || powerData.length < 2) return;

    const tx1 = powerData.find((p) => p.transformer_id === "tx-1") || powerData[0];
    const tx2 = powerData.find((p) => p.transformer_id === "tx-2") || powerData[1];

    if (tx1) {
      document.getElementById("tx1Load").textContent = `${tx1.current_load_kw.toFixed(1)} kW`;
      document.getElementById("tx1Headroom").textContent = `${tx1.headroom_kw.toFixed(1)} kW`;
      document.getElementById("tx1Aerators").textContent = `${tx1.running_aerator_count} aerators`;
      const pct1 = Math.min(100, Math.round((tx1.current_load_kw / tx1.continuous_rating_80pct_kw) * 100));
      const bar1 = document.getElementById("tx1Bar");
      bar1.style.width = `${pct1}%`;
      bar1.className = `power-bar-fill ${tx1.overload_warning ? "warning" : ""}`;
      const badge1 = document.getElementById("tx1StatusBadge");
      badge1.textContent = tx1.overload_warning ? "OVERLOAD WARNING" : "NORMAL";
      badge1.className = `badge-tag ${tx1.overload_warning ? "WARNING" : "NORMAL"}`;
    }

    if (tx2) {
      document.getElementById("tx2Load").textContent = `${tx2.current_load_kw.toFixed(1)} kW`;
      document.getElementById("tx2Headroom").textContent = `${tx2.headroom_kw.toFixed(1)} kW`;
      document.getElementById("tx2Aerators").textContent = `${tx2.running_aerator_count} aerators`;
      const pct2 = Math.min(100, Math.round((tx2.current_load_kw / tx2.continuous_rating_80pct_kw) * 100));
      const bar2 = document.getElementById("tx2Bar");
      bar2.style.width = `${pct2}%`;
      bar2.className = `power-bar-fill ${tx2.overload_warning ? "warning" : ""}`;
      const badge2 = document.getElementById("tx2StatusBadge");
      badge2.textContent = tx2.overload_warning ? "OVERLOAD WARNING" : "NORMAL";
      badge2.className = `badge-tag ${tx2.overload_warning ? "WARNING" : "NORMAL"}`;
    }
  } catch (err) {
    console.error("Failed to load power summary:", err);
  }
}

async function loadFarmProductionRollup() {
  try {
    const prod = await api.getFarmProductionSummary();
    if (!prod) return;

    const elBiomass = document.getElementById("farmTotalBiomass");
    if (elBiomass) elBiomass.textContent = `${(prod.total_estimated_biomass_kg || 0).toLocaleString()} kg`;

    const elFeed = document.getElementById("farmCumulativeFeed");
    if (elFeed) elFeed.textContent = `${(prod.total_cumulative_feed_kg || 0).toLocaleString()} kg`;

    const elAbw = document.getElementById("farmAvgAbw");
    if (elAbw) elAbw.textContent = `${(prod.farm_average_abw_g || 0).toFixed(2)} g`;

    const elDoc = document.getElementById("farmAvgDoc");
    if (elDoc) elDoc.textContent = `Avg DOC ${prod.farm_average_doc || 1}`;

    const elFcr = document.getElementById("farmProdFcr");
    if (elFcr) {
      const fcrVal = prod.farm_production_fcr?.production_fcr;
      elFcr.textContent = fcrVal ? fcrVal.toFixed(2) : "N/A";
    }

    const elStatus = document.getElementById("farmSamplingStatus");
    const elStaleCount = document.getElementById("farmStalePondsCount");
    if (elStatus && elStaleCount) {
      if (prod.stale_sampling_pond_count > 0) {
        elStatus.textContent = "⚠️ Stale Samplings";
        elStatus.style.color = "var(--color-warning)";
        elStaleCount.textContent = `${prod.stale_sampling_pond_count} pond(s) need sampling`;
      } else {
        elStatus.textContent = "✓ All Ponds Current";
        elStatus.style.color = "var(--color-normal)";
        elStaleCount.textContent = "Samples up-to-date";
      }
    }
  } catch (err) {
    console.error("Failed to load farm production rollup:", err);
  }
}

async function loadOverview() {
  try {
    const data = await api.getDashboardOverview();
    renderSummary(data.summary);
    renderPondsGrid(data.ponds);
    updateSimulatorBadge(data.simulator_status);
    updateEdgeBadge(data.edge_status);
    await loadPowerSummary();
    await loadFarmProductionRollup();
    await loadWaterPumpSummary(data.intake_pump_summary);
  } catch (err) {
    if (err.message === "UNAUTHORIZED") {
      showLoginModal();
    } else {
      console.error("Failed to load overview:", err);
    }
  }
}

function initStream() {
  api.connectStream({
    onStateChange: (connState) => {
      const badge = document.getElementById("connectionStatusBadge");
      if (!badge) return;
      badge.className = `status-badge ${connState.toLowerCase()}`;
      badge.textContent = `LIVE SSE: ${connState}`;
    },
    onPondUpdate: (data) => {
      handleLivePondUpdate(data);
    },
    onSimulatorCycle: (data) => {
      const counter = document.getElementById("simStepCounter");
      if (counter) counter.textContent = `Step #${data.step_count}`;
    },
  });
}

function handleLivePondUpdate(data) {
  const pondId = data.pond_id;
  const packet = data.packet;
  const evaluation = data.evaluation;

  // Build card representation
  const card = state.ponds[pondId] || { pond_id: pondId, name: pondId };
  card.timestamp = packet.timestamp;
  card.freshness_seconds = 0.0;
  card.is_stale = false;
  card.is_simulated = packet.is_simulated;

  // Evaluate status
  if (evaluation) {
    card.status = evaluation.severity;
    card.is_safe = evaluation.is_safe;
    card.active_alerts = evaluation.messages;
    card.recommended_action = evaluation.recommended_action;
  } else {
    card.status = "NORMAL";
    card.is_safe = true;
    card.active_alerts = [];
  }

  // Metrics
  card.metrics = {};
  for (const [mType, mObj] of Object.entries(packet.metrics)) {
    card.metrics[mType] = {
      value: Number(mObj.value.toFixed(2)),
      unit: mObj.unit,
      quality: mObj.quality,
    };
  }

  // Aerator state
  card.aerator_status = "ON";
  if (packet.hardware_status && !packet.hardware_status.mains_power_ok) {
    card.aerator_status = "FAULT";
  }

  // Water level live sync
  if (packet.metrics && packet.metrics.water_level) {
    card.water_level_m = Number(packet.metrics.water_level.value.toFixed(2));
    const minM = card.water_level_min_m || 0.95;
    const maxM = card.water_level_max_m || 1.40;
    if (card.water_level_m < minM) {
      card.water_level_status = "LOW";
    } else if (card.water_level_m > maxM) {
      card.water_level_status = "HIGH";
    } else {
      card.water_level_status = "NORMAL";
    }
  }

  state.ponds[pondId] = card;
  updatePondCardDOM(card);
  recalculateSummary();

  // If detail modal is currently showing this pond, update detail view in real time
  if (state.activePondId === pondId) {
    updateDetailModalContent(card);
    if (!state.historyCache[pondId]) state.historyCache[pondId] = [];
    state.historyCache[pondId].push(packet);
    renderActiveTrendChart(pondId);
  }
}

function renderSummary(summary) {
  state.summary = summary;
  if (!summary) return;
  document.getElementById("kpiTotal").textContent = summary.total_ponds;
  document.getElementById("kpiNormal").textContent = summary.normal_ponds;
  document.getElementById("kpiWarning").textContent = summary.warning_ponds;
  document.getElementById("kpiCritical").textContent = summary.critical_ponds;
  document.getElementById("kpiDegraded").textContent = summary.degraded_ponds;
  document.getElementById("kpiAlerts").textContent = summary.active_alerts_count;
}

function recalculateSummary() {
  const ponds = Object.values(state.ponds);
  let normal = 0, warning = 0, critical = 0, degraded = 0, unknown = 0, alerts = 0;

  ponds.forEach((p) => {
    if (p.is_stale || p.status === "DEGRADED") degraded++;
    else if (p.status === "CRITICAL" || p.status === "EMERGENCY") critical++;
    else if (p.status === "WARNING") warning++;
    else if (p.status === "NORMAL") normal++;
    else unknown++;

    if (p.active_alerts) alerts += p.active_alerts.length;
  });

  renderSummary({
    total_ponds: ponds.length,
    normal_ponds: normal,
    warning_ponds: warning,
    critical_ponds: critical,
    degraded_ponds: degraded,
    unknown_ponds: unknown,
    active_alerts_count: alerts,
  });
}

function applyPondFilter() {
  const filter = state.filterStatus || "ALL";
  Object.values(state.ponds).forEach((pond) => {
    const cardEl = document.getElementById(`card-${pond.pond_id}`);
    if (!cardEl) return;
    let visible = true;
    if (filter === "ALL") {
      visible = true;
    } else if (filter === "NORMAL") {
      visible = pond.status === "NORMAL" && !pond.is_stale;
    } else if (filter === "WARNING") {
      visible = pond.status === "WARNING";
    } else if (filter === "CRITICAL") {
      visible = pond.status === "CRITICAL" || pond.status === "EMERGENCY";
    } else if (filter === "STALE") {
      visible = pond.is_stale || pond.status === "DEGRADED";
    }
    cardEl.style.display = visible ? "" : "none";
  });
}

function renderPondsGrid(pondsList) {
  const container = document.getElementById("pondsGridContainer");
  if (!container) return;
  container.innerHTML = "";

  pondsList.forEach((pond) => {
    state.ponds[pond.pond_id] = pond;
    const cardEl = createPondCardElement(pond);
    container.appendChild(cardEl);
  });
  applyPondFilter();
}

function createPondCardElement(pond) {
  const el = document.createElement("div");
  el.id = `card-${pond.pond_id}`;
  el.className = `pond-card status-${pond.status}`;
  el.setAttribute("data-pond-id", pond.pond_id);
  el.addEventListener("click", () => openPondDetailModal(pond.pond_id));

  el.innerHTML = getPondCardInnerHtml(pond);
  return el;
}

function updatePondCardDOM(pond) {
  const el = document.getElementById(`card-${pond.pond_id}`);
  if (!el) return;
  el.className = `pond-card status-${pond.status}`;
  el.innerHTML = getPondCardInnerHtml(pond);
  applyPondFilter();
}

function getPondCardInnerHtml(pond) {
  const doVal = pond.metrics?.dissolved_oxygen?.value ?? "--";
  const tempVal = pond.metrics?.temperature?.value ?? "--";
  const phVal = pond.metrics?.ph?.value ?? "--";
  const salVal = pond.metrics?.salinity?.value ?? "--";
  const wlVal = pond.water_level_m !== null && pond.water_level_m !== undefined
    ? `${pond.water_level_m.toFixed(2)}m`
    : (pond.metrics?.water_level?.value ? `${pond.metrics.water_level.value.toFixed(2)}m` : "--");
  const targetWl = pond.water_level_target_m ? `${pond.water_level_target_m.toFixed(2)}m` : "1.22m";
  const wlStatus = pond.water_level_status || "NORMAL";
  const normalOutlet = pond.normal_outlet_state || "CLOSED";
  const fullDrainLocked = pond.full_drain_locked !== false;
  const fullDrainState = fullDrainLocked ? "🔒 LOCKED" : (pond.full_drain_outlet_state || "CLOSED");

  const freshnessText = pond.freshness_seconds !== null && pond.freshness_seconds !== undefined
    ? `${Math.round(pond.freshness_seconds)}s ago`
    : "No Data";

  const staleClass = pond.is_stale ? "stale" : "";
  const aeratorClass = pond.aerator_status || "IDLE";

  let alertSnippet = "";
  if (pond.active_alerts && pond.active_alerts.length > 0) {
    alertSnippet = `<div class="pond-alert-snippet">${escapeHtml(pond.active_alerts[0])}</div>`;
  }

  return `
    <div class="pond-card-header">
      <div class="pond-identity">
        <h3>${escapeHtml(pond.name || pond.pond_id)}</h3>
        <span style="font-size:0.72rem;color:var(--text-muted);">${escapeHtml(pond.pond_id)} &bull; 0.75 ac &bull; 4.0 ft &bull; 150k PL</span>
      </div>
      <div class="pond-badges">
        <span class="badge-tag ${pond.status}">${pond.status}</span>
        ${pond.is_simulated ? '<span class="badge-tag SIMULATED">SIMULATED</span>' : ""}
      </div>
    </div>

    ${alertSnippet}

    <div class="pond-metrics-grid">
      <div class="metric-cell">
        <span class="metric-label">DO</span>
        <div class="metric-value-container">
          <span class="metric-value">${doVal}</span>
          <span class="metric-unit">mg/L</span>
        </div>
      </div>
      <div class="metric-cell">
        <span class="metric-label">TEMP</span>
        <div class="metric-value-container">
          <span class="metric-value">${tempVal}</span>
          <span class="metric-unit">°C</span>
        </div>
      </div>
      <div class="metric-cell">
        <span class="metric-label">pH</span>
        <div class="metric-value-container">
          <span class="metric-value">${phVal}</span>
          <span class="metric-unit">pH</span>
        </div>
      </div>
      <div class="metric-cell">
        <span class="metric-label">SALINITY</span>
        <div class="metric-value-container">
          <span class="metric-value">${salVal}</span>
          <span class="metric-unit">ppt</span>
        </div>
      </div>
    </div>

    <div style="display:flex;justify-content:space-between;align-items:center;background:rgba(0,0,0,0.25);border:1px solid rgba(255,255,255,0.06);border-radius:4px;padding:0.35rem 0.6rem;margin-top:0.4rem;font-size:0.75rem;">
      <div>
        <span style="color:var(--text-muted)">Water Level: </span>
        <strong style="color:${wlStatus === 'LOW' || wlStatus === 'HIGH' ? 'var(--color-warning)' : '#38bdf8'}">${wlVal}</strong>
        <span style="color:var(--text-muted);font-size:0.7rem;"> (tgt ${targetWl})</span>
      </div>
      <div>
        <span style="color:var(--text-muted)">Outlets: </span>
        <span style="color:#fff">${normalOutlet === 'OPEN' ? '<span style="color:var(--color-warning)">NORM:OPEN</span>' : 'NORM:CLSD'}</span>
        <span style="color:var(--text-muted);margin:0 0.2rem;">|</span>
        <span style="color:${fullDrainLocked ? 'var(--color-normal)' : '#ef4444'}">${fullDrainState}</span>
      </div>
    </div>

    <div class="pond-card-footer">
      <div class="aerator-pill ${aeratorClass}">
        &#9881; AERATOR: ${aeratorClass}
      </div>
      <div class="freshness-pill ${staleClass}" id="freshness-${pond.pond_id}">
        &#9201; ${freshnessText}
      </div>
    </div>
  `;
}

function startFreshnessTimer() {
  setInterval(() => {
    const now = Date.now();
    Object.values(state.ponds).forEach((pond) => {
      if (!pond.timestamp) return;
      const t = new Date(pond.timestamp).getTime();
      const sec = Math.max(0, Math.round((now - t) / 1000));
      pond.freshness_seconds = sec;

      const el = document.getElementById(`freshness-${pond.pond_id}`);
      if (el) {
        el.textContent = `\u23F1 ${sec}s ago`;
        if (sec > 60 && !pond.is_stale) {
          pond.is_stale = true;
          el.classList.add("stale");
        } else if (sec <= 60 && pond.is_stale) {
          pond.is_stale = false;
          el.classList.remove("stale");
        }
      }
    });
  }, 1000);
}

async function openPondDetailModal(pondId) {
  state.activePondId = pondId;
  const pond = state.ponds[pondId];
  if (!pond) return;

  const modal = document.getElementById("pondDetailModal");
  document.getElementById("modalPondTitle").textContent = `${pond.name || pondId} (${pondId})`;
  document.getElementById("detailModalStatus").className = `badge-tag ${pond.status || "NORMAL"}`;
  document.getElementById("detailModalStatus").textContent = pond.status || "NORMAL";

  // Reset to first tab
  switchModalTab("tab-trends");
  modal.classList.add("open");

  // Fetch full details, history, and health summary in parallel
  try {
    const [detail, history, healthSummary, waterStatus, waterExchanges] = await Promise.all([
      api.getPondDetailFull(pondId).catch((e) => {
        console.warn("Could not fetch pond detail:", e);
        return null;
      }),
      api.getPondHistory(pondId, "farm-alpha", 50).catch((e) => {
        console.warn("Could not fetch pond history:", e);
        return [];
      }),
      api.getPondHealthSummary(pondId, "farm-alpha").catch((e) => {
        console.warn("Could not fetch health summary:", e);
        return null;
      }),
      api.getPondWaterStatus(pondId, "farm-alpha").catch((e) => {
        console.warn("Could not fetch water status:", e);
        return null;
      }),
      api.getWaterExchanges(pondId, "farm-alpha", 50).catch((e) => {
        console.warn("Could not fetch water exchanges:", e);
        return [];
      }),
    ]);

    state.historyCache[pondId] = history;
    renderActiveTrendChart(pondId);

    if (detail) {
      populatePondDetailTabs(detail);
    }
    if (healthSummary) {
      populateHealthTab(healthSummary);
    }
    if (waterStatus) {
      populateWaterTab(pondId, waterStatus, waterExchanges);
    }
  } catch (err) {
    console.error("Failed to load pond modal data:", err);
  }
}

function populatePondDetailTabs(detail) {
  const cfg = detail.config || {};

  // 1. Metadata Grid in Tab 1
  document.getElementById("metaSpecies").textContent = cfg.species || "L. vannamei";
  document.getElementById("metaArea").textContent = `${cfg.area_acres || 0.75} Acres (${((cfg.area_acres || 0.75) * 4046.86).toFixed(0)} m²)`;
  document.getElementById("metaDepth").textContent = `${cfg.depth_feet || 4.0} Feet (${((cfg.depth_feet || 4.0) * 0.3048).toFixed(2)} m)`;
  document.getElementById("metaStocking").textContent = `${(cfg.stocking_count || 150000).toLocaleString()} PL`;
  document.getElementById("metaDoc").textContent = `DOC ${cfg.days_of_culture || 35}`;
  document.getElementById("metaTx").textContent = cfg.transformer_id === "tx-2" ? "Transformer 2 (23 kW)" : "Transformer 1 (23 kW)";

  // 2. Sensors Tab
  const sensors = detail.sensors || [];
  const sensorsTable = document.getElementById("sensorsTableBody");
  const sensorSelect = document.getElementById("calibSensorSelect");
  sensorsTable.innerHTML = "";
  sensorSelect.innerHTML = "";

  sensors.forEach((s) => {
    const opt = document.createElement("option");
    opt.value = s.sensor_id;
    opt.textContent = `${s.sensor_id} (${s.sensor_type})`;
    sensorSelect.appendChild(opt);

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${escapeHtml(s.sensor_id)}</strong></td>
      <td>${escapeHtml(s.sensor_type)}</td>
      <td><code>${escapeHtml(s.protocol)}</code></td>
      <td>#${s.device_address}</td>
      <td>${s.capabilities.map((c) => `<span class="badge-tag NORMAL" style="font-size:0.65rem">${c}</span>`).join(" ")}</td>
      <td>${s.has_integrated_temp ? '<span style="color:var(--color-normal)">✓ PT1000 Temp</span>' : '<span style="color:var(--text-muted)">No</span>'}</td>
      <td>${s.calibration_date ? new Date(s.calibration_date).toLocaleDateString() : "Factory"} (Offset: ${s.calibration_offset}, Slope: ${s.calibration_slope})</td>
      <td><span class="badge-tag ${s.status === "ONLINE" ? "NORMAL" : "WARNING"}">${s.status}</span></td>
    `;
    sensorsTable.appendChild(tr);
  });

  // 3. Aerators & Dry-Run Tab
  const aerators = detail.aerators || [];
  const aeratorsTable = document.getElementById("aeratorsTableBody");
  aeratorsTable.innerHTML = "";

  aerators.forEach((a) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${escapeHtml(a.aerator_id)}</strong></td>
      <td>${a.rating_kw} kW</td>
      <td>${escapeHtml(a.transformer_id)}</td>
      <td><code>${a.desired_state}</code></td>
      <td><span class="badge-tag ${a.verified_physical_state === "RUNNING" ? "NORMAL" : "DEGRADED"}">${a.verified_physical_state}</span></td>
      <td>${a.current_draw_amps.toFixed(1)} A</td>
      <td>${a.power_kw.toFixed(2)} kW</td>
      <td>${a.runtime_minutes_today.toFixed(0)} min</td>
      <td>
        <div style="display:flex;gap:0.25rem;">
          <button class="btn btn-outline" style="padding:0.15rem 0.35rem;font-size:0.7rem;${a.desired_state === 'FORCE_ON' ? 'border-color:var(--color-normal);color:var(--color-normal)' : ''}" onclick="handleSetAeratorOverride('${escapeHtml(a.aerator_id)}', 'FORCE_ON')">ON</button>
          <button class="btn btn-outline" style="padding:0.15rem 0.35rem;font-size:0.7rem;${a.desired_state === 'FORCE_OFF' ? 'border-color:var(--color-critical);color:var(--color-critical)' : ''}" onclick="handleSetAeratorOverride('${escapeHtml(a.aerator_id)}', 'FORCE_OFF')">OFF</button>
          <button class="btn btn-outline" style="padding:0.15rem 0.35rem;font-size:0.7rem;${a.desired_state === 'AUTO' ? 'border-color:var(--accent);color:var(--accent)' : ''}" onclick="handleSetAeratorOverride('${escapeHtml(a.aerator_id)}', 'AUTO')">AUTO</button>
        </div>
      </td>
    `;
    aeratorsTable.appendChild(tr);
  });

  // Daily Runtime Summary Strip
  const runSum = detail.aeration_runtime_summary || {};
  const elDailyRuntime = document.getElementById("aeroDailyRuntime");
  if (elDailyRuntime) elDailyRuntime.textContent = `${(runSum.runtime_hours_today || 0).toFixed(1)} h`;
  const elDailyRuntimeMin = document.getElementById("aeroDailyRuntimeMin");
  if (elDailyRuntimeMin) elDailyRuntimeMin.textContent = `${Math.round(runSum.runtime_minutes_today || 0)} min today`;
  const elRunningCount = document.getElementById("aeroRunningCount");
  if (elRunningCount) elRunningCount.textContent = `${runSum.running_aerators || 0} / ${runSum.total_aerators || aerators.length}`;
  const elTotalPower = document.getElementById("aeroTotalPower");
  if (elTotalPower) elTotalPower.textContent = `${(runSum.total_power_kw || 0).toFixed(1)} kW`;
  const elAssignedTx = document.getElementById("aeroAssignedTx");
  if (elAssignedTx) elAssignedTx.textContent = cfg.transformer_id === "tx-2" ? "Transformer 2 (TX-2)" : "Transformer 1 (TX-1)";
  const elTxHeadroom = document.getElementById("aeroTxHeadroom");
  const txStatus = detail.transformer_status || {};
  if (elTxHeadroom) elTxHeadroom.textContent = `${(txStatus.headroom_kw || 15.0).toFixed(1)} kW`;
  const elEnergy = document.getElementById("aeroEnergyKwh");
  if (elEnergy) elEnergy.textContent = `${(runSum.energy_kwh_today || 0).toFixed(1)} kWh`;

  // Decision & DO Risk Advisory
  const decision = detail.aeration_decision;
  if (decision) {
    const decBox = document.getElementById("aerationDecisionBox");
    decBox.className = `decision-box ${decision.proposed_action}`;
    const badge = document.getElementById("decisionActionBadge");
    badge.textContent = `PROPOSED: ${decision.proposed_action}`;
    badge.className = `badge-tag ${decision.proposed_action === "START" ? "NORMAL" : decision.proposed_action === "STOP" ? "CRITICAL" : "NORMAL"}`;
    document.getElementById("decisionReasonText").textContent = decision.reason;
    document.getElementById("decisionInterlocks").textContent = decision.interlocks_ok ? "OK" : "OVERLOAD BLOCK";

    // Provenance badge
    const provBadge = document.getElementById("aerationProvenanceBadge");
    if (provBadge) {
      provBadge.textContent = decision.is_simulated ? "SIMULATED TELEMETRY" : "PHYSICAL RS485";
      provBadge.className = `badge-tag ${decision.is_simulated ? "SIMULATED" : "NORMAL"}`;
    }

    // Risk badge and description
    const riskBadge = document.getElementById("aeroRiskBadge");
    if (riskBadge) {
      riskBadge.textContent = decision.risk_level || "NORMAL";
      riskBadge.className = `badge-tag ${decision.risk_level === "CRITICAL" ? "CRITICAL" : decision.risk_level === "MODERATE" ? "WARNING" : "NORMAL"}`;
    }
    const freshEl = document.getElementById("aeroFreshnessText");
    if (freshEl) {
      const freshSec = decision.sensor_freshness_seconds;
      freshEl.textContent = freshSec !== null && freshSec !== undefined ? `Reading freshness: ${Math.round(freshSec)}s ago` : "No Telemetry";
      freshEl.style.color = freshSec !== null && freshSec > 60 ? "var(--color-warning)" : "var(--text-muted)";
    }
    const riskDesc = document.getElementById("aeroRiskDesc");
    if (riskDesc) {
      const doVal = decision.do_value_mg_l !== null ? `${decision.do_value_mg_l.toFixed(2)} mg/L` : "--";
      if (decision.risk_level === "CRITICAL") {
        riskDesc.innerHTML = `<span style="color:var(--color-critical);font-weight:600;">CRITICAL HYPOXIA RISK:</span> Current DO (${doVal}) is below emergency threshold (3.0 mg/L). Immediate aeration required.`;
      } else if (decision.risk_level === "MODERATE") {
        riskDesc.innerHTML = `<span style="color:var(--color-warning);font-weight:600;">SUB-OPTIMAL OXYGEN WARNING:</span> Current DO (${doVal}) is below safe target (4.0 mg/L). State machine initiates aeration ON.`;
      } else if (decision.risk_level === "UNKNOWN") {
        riskDesc.innerHTML = `<span style="color:var(--color-degraded);font-weight:600;">SENSOR OFFLINE / DEGRADED:</span> Reading unavailable or stale. Operating in fail-safe safety mode.`;
      } else {
        riskDesc.innerHTML = `<span style="color:var(--color-normal);font-weight:600;">OPTIMAL DISSOLVED OXYGEN:</span> Current DO (${doVal}) is in healthy range (&ge; 4.5 mg/L). Aerators operate per hysteresis rules.`;
      }
    }
  }

  // Runtime History Table
  const history = detail.aeration_runtime_history || [];
  const decHistory = detail.aeration_decision_history || [];
  const historyTable = document.getElementById("aeratorHistoryTableBody");
  if (historyTable) {
    historyTable.innerHTML = "";
    if (history.length === 0 && decHistory.length === 0) {
      historyTable.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:1rem;">No duty-cycle logs recorded yet. Run dry-run advisory to record a decision audit.</td></tr>`;
    } else {
      // Show decisions and runtime logs
      decHistory.slice(0, 15).forEach((dh) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${dh.timestamp ? new Date(dh.timestamp).toLocaleTimeString() : "--"}</td>
          <td><strong>ALL UNITS</strong></td>
          <td><span class="badge-tag ${dh.proposed_action === "START" ? "NORMAL" : dh.proposed_action === "STOP" ? "CRITICAL" : "NORMAL"}" style="font-size:0.7rem">${dh.proposed_action}</span></td>
          <td>--</td>
          <td>${escapeHtml(dh.reason)}</td>
          <td><span class="badge-tag SIMULATED" style="font-size:0.65rem">SIMULATED</span></td>
        `;
        historyTable.appendChild(tr);
      });
      history.forEach((h) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${h.start_time ? new Date(h.start_time).toLocaleTimeString() : "--"}</td>
          <td><strong>${escapeHtml(h.aerator_id)}</strong></td>
          <td>${h.duration_minutes} min</td>
          <td>${h.energy_kwh} kWh</td>
          <td>${escapeHtml(h.trigger_reason)}</td>
          <td><span class="badge-tag ${h.is_simulated ? "SIMULATED" : "NORMAL"}" style="font-size:0.65rem">${h.is_simulated ? "SIMULATED" : "PHYSICAL"}</span></td>
        `;
        historyTable.appendChild(tr);
      });
    }
  }

  // 4. Growth, Sampling & Harvest Planning Tab
  const prod = detail.production_intelligence || {};
  const stock = prod.batch || detail.stocking || {};
  const latestSample = prod.latest_sample;
  const prevSample = prod.previous_sample;
  const fcr = prod.fcr_analysis || {};
  const harvest = prod.harvest_projection || {};
  const samples = prod.samples_history || [];

  document.getElementById("stockDoc").textContent = `DOC ${stock.days_of_culture || 35}`;
  document.getElementById("stockStockingDate").textContent = stock.stocking_date
    ? `Stocked: ${new Date(stock.stocking_date).toLocaleDateString()}`
    : "Stocked: --";
  document.getElementById("stockAbw").textContent = `${(stock.avg_body_weight_g || 8.5).toFixed(2)} g`;
  document.getElementById("stockAbwBasis").textContent = latestSample
    ? `${latestSample.measurement_type} (${latestSample.sampling_method})`
    : "PL BASELINE";

  const adgVal = prod.adg_g_per_day;
  document.getElementById("stockAdg").textContent =
    adgVal !== null && adgVal !== undefined
      ? `${adgVal >= 0 ? "+" : ""}${adgVal.toFixed(3)} g/d`
      : "Baseline";
  document.getElementById("stockAdgPrevComp").textContent =
    prevSample && latestSample
      ? `Gain: +${(latestSample.abw_g - prevSample.abw_g).toFixed(2)}g in ${Math.max(1, Math.round((new Date(latestSample.sample_date) - new Date(prevSample.sample_date)) / 86400000))}d`
      : "vs PL baseline interval";

  const surv = stock.estimated_survival_pct || 82.0;
  document.getElementById("stockSurvivalPct").textContent = `${surv.toFixed(1)} %`;
  const pop = Math.round((stock.initial_count || 150000) * (surv / 100.0));
  document.getElementById("stockLivePop").textContent = `~${pop.toLocaleString()} live shrimp`;
  document.getElementById("stockBiomass").textContent = `${(stock.estimated_biomass_kg || 1045.5).toLocaleString()} kg`;
  document.getElementById("stockFeedKg").textContent = `${(prod.cumulative_feed_kg || 0).toLocaleString()} kg`;

  // Stale sampling indicator badge
  const staleEl = document.getElementById("stockStaleBadgeWrapper");
  if (staleEl) {
    if (prod.is_sample_stale) {
      staleEl.innerHTML = `<span class="stale-badge">&#9888; SAMPLING STALE (${prod.days_since_sample || 0}d ago)</span>`;
    } else {
      staleEl.innerHTML = `<span class="badge-tag NORMAL">&check; SAMPLING CURRENT</span>`;
    }
  }

  // FCR Analysis
  document.getElementById("stockProdFcrBadge").textContent = fcr.production_fcr
    ? `PRODUCTION FCR: ${fcr.production_fcr.toFixed(2)}`
    : "PRODUCTION FCR: N/A";
  document.getElementById("stockApparentFcrBadge").textContent = fcr.apparent_fcr
    ? `APPARENT FCR: ${fcr.apparent_fcr.toFixed(2)}`
    : "APPARENT: N/A";
  document.getElementById("stockFcrFormulaText").textContent = fcr.formula_used
    ? `${fcr.formula_used} [Period: ${fcr.calculation_period_label || "Batch"}]`
    : "FCR requires valid positive biomass gain and cumulative feed.";
  const warnEl = document.getElementById("stockFcrWarningText");
  if (warnEl) {
    warnEl.textContent = (fcr.warnings || []).join(" | ");
  }

  // Historical Samples Table
  const samplesTable = document.getElementById("samplesTableBody");
  if (samplesTable) {
    samplesTable.innerHTML = "";
    if (samples.length === 0) {
      samplesTable.innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:1rem;">No sampling records yet for this batch. Submit sample above.</td></tr>`;
    } else {
      samples.forEach((s) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${s.sample_date ? new Date(s.sample_date).toLocaleDateString() : "--"}</td>
          <td><strong>DOC ${s.doc}</strong></td>
          <td>${s.sample_count}</td>
          <td><strong style="color:#fff">${s.abw_g.toFixed(2)} g</strong></td>
          <td>${s.adg_g_per_day !== null && s.adg_g_per_day !== undefined ? `${s.adg_g_per_day >= 0 ? "+" : ""}${s.adg_g_per_day.toFixed(3)}` : "-"}</td>
          <td><span class="badge-tag ${s.measurement_type === "MEASURED" ? "NORMAL" : "DEGRADED"}" style="font-size:0.65rem">${s.measurement_type}</span> <span style="font-size:0.75rem">${escapeHtml(s.sampling_method)}</span></td>
          <td>${(s.estimated_biomass_kg || 0).toLocaleString()} kg <span style="font-size:0.65rem;color:var(--text-muted)">[EST]</span></td>
          <td>${escapeHtml(s.observations || "-")}</td>
          <td><code>${escapeHtml(s.recorded_by)}</code></td>
        `;
        samplesTable.appendChild(tr);
      });
    }
  }

  // Harvest Planning Card
  document.getElementById("harvestTargetAbwInput").value = stock.target_abw_g || 25.0;
  document.getElementById("harvestPriceInput").value = stock.projected_sale_price_per_kg || 5.50;
  if (stock.target_harvest_date) {
    document.getElementById("harvestTargetDateInput").value = stock.target_harvest_date.substring(0, 10);
  }

  const remainG = Math.max(0, (stock.target_abw_g || 25.0) - (stock.avg_body_weight_g || 8.5));
  document.getElementById("harvestRemainGrowth").textContent = `${remainG.toFixed(1)} g`;
  document.getElementById("harvestDaysRemain").textContent =
    harvest.estimated_days_to_harvest !== null && harvest.estimated_days_to_harvest !== undefined
      ? `${harvest.estimated_days_to_harvest} days`
      : "N/A";
  document.getElementById("harvestEstDoc").textContent = harvest.estimated_harvest_doc
    ? `Target DOC ${harvest.estimated_harvest_doc}`
    : "ADG required";
  document.getElementById("harvestEstDate").textContent = harvest.estimated_harvest_date || "Projecting...";
  document.getElementById("harvestEstBiomass").textContent = harvest.estimated_harvest_biomass_kg
    ? `${harvest.estimated_harvest_biomass_kg.toLocaleString()} kg`
    : "N/A";
  document.getElementById("harvestProjRevenue").textContent = harvest.projected_gross_revenue
    ? `$ ${harvest.projected_gross_revenue.toLocaleString()}`
    : "$ --";

  // Batches Table
  loadPondBatchesTable(state.activePondId);

  // 5. Feeding Management Tab
  populateFeedingTab(state.activePondId, detail);

  // 6. Alerts Tab
  const alerts = detail.active_alerts || [];
  const alertsTable = document.getElementById("alertsTableBody");
  alertsTable.innerHTML = "";

  if (alerts.length === 0) {
    alertsTable.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--color-normal);padding:1rem;">✓ No active safety alerts for this pond.</td></tr>`;
  } else {
    alerts.forEach((alt) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><span class="badge-tag ${alt.severity}">${alt.severity}</span></td>
        <td><strong>${escapeHtml(alt.alert_code)}</strong></td>
        <td>
          <div style="color:#fff;">${escapeHtml(alt.message)}</div>
          <div style="font-size:0.75rem;color:var(--text-secondary);">${escapeHtml(alt.recommended_action || "")}</div>
        </td>
        <td>${alt.first_triggered_at ? new Date(alt.first_triggered_at).toLocaleTimeString() : "--"}</td>
        <td><span class="badge-tag ${alt.status}">${alt.status}</span></td>
        <td>
          ${alt.status === "ACTIVE" ? `<button class="btn btn-outline" style="padding:0.25rem 0.5rem;font-size:0.7rem;margin-right:0.25rem;" onclick="handleAcknowledgeAlert('${alt.alert_id}')">Acknowledge</button>` : ""}
          ${alt.status !== "RESOLVED" ? `<button class="btn btn-success" style="padding:0.25rem 0.5rem;font-size:0.7rem;" onclick="handleResolveAlert('${alt.alert_id}')">Resolve</button>` : ""}
        </td>
      `;
      alertsTable.appendChild(tr);
    });
  }
}

async function handleSaveCalibration() {
  const pondId = state.activePondId;
  const sensorId = document.getElementById("calibSensorSelect").value;
  const offset = document.getElementById("calibOffsetInput").value;
  const slope = document.getElementById("calibSlopeInput").value;
  const feedback = document.getElementById("calibFeedback");

  try {
    await api.calibrateSensor(pondId, sensorId, offset, slope);
    feedback.textContent = `✓ Calibrated ${sensorId}`;
    setTimeout(() => { feedback.textContent = ""; }, 3000);
    const detail = await api.getPondDetailFull(pondId);
    if (detail) populatePondDetailTabs(detail);
  } catch (err) {
    alert("Calibration failed: " + err.message);
  }
}

async function handleRunDryRun() {
  const pondId = state.activePondId;
  try {
    const decision = await api.triggerAerationDryRun(pondId);
    const decBox = document.getElementById("aerationDecisionBox");
    decBox.className = `decision-box ${decision.proposed_action}`;
    const badge = document.getElementById("decisionActionBadge");
    badge.textContent = `PROPOSED: ${decision.proposed_action}`;
    badge.className = `badge-tag ${decision.proposed_action === "START" ? "NORMAL" : decision.proposed_action === "STOP" ? "CRITICAL" : "NORMAL"}`;
    document.getElementById("decisionReasonText").textContent = decision.reason;
    document.getElementById("decisionInterlocks").textContent = decision.interlocks_ok ? "OK" : "OVERLOAD BLOCK";
  } catch (err) {
    alert("Dry-run evaluation failed: " + err.message);
  }
}

async function handleUpdateStocking() {
  const pondId = state.activePondId;
  const doc = parseInt(document.getElementById("stockingDocInput").value, 10);
  const survival = parseFloat(document.getElementById("stockingSurvivalInput").value);
  const abw = parseFloat(document.getElementById("stockingAbwInput").value);
  const feedback = document.getElementById("stockingFeedback");

  try {
    await api.updatePondStocking(pondId, {
      days_of_culture: doc,
      estimated_survival_pct: survival,
      avg_body_weight_g: abw,
    });
    feedback.textContent = "✓ Biomass updated";
    setTimeout(() => { feedback.textContent = ""; }, 3000);
    const detail = await api.getPondDetailFull(pondId);
    if (detail) populatePondDetailTabs(detail);
  } catch (err) {
    alert("Update stocking failed: " + err.message);
  }
}

// ============================================================================
// Feeding Management Controllers & Daily Summary Handlers
// ============================================================================

let currentFeedingView = "logs"; // 'logs' or 'daily'
let currentFeedingDateFilter = null;

async function populateFeedingTab(pondId, detail) {
  if (!pondId) return;

  const stock = detail?.stocking || detail?.production_intelligence?.batch || {};
  const activeBatchId = stock.batch_id || "";

  // 1. Update Active Batch Badge and Form Input Default
  const batchBadge = document.getElementById("feedActiveBatchBadge");
  if (batchBadge) {
    batchBadge.textContent = activeBatchId ? `BATCH: ${activeBatchId}` : "BATCH: --";
  }

  const batchInput = document.getElementById("feedBatchInput");
  if (batchInput && !batchInput.value && activeBatchId) {
    batchInput.value = activeBatchId;
  }

  // 2. Fetch Daily Feeding Summary & Advisories concurrently
  try {
    const [summary, advisories] = await Promise.all([
      api.getPondFeedingSummary(pondId, "farm-alpha", activeBatchId || null, 30).catch((e) => {
        console.warn("Could not fetch feeding summary:", e);
        return null;
      }),
      api.getPondFeedingAdvisories(pondId, "farm-alpha", activeBatchId || null).catch((e) => {
        console.warn("Could not fetch feeding advisories:", e);
        return [];
      }),
    ]);

    // 3. Populate Feeding KPI Strip
    if (summary) {
      const elTodayKg = document.getElementById("feedTodayKg");
      if (elTodayKg) elTodayKg.textContent = `${(summary.today_feed_kg || 0).toFixed(1)} kg`;

      const elTodayEvents = document.getElementById("feedTodayEvents");
      if (elTodayEvents) elTodayEvents.textContent = `${summary.today_events_count || 0} events logged`;

      const el3Day = document.getElementById("feedRecent3DayAvg");
      if (el3Day) {
        el3Day.textContent = summary.recent_3day_avg_kg !== null && summary.recent_3day_avg_kg !== undefined
          ? `${summary.recent_3day_avg_kg.toFixed(1)} kg/d`
          : "-- kg/d";
      }

      const elBatchCum = document.getElementById("feedBatchCumulativeKg");
      if (elBatchCum) elBatchCum.textContent = `${(summary.batch_cumulative_feed_kg || 0).toLocaleString()} kg`;

      const elDaysRec = document.getElementById("feedDaysRecorded");
      if (elDaysRec) elDaysRec.textContent = `${summary.days_recorded || 0} days on record`;

      const elProdFcr = document.getElementById("feedProdFcr");
      if (elProdFcr) {
        if (summary.fcr_analysis?.is_calculable && summary.fcr_analysis?.production_fcr !== null) {
          elProdFcr.textContent = summary.fcr_analysis.production_fcr.toFixed(2);
        } else {
          elProdFcr.textContent = "N/A";
          elProdFcr.title = (summary.fcr_analysis?.warnings || []).join("; ") || "Insufficient biomass gain";
        }
      }

      const elApparentFcr = document.getElementById("feedApparentFcr");
      if (elApparentFcr) {
        if (summary.fcr_analysis?.apparent_fcr !== null && summary.fcr_analysis?.apparent_fcr !== undefined) {
          elApparentFcr.textContent = `Apparent: ${summary.fcr_analysis.apparent_fcr.toFixed(2)}`;
        } else {
          elApparentFcr.textContent = "Apparent: N/A";
        }
      }
    }

    // 4. Render Advisories Container
    renderFeedingAdvisories(advisories || summary?.advisories || []);

    // 5. Render Daily Summary Breakdown Table
    renderFeedingDailyTable(summary?.daily_summaries || []);

  } catch (err) {
    console.warn("Error rendering feeding summary:", err);
  }

  // 6. Fetch and Render Ration Logs Table
  await loadFeedingLogsTable(pondId, activeBatchId, currentFeedingDateFilter);
}

function renderFeedingAdvisories(advisories = []) {
  const container = document.getElementById("feedingAdvisoriesContainer");
  if (!container) return;
  container.innerHTML = "";

  if (!advisories || advisories.length === 0) {
    return;
  }

  advisories.forEach((adv) => {
    const card = document.createElement("div");
    card.className = "advisory-card";
    const isWarning = adv.severity === "WARNING" || adv.severity === "CRITICAL";
    card.style.background = isWarning ? "rgba(231,76,60,0.12)" : "rgba(56,189,248,0.12)";
    card.style.border = `1px solid ${isWarning ? "rgba(231,76,60,0.35)" : "rgba(56,189,248,0.35)"}`;
    card.style.borderRadius = "6px";
    card.style.padding = "0.55rem 0.8rem";
    card.style.marginBottom = "0.5rem";
    card.style.display = "flex";
    card.style.justifyContent = "space-between";
    card.style.alignItems = "flex-start";

    card.innerHTML = `
      <div style="flex:1;">
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.25rem;">
          <strong style="color:#fff;font-size:0.83rem;">${escapeHtml(adv.title || "Advisory")}</strong>
          <span class="badge-tag ${adv.severity}" style="font-size:0.65rem;">${adv.severity}</span>
        </div>
        <p style="margin:0 0 0.25rem 0;font-size:0.78rem;color:var(--text-secondary);">${escapeHtml(adv.message)}</p>
        <div style="font-size:0.74rem;color:var(--accent);"><strong>Recommendation:</strong> ${escapeHtml(adv.recommendation || "-")}</div>
      </div>
    `;
    container.appendChild(card);
  });
}

async function loadFeedingLogsTable(pondId, batchId = null, filterDate = null) {
  const table = document.getElementById("feedingTableBody");
  if (!table) return;

  try {
    let startDate = null;
    let endDate = null;
    if (filterDate) {
      startDate = `${filterDate}T00:00:00`;
      endDate = `${filterDate}T23:59:59`;
    }

    const feedingLogs = await api.getPondFeeding(pondId, "farm-alpha", batchId || null, startDate, endDate, 50);
    table.innerHTML = "";

    if (!feedingLogs || feedingLogs.length === 0) {
      table.innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:1rem;">No feeding records matching criteria. Record a ration entry above.</td></tr>`;
      return;
    }

    feedingLogs.forEach((f) => {
      const tr = document.createElement("tr");
      const d = f.timestamp ? new Date(f.timestamp) : null;
      const timeStr = d ? `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : "--";
      tr.innerHTML = `
        <td>${timeStr}</td>
        <td><code>${escapeHtml(f.batch_id || "--")}</code></td>
        <td><strong>${escapeHtml(f.feed_time_label || "--")}</strong></td>
        <td><strong style="color:#fff;">${f.feed_kg} kg</strong></td>
        <td>${f.feeding_event_count || 1}</td>
        <td>${escapeHtml(f.feed_type || "--")}</td>
        <td><span style="color:var(--color-normal);font-size:0.75rem;">${escapeHtml(f.tray_observation || "--")}</span></td>
        <td>${escapeHtml(f.notes || "-")}</td>
        <td><code>${escapeHtml(f.recorded_by || "--")}</code></td>
      `;
      table.appendChild(tr);
    });
  } catch (err) {
    console.warn("Could not load feeding logs:", err);
    table.innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--color-warning);padding:1rem;">Failed to load feeding logs.</td></tr>`;
  }
}

function renderFeedingDailyTable(dailySummaries = []) {
  const table = document.getElementById("feedingDailyTableBody");
  if (!table) return;
  table.innerHTML = "";

  if (!dailySummaries || dailySummaries.length === 0) {
    table.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:1rem;">No historical daily feeding records available.</td></tr>`;
    return;
  }

  dailySummaries.forEach((d) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${escapeHtml(d.date)}</strong></td>
      <td><strong style="color:var(--color-normal);">${(d.total_feed_kg || 0).toFixed(1)} kg</strong></td>
      <td>${d.event_count || 0}</td>
      <td><span style="font-size:0.75rem;color:var(--text-secondary);">${(d.feed_types || []).map(escapeHtml).join(", ") || "--"}</span></td>
      <td><span style="font-size:0.75rem;color:#38bdf8;">${(d.tray_observations || []).map(escapeHtml).join(" | ") || "--"}</span></td>
      <td><code>${d.entries_count || 0} logs</code></td>
    `;
    table.appendChild(tr);
  });
}

function switchFeedingView(view) {
  currentFeedingView = view;
  const logsWrapper = document.getElementById("feedingLogsTableWrapper");
  const dailyWrapper = document.getElementById("feedingDailySummaryWrapper");
  const btnLogs = document.getElementById("btnViewFeedLogs");
  const btnDaily = document.getElementById("btnViewDailySummaries");

  if (view === "daily") {
    if (logsWrapper) logsWrapper.style.display = "none";
    if (dailyWrapper) dailyWrapper.style.display = "block";
    if (btnLogs) { btnLogs.classList.remove("btn-primary"); btnLogs.classList.add("btn-outline"); }
    if (btnDaily) { btnDaily.classList.remove("btn-outline"); btnDaily.classList.add("btn-primary"); }
  } else {
    if (logsWrapper) logsWrapper.style.display = "block";
    if (dailyWrapper) dailyWrapper.style.display = "none";
    if (btnLogs) { btnLogs.classList.remove("btn-outline"); btnLogs.classList.add("btn-primary"); }
    if (btnDaily) { btnDaily.classList.remove("btn-primary"); btnDaily.classList.add("btn-outline"); }
  }
}

async function handleFilterFeedLogs() {
  const filterInput = document.getElementById("feedDateFilter");
  if (!filterInput || !filterInput.value) {
    alert("Please select a date to filter feeding logs.");
    return;
  }
  currentFeedingDateFilter = filterInput.value;
  if (state.activePondId) {
    const detail = await api.getPondDetailFull(state.activePondId).catch(() => null);
    await loadFeedingLogsTable(state.activePondId, detail?.stocking?.batch_id, currentFeedingDateFilter);
  }
}

async function handleResetFeedFilter() {
  const filterInput = document.getElementById("feedDateFilter");
  if (filterInput) filterInput.value = "";
  currentFeedingDateFilter = null;
  if (state.activePondId) {
    const detail = await api.getPondDetailFull(state.activePondId).catch(() => null);
    await loadFeedingLogsTable(state.activePondId, detail?.stocking?.batch_id, null);
  }
}

async function handleLogFeeding() {
  const pondId = state.activePondId;
  if (!pondId) {
    alert("No active pond selected.");
    return;
  }

  const feedKg = parseFloat(document.getElementById("feedKgInput").value);
  const eventCount = parseInt(document.getElementById("feedEventCountInput").value, 10) || 1;
  const feedType = document.getElementById("feedTypeInput").value;
  const feedTime = document.getElementById("feedTimeInput").value;
  const feedTray = document.getElementById("feedTrayInput").value;
  const batchId = document.getElementById("feedBatchInput").value.trim() || null;
  const notes = document.getElementById("feedNotesInput").value;
  const feedback = document.getElementById("feedFeedback");

  if (isNaN(feedKg) || feedKg <= 0) {
    alert("Please enter a valid feed amount strictly greater than 0 kg.");
    return;
  }
  if (isNaN(eventCount) || eventCount < 1) {
    alert("Feeding event count must be at least 1.");
    return;
  }

  try {
    const res = await api.logPondFeeding(pondId, {
      feed_kg: feedKg,
      feeding_event_count: eventCount,
      feed_type: feedType ? feedType.trim() : "Grower Pellet 38%",
      feed_time_label: feedTime,
      tray_observation: feedTray,
      batch_id: batchId,
      notes: notes ? notes.trim() : null,
    });

    if (feedback) {
      feedback.textContent = `✓ Feed logged (${feedKg} kg)`;
      setTimeout(() => { feedback.textContent = ""; }, 3000);
    }
    document.getElementById("feedNotesInput").value = "";

    // Refresh modal tabs and overview
    const detail = await api.getPondDetailFull(pondId);
    if (detail) {
      populatePondDetailTabs(detail);
    }
    await loadOverview();
  } catch (err) {
    alert("Feed log failed: " + err.message);
  }
}

async function handleAcknowledgeAlert(alertId) {
  try {
    await api.acknowledgeAlert(alertId, "Acknowledged by operator in modal");
    if (state.activePondId) {
      const detail = await api.getPondDetailFull(state.activePondId);
      if (detail) populatePondDetailTabs(detail);
    }
    await loadOverview();
  } catch (err) {
    alert("Acknowledge alert failed: " + err.message);
  }
}

async function handleResolveAlert(alertId) {
  try {
    await api.resolveAlert(alertId, "Resolved by operator in modal");
    if (state.activePondId) {
      const detail = await api.getPondDetailFull(state.activePondId);
      if (detail) populatePondDetailTabs(detail);
    }
    await loadOverview();
  } catch (err) {
    alert("Resolve alert failed: " + err.message);
  }
}

async function loadPondBatchesTable(pondId) {
  const table = document.getElementById("batchesTableBody");
  if (!table) return;
  try {
    const batches = await api.getPondBatches(pondId);
    table.innerHTML = "";
    if (!batches || batches.length === 0) {
      table.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:1rem;">No batch records.</td></tr>`;
      return;
    }
    batches.forEach((b) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${escapeHtml(b.batch_id)}</strong></td>
        <td>${b.stocking_date ? new Date(b.stocking_date).toLocaleDateString() : "--"}</td>
        <td>${escapeHtml(b.species || "--")}</td>
        <td>${(b.initial_count || 150000).toLocaleString()} PL</td>
        <td>${escapeHtml(b.seed_supplier || "--")}</td>
        <td>${escapeHtml(b.quality_notes || "--")}</td>
        <td><span class="badge-tag ${b.status === 'ACTIVE' ? 'NORMAL' : 'UNKNOWN'}">${escapeHtml(b.status || 'ACTIVE')}</span></td>
      `;
      table.appendChild(tr);
    });
  } catch (err) {
    console.error("Failed to load batches:", err);
  }
}

async function handleSaveHarvestPlan() {
  const pondId = state.activePondId;
  if (!pondId) return;

  const targetAbw = parseFloat(document.getElementById("harvestTargetAbwInput").value);
  const price = parseFloat(document.getElementById("harvestPriceInput").value);
    const targetDate = document.getElementById("harvestTargetDateInput").value || null;
  const feedback = document.getElementById("harvestFeedback");

  if (isNaN(targetAbw) || targetAbw <= 0) {
    alert("Target ABW must be greater than zero.");
    return;
  }

  try {
    const detail = await api.getPondDetailFull(pondId);
    const batchId = detail?.stocking?.batch_id;
    if (!batchId) {
      alert("No active batch found to update harvest plan.");
      return;
    }
    await api.updateHarvestPlan(batchId, targetAbw, targetDate, price);
    feedback.textContent = "✓ Harvest target updated";
    setTimeout(() => { feedback.textContent = ""; }, 3000);
    const updated = await api.getPondDetailFull(pondId);
    if (updated) populatePondDetailTabs(updated);
  } catch (err) {
    alert("Update harvest plan failed: " + err.message);
  }
}

async function handleCloseActiveBatch() {
  const pondId = state.activePondId;
  if (!confirm(`Are you sure you want to HARVEST and CLOSE the active production batch for pond ${pondId}? Historical records will be preserved.`)) {
    return;
  }

  const detail = await api.getPondDetailFull(pondId);
  const batchId = detail?.stocking?.batch_id;
  if (!batchId) return;

  const harvestedBiomass = prompt("Enter final harvested biomass in kg (or leave blank):", detail?.stocking?.estimated_biomass_kg || "");
  const harvestNotes = prompt("Enter optional harvest observations or processor destination:", "Standard harvest, clean pond drain");

  try {
    await api.closeBatch(batchId, "HARVESTED", harvestedBiomass || null, harvestNotes || null);
    alert(`Batch ${batchId} has been archived as HARVESTED. Historical records preserved.`);
    const updated = await api.getPondDetailFull(pondId);
    if (updated) populatePondDetailTabs(updated);
    await loadOverview();
  } catch (err) {
    alert("Close batch failed: " + err.message);
  }
}

function renderActiveTrendChart(pondId) {
  const history = state.historyCache[pondId] || [];
  const metricKey = state.activeMetricTab;
  const metricCfg = METRIC_CONFIG[metricKey];

  const dataPoints = history
    .filter((h) => h.metrics && h.metrics[metricKey])
    .map((h) => ({
      timestamp: h.timestamp,
      value: h.metrics[metricKey].value,
      quality: h.metrics[metricKey].quality,
    }));

  const chart = new SVGTimeSeriesChart("detailChartWrapper", {
    unit: metricCfg.unit,
    metricName: metricCfg.name,
    lineColor: metricCfg.color,
    fillColor: metricCfg.color.replace(")", ", 0.12)").replace("rgb", "rgba").replace("#", "rgba("),
  });

  chart.render(dataPoints, metricCfg.thresholds);
}

function switchMetricTab(metric) {
  if (!METRIC_CONFIG[metric]) return;
  state.activeMetricTab = metric;

  document.querySelectorAll(".chart-tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-metric") === metric);
  });

  if (state.activePondId) {
    renderActiveTrendChart(state.activePondId);
  }
}

function closeDetailModal() {
  state.activePondId = null;
  const modal = document.getElementById("pondDetailModal");
  if (modal) modal.classList.remove("open");
}

function updateSimulatorBadge(status) {
  state.simulatorRunning = status?.is_running || false;
  const btn = document.getElementById("btnToggleSim");
  if (btn) {
    btn.textContent = state.simulatorRunning ? "\u23F8 Pause Sim" : "\u25B6 Start Sim (3s)";
    btn.className = state.simulatorRunning ? "btn btn-warning" : "btn btn-success";
  }
}

function updateEdgeBadge(edgeStatus) {
  const badge = document.getElementById("edgeStatusBadge");
  if (!badge || !edgeStatus) return;
  badge.textContent = `EDGE: WAL SOVEREIGN | QUEUE: ${edgeStatus.sync_queue_depth}`;
}

async function toggleSimulator() {
  try {
    if (state.simulatorRunning) {
      await api.stopSimulator();
      state.simulatorRunning = false;
    } else {
      await api.startSimulator(3.0);
      state.simulatorRunning = true;
    }
    const status = await api.getSimulatorStatus();
    updateSimulatorBadge(status);
  } catch (err) {
    alert("Simulator operation failed: " + err.message);
  }
}

async function stepSimulator() {
  try {
    await api.stepSimulator();
  } catch (err) {
    alert("Step failed: " + err.message);
  }
}

async function applyScenario() {
  const select = document.getElementById("scenarioSelect");
  const pondId = document.getElementById("scenarioPondInput").value || "pond-03";
  const scenarioType = select.value;

  try {
    await api.injectScenario(pondId, scenarioType, 6.0);
    alert(`Injected scenario '${scenarioType}' on '${pondId}'.`);
  } catch (err) {
    alert("Scenario injection failed: " + err.message);
  }
}

async function resetAllScenarios() {
  try {
    await api.resetScenarios();
    alert("All ponds reset to normal biological operation.");
  } catch (err) {
    alert("Reset failed: " + err.message);
  }
}

function showLoginModal() {
  const modal = document.getElementById("loginModal");
  if (modal) modal.classList.add("open");
}

function hideLoginModal() {
  const modal = document.getElementById("loginModal");
  if (modal) modal.classList.remove("open");
}

async function handleLoginSubmit(e) {
  e.preventDefault();
  const u = document.getElementById("loginUsername").value;
  const p = document.getElementById("loginPassword").value;
  const errEl = document.getElementById("loginError");
  errEl.textContent = "";

  try {
    await api.login(u, p);
    hideLoginModal();
    updateUserUI();
    await loadOverview();
    initStream();
  } catch {
    errEl.textContent = "Invalid username or password.";
  }
}

function quickLogin(username, password) {
  document.getElementById("loginUsername").value = username;
  document.getElementById("loginPassword").value = password;
  document.getElementById("loginForm").dispatchEvent(new Event("submit"));
}

function handleLogout() {
  api.logout();
  location.reload();
}

function escapeHtml(text) {
  if (!text) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

window.handleAcknowledgeAlert = handleAcknowledgeAlert;
window.handleResolveAlert = handleResolveAlert;
window.quickLogin = quickLogin;

// ============================================================================
// Pond Health, Mortality & Treatment Management Handlers
// ============================================================================

function populateHealthTab(summary) {
  if (!summary) return;

  // 1. Health Status Badge
  const badge = document.getElementById("healthStatusBadge");
  if (badge) {
    const st = summary.health_status || "GOOD";
    badge.className = `badge-tag ${st === "GOOD" ? "NORMAL" : st === "CAUTION" ? "WARNING" : st === "CRITICAL" ? "CRITICAL" : "DEGRADED"}`;
    badge.textContent = st;
  }

  // 2. Harvest Restriction Alert Banner
  const restAlert = document.getElementById("harvestRestrictionAlert");
  if (restAlert) {
    if (summary.is_harvest_blocked && summary.active_harvest_restrictions?.length > 0) {
      const r = summary.active_harvest_restrictions[0];
      restAlert.style.background = "rgba(231,76,60,0.2)";
      restAlert.style.color = "#e74c3c";
      restAlert.style.borderColor = "rgba(231,76,60,0.4)";
      restAlert.innerHTML = `&#9888; HARVEST RESTRICTED: <strong>${escapeHtml(r.product_name)}</strong> active (${r.remaining_restriction_days}d left)`;
    } else {
      restAlert.style.background = "rgba(46,204,113,0.15)";
      restAlert.style.color = "#2ecc71";
      restAlert.style.borderColor = "rgba(46,204,113,0.3)";
      restAlert.innerHTML = `&#10003; No Active Harvest Restrictions`;
    }
  }

  // 3. Population Integrity & Reconciliation KPIs
  const p = summary.population_metrics || {};
  const elDocDead = document.getElementById("kpiDocDead");
  if (elDocDead) elDocDead.textContent = (p.cumulative_recorded_mortality || 0).toLocaleString();
  const elDocDeadPct = document.getElementById("kpiDocDeadPct");
  if (elDocDeadPct) elDocDeadPct.textContent = `${(p.confirmed_mortality_pct || 0).toFixed(2)}% Initial PL`;

  const elSampleSurv = document.getElementById("kpiSampleSurvival");
  if (elSampleSurv) elSampleSurv.textContent = `${(p.sampling_survival_pct || 85.0).toFixed(1)}%`;
  const elSamplePop = document.getElementById("kpiSamplePop");
  if (elSamplePop) elSamplePop.textContent = `~${(p.sampling_estimated_population || 0).toLocaleString()} Est.`;

  const elAdjPop = document.getElementById("kpiAdjPop");
  if (elAdjPop) elAdjPop.textContent = (p.conservative_adjusted_population || 0).toLocaleString();
  const elAdjSurv = document.getElementById("kpiAdjSurvival");
  if (elAdjSurv) elAdjSurv.textContent = `${(p.conservative_adjusted_survival_pct || 0).toFixed(1)}% Adjusted`;

  const elUnobs = document.getElementById("kpiUnobservedLoss");
  if (elUnobs) elUnobs.textContent = `${(p.estimated_unobserved_loss_pct || 0).toFixed(1)}%`;

  const elDead24 = document.getElementById("kpiDead24h");
  if (elDead24) elDead24.textContent = (summary.mortalities_last_24h || 0).toLocaleString();
  const elDead24Rate = document.getElementById("kpiDead24hRate");
  if (elDead24Rate) {
    const rate24 = ((summary.mortalities_last_24h || 0) / (p.initial_stock_count || 1)) * 100;
    elDead24Rate.textContent = `${rate24.toFixed(2)}% / 24h`;
  }

  // 4. Water Quality Context on Observations Header
  const wqBadge = document.getElementById("obsWqBadge");
  if (wqBadge) {
    const wq = summary.water_quality_snapshot || {};
    if (wq.telemetry_timestamp) {
      const doStr = wq.dissolved_oxygen !== null && wq.dissolved_oxygen !== undefined ? `${wq.dissolved_oxygen.toFixed(2)} mg/L` : "--";
      const tempStr = wq.temperature !== null && wq.temperature !== undefined ? `${wq.temperature.toFixed(1)}°C` : "--";
      const phStr = wq.ph !== null && wq.ph !== undefined ? wq.ph.toFixed(2) : "--";
      const salStr = wq.salinity !== null && wq.salinity !== undefined ? `${wq.salinity.toFixed(1)} ppt` : "--";
      wqBadge.textContent = `WQ Context: DO ${doStr} | Temp ${tempStr} | pH ${phStr} | Sal ${salStr} [${wq.data_source}] ${wq.is_stale ? '(STALE)' : '(LIVE)'}`;
    } else {
      wqBadge.textContent = "WQ Context: No real-time telemetry";
    }
  }

  // 5. Mortality Table
  const mortTable = document.getElementById("mortalityTableBody");
  if (mortTable) {
    mortTable.innerHTML = "";
    const mortalities = summary.recent_mortalities || [];
    if (mortalities.length === 0) {
      mortTable.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:0.75rem;">No mortality records logged yet.</td></tr>`;
    } else {
      mortalities.forEach((m) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${m.timestamp ? new Date(m.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : "--"}</td>
          <td><strong>DOC ${m.doc}</strong></td>
          <td><strong style="color:#e74c3c;">${m.dead_count.toLocaleString()} dead</strong></td>
          <td>${escapeHtml(m.collection_method)}</td>
          <td>${escapeHtml(m.suspected_reason)}</td>
          <td>${escapeHtml(m.notes || "-")}</td>
          <td><code>${escapeHtml(m.recorded_by)}</code></td>
          <td>
            ${m.is_corrected
              ? `<span class="badge-tag WARNING" title="${escapeHtml(m.correction_notes || '')}">CORRECTED</span>`
              : `<button class="btn btn-outline" style="padding:0.2rem 0.5rem;font-size:0.7rem;" onclick="handleCorrectMortality('${m.mortality_id}', ${m.dead_count})">Audit</button>`
            }
          </td>
        `;
        mortTable.appendChild(tr);
      });
    }
  }

  // 6. Observations Table
  const obsTable = document.getElementById("observationsTableBody");
  if (obsTable) {
    obsTable.innerHTML = "";
    const observations = summary.recent_observations || [];
    if (observations.length === 0) {
      obsTable.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:0.75rem;">No health observations recorded yet.</td></tr>`;
    } else {
      observations.forEach((o) => {
        const tr = document.createElement("tr");
        const wqCtx = o.water_quality_context;
        const wqText = wqCtx
          ? `DO ${wqCtx.dissolved_oxygen ?? '--'} | ${wqCtx.temperature ?? '--'}°C | pH ${wqCtx.ph ?? '--'}`
          : "--";

        tr.innerHTML = `
          <td>${o.timestamp ? new Date(o.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : "--"}</td>
          <td><strong>DOC ${o.doc}</strong></td>
          <td>${escapeHtml(o.swimming_activity)} / <span style="color:#fff;">${escapeHtml(o.feed_response)}</span></td>
          <td>${escapeHtml(o.gill_condition)} / ${escapeHtml(o.gut_condition)}</td>
          <td>${escapeHtml(o.visible_lesions)} <span class="badge-tag ${o.severity === "NORMAL" ? "NORMAL" : "WARNING"}" style="font-size:0.65rem;">${o.severity}</span></td>
          <td><span style="font-size:0.75rem;color:var(--text-secondary);">${wqText}</span></td>
          <td>${escapeHtml(o.notes || "-")}</td>
          <td><code>${escapeHtml(o.recorded_by)}</code></td>
        `;
        obsTable.appendChild(tr);
      });
    }
  }

  // 7. Treatments Table
  const trtTable = document.getElementById("treatmentsTableBody");
  if (trtTable) {
    trtTable.innerHTML = "";
    const treatments = summary.recent_treatments || [];
    if (treatments.length === 0) {
      trtTable.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:0.75rem;">No treatment records logged yet.</td></tr>`;
    } else {
      treatments.forEach((t) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${t.timestamp ? new Date(t.timestamp).toLocaleDateString() : "--"}</td>
          <td><strong>${escapeHtml(t.product_name)}</strong> <span style="font-size:0.7rem;color:var(--text-muted);">(${escapeHtml(t.active_ingredient || "None specified")})</span></td>
          <td>${escapeHtml(t.reason_for_treatment)}</td>
          <td>${t.dosage_amount} ${escapeHtml(t.dosage_unit)}</td>
          <td>${t.withdrawal_period_days} days</td>
          <td>
            ${t.is_harvest_restricted
              ? `<span class="badge-tag CRITICAL">RESTRICTED (${t.remaining_restriction_days}d left)</span>`
              : `<span class="badge-tag NORMAL">CLEARED</span>`
            }
          </td>
          <td>
            ${t.has_missing_label_info
              ? `<span style="color:#e74c3c;font-size:0.72rem;">&#9888; Incomplete label data</span>`
              : `<span style="font-size:0.75rem;">${escapeHtml(t.product_label_info || "Standard")}</span>`
            }
          </td>
          <td><code>${escapeHtml(t.recorded_by)}</code></td>
        `;
        trtTable.appendChild(tr);
      });
    }
  }
}

async function handleLogMortality() {
  const pondId = state.activePondId;
  const count = parseInt(document.getElementById("mortDeadCount").value, 10);
  const method = document.getElementById("mortCollectionMethod").value;
  const reason = document.getElementById("mortSuspectedReason").value;
  const notes = document.getElementById("mortNotes").value;

  if (isNaN(count) || count <= 0) {
    alert("Please enter a valid positive dead count.");
    return;
  }

  try {
    const res = await api.recordMortality(pondId, {
      dead_count: count,
      collection_method: method,
      suspected_reason: reason,
      notes: notes || null,
    });

    document.getElementById("mortNotes").value = "";
    if (res.raised_alerts && res.raised_alerts.length > 0) {
      alert(`Mortality logged (${count} dead). Alert raised: ${res.raised_alerts[0].alert_code}`);
    }

    // Refresh health tab and pond details
    const healthSummary = await api.getPondHealthSummary(pondId);
    if (healthSummary) populateHealthTab(healthSummary);
    const detail = await api.getPondDetailFull(pondId);
    if (detail) populatePondDetailTabs(detail);
    await loadOverview();
  } catch (err) {
    alert("Log mortality failed: " + err.message);
  }
}

async function handleCorrectMortality(mortalityId, currentCount) {
  const pondId = state.activePondId;
  const input = prompt("Enter corrected physical dead count:", currentCount);
  if (input === null) return;
  const newCount = parseInt(input, 10);
  if (isNaN(newCount) || newCount < 0) {
    alert("Please enter a valid non-negative integer for dead count.");
    return;
  }

  const reason = prompt("Enter required audit reason for modifying this mortality entry:", "Re-siphoning count verification");
  if (!reason || reason.trim().length < 3) {
    alert("Audit reason is mandatory for correcting mortality records.");
    return;
  }

  try {
    await api.correctMortality(mortalityId, {
      corrected_dead_count: newCount,
      correction_notes: reason.trim(),
    });

    const healthSummary = await api.getPondHealthSummary(pondId);
    if (healthSummary) populateHealthTab(healthSummary);
    const detail = await api.getPondDetailFull(pondId);
    if (detail) populatePondDetailTabs(detail);
    await loadOverview();
  } catch (err) {
    alert("Correct mortality failed: " + err.message);
  }
}

async function handleLogObservation() {
  const pondId = state.activePondId;
  const count = parseInt(document.getElementById("obsSampleCount").value, 10) || 20;
  const method = document.getElementById("obsMethod").value;
  const swimming = document.getElementById("obsSwimming").value;
  const feed = document.getElementById("obsFeedResponse").value;
  const gills = document.getElementById("obsGills").value;
  const gut = document.getElementById("obsGut").value;
  const lesions = document.getElementById("obsLesions").value;
  const severity = document.getElementById("obsSeverity").value;
  const notes = document.getElementById("obsNotes").value;

  try {
    const res = await api.recordHealthObservation(pondId, {
      sample_count: count,
      observation_method: method,
      swimming_activity: swimming,
      feed_response: feed,
      gill_condition: gills,
      gut_condition: gut,
      visible_lesions: lesions,
      severity: severity,
      notes: notes || null,
    });

    document.getElementById("obsNotes").value = "";
    if (res.raised_alerts && res.raised_alerts.length > 0) {
      alert(`Observation saved. Health risk alert raised: ${res.raised_alerts[0].alert_code}`);
    }

    const healthSummary = await api.getPondHealthSummary(pondId);
    if (healthSummary) populateHealthTab(healthSummary);
    const detail = await api.getPondDetailFull(pondId);
    if (detail) populatePondDetailTabs(detail);
    await loadOverview();
  } catch (err) {
    alert("Record observation failed: " + err.message);
  }
}

async function handleLogTreatment() {
  const pondId = state.activePondId;
  const product = document.getElementById("treatProduct").value;
  const active = document.getElementById("treatActive").value;
  const dosage = parseFloat(document.getElementById("treatDosage").value);
  const unit = document.getElementById("treatUnit").value;
  const reason = document.getElementById("treatReason").value;
  const withdrawal = parseInt(document.getElementById("treatWithdrawal").value, 10) || 0;
  const label = document.getElementById("treatLabel").value;

  if (!product || product.trim().length === 0) {
    alert("Please enter the product name.");
    return;
  }
  if (isNaN(dosage) || dosage <= 0) {
    alert("Please enter a valid positive dosage amount.");
    return;
  }
  if (!reason || reason.trim().length === 0) {
    alert("Please enter the reason for treatment.");
    return;
  }

  try {
    await api.recordTreatment(pondId, {
      product_name: product.trim(),
      active_ingredient: active ? active.trim() : null,
      dosage_amount: dosage,
      dosage_unit: unit,
      reason_for_treatment: reason.trim(),
      withdrawal_period_days: withdrawal,
      product_label_info: label ? label.trim() : null,
    });

    document.getElementById("treatProduct").value = "";
    document.getElementById("treatActive").value = "";
    document.getElementById("treatReason").value = "";
    document.getElementById("treatLabel").value = "";

    const healthSummary = await api.getPondHealthSummary(pondId);
    if (healthSummary) populateHealthTab(healthSummary);
    const detail = await api.getPondDetailFull(pondId);
    if (detail) populatePondDetailTabs(detail);
    await loadOverview();
  } catch (err) {
    alert("Record treatment failed: " + err.message);
  }
}

window.handleCorrectMortality = handleCorrectMortality;

// ============================================================================
// Water Management & River Intake Pump Controllers
// ============================================================================

async function loadWaterPumpSummary(intakeSummary) {
  try {
    let pump = intakeSummary?.pump;
    let advisory = intakeSummary?.advisory;

    if (!pump) {
      pump = await api.getPumpStatus().catch(() => null);
    }
    if (!advisory && pump) {
      advisory = await api.getPumpAdvisory(pump.pump_id).catch(() => null);
    }

    if (pump) {
      const elFeeder = document.getElementById("pumpFeeder");
      if (elFeeder) {
        if (pump.transformer_id === "tx-1") elFeeder.textContent = "Transformer 1 (TX-1)";
        else if (pump.transformer_id === "tx-2") elFeeder.textContent = "Transformer 2 (TX-2)";
        else elFeeder.textContent = "Unconfigured";
      }

      const elRating = document.getElementById("pumpRating");
      if (elRating) {
        if (pump.rating_kw !== null && pump.rating_kw !== undefined && pump.motor_hp !== null && pump.motor_hp !== undefined) {
          elRating.textContent = `${pump.motor_hp} HP / ${pump.rating_kw} kW`;
          elRating.style.color = "#fff";
        } else if (pump.rating_kw !== null && pump.rating_kw !== undefined) {
          elRating.textContent = `${pump.rating_kw} kW`;
          elRating.style.color = "#fff";
        } else {
          elRating.textContent = "Unconfigured (Pending Survey)";
          elRating.style.color = "var(--color-warning)";
        }
      }

      const elAmps = document.getElementById("pumpAmps");
      if (elAmps) elAmps.textContent = `${(pump.current_draw_amps || 0).toFixed(1)} A`;

      const elKw = document.getElementById("pumpKw");
      if (elKw) elKw.textContent = `${(pump.power_kw || 0).toFixed(1)} kW`;

      const elLastRun = document.getElementById("pumpLastRun");
      if (elLastRun) elLastRun.textContent = pump.last_run_timestamp ? new Date(pump.last_run_timestamp).toLocaleTimeString() : "Never";

      const badge = document.getElementById("pumpStatusBadge");
      if (badge) {
        badge.textContent = `${pump.physical_state} (${pump.desired_state === "RUNNING" ? "ACTIVE" : "STANDBY"})`;
        badge.className = `badge-tag ${pump.physical_state === "RUNNING" ? "WARNING" : "NORMAL"}`;
      }

      const txSelect = document.getElementById("pumpTxSelect");
      if (txSelect && pump.transformer_id) txSelect.value = pump.transformer_id;
    }

    if (advisory) {
      const badge = document.getElementById("advisoryActionBadge");
      if (badge) {
        badge.textContent = advisory.proposed_action;
        badge.className = `badge-tag ${advisory.proposed_action === "START" ? "NORMAL" : "WARNING"}`;
      }

      const elHeadroom = document.getElementById("advisoryHeadroom");
      if (elHeadroom) elHeadroom.textContent = `${advisory.transformer_headroom_kw.toFixed(1)} kW`;

      const elReason = document.getElementById("advisoryReason");
      if (elReason) elReason.textContent = advisory.reason;
    }
  } catch (err) {
    console.error("Failed to load water pump summary:", err);
  }
}

function populateWaterTab(pondId, waterStatus, waterExchanges = []) {
  if (!waterStatus) return;

  const depthVal = waterStatus.current_level_m !== null && waterStatus.current_level_m !== undefined
    ? `${waterStatus.current_level_m.toFixed(2)} m`
    : "-- m";
  const depthFt = waterStatus.current_level_m !== null && waterStatus.current_level_m !== undefined
    ? `${(waterStatus.current_level_m * 3.28084).toFixed(2)} ft`
    : "-- ft";
  const freshness = waterStatus.freshness_seconds !== null && waterStatus.freshness_seconds !== undefined
    ? `${Math.round(waterStatus.freshness_seconds)}s ago`
    : "No Telemetry";

  const elDepth = document.getElementById("modalWaterDepth");
  if (elDepth) elDepth.textContent = depthVal;

  const elDepthFt = document.getElementById("modalWaterDepthFt");
  if (elDepthFt) elDepthFt.textContent = depthFt;

  const elFreshness = document.getElementById("modalWaterFreshness");
  if (elFreshness) {
    elFreshness.textContent = freshness;
    elFreshness.style.color = waterStatus.is_stale ? "var(--color-warning)" : "var(--color-normal)";
  }

  const badgeStatus = document.getElementById("modalWaterStatusBadge");
  if (badgeStatus) {
    badgeStatus.textContent = waterStatus.status;
    badgeStatus.className = `badge-tag ${waterStatus.status}`;
  }

  // Targets
  const targetInput = document.getElementById("waterTargetInput");
  if (targetInput) targetInput.value = waterStatus.water_level_target_m || 1.22;
  const minInput = document.getElementById("waterMinInput");
  if (minInput) minInput.value = waterStatus.water_level_min_m || 0.95;
  const maxInput = document.getElementById("waterMaxInput");
  if (maxInput) maxInput.value = waterStatus.water_level_max_m || 1.40;

  // Normal outlet
  const normBadge = document.getElementById("normalOutletBadge");
  if (normBadge) {
    normBadge.textContent = waterStatus.normal_outlet_state;
    normBadge.className = `badge-tag ${waterStatus.normal_outlet_state === "OPEN" ? "WARNING" : "NORMAL"}`;
  }

  // Full drain outlet
  const drainBadge = document.getElementById("fullDrainBadge");
  if (drainBadge) {
    const isLocked = waterStatus.full_drain_locked !== false;
    drainBadge.textContent = isLocked ? "🔒 LOCKED" : (waterStatus.full_drain_outlet_state || "UNLOCKED");
    drainBadge.className = `badge-tag ${isLocked ? "NORMAL" : "CRITICAL"}`;
  }
  const drainReason = document.getElementById("fullDrainReasonText");
  if (drainReason) drainReason.textContent = waterStatus.drain_lock_reason || "Active batch containment";

  // Pre-fill initial level for exchange form
  const exInitInput = document.getElementById("exchangeInitialLevelInput");
  if (exInitInput && waterStatus.current_level_m !== null && waterStatus.current_level_m !== undefined) {
    exInitInput.value = waterStatus.current_level_m.toFixed(2);
  }

  // Render exchanges table
  renderWaterExchangesTable(waterExchanges);
}

function renderWaterExchangesTable(exchanges = []) {
  const table = document.getElementById("waterExchangesTableBody");
  if (!table) return;
  table.innerHTML = "";

  if (exchanges.length === 0) {
    table.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:1rem;">No water exchange records logged yet.</td></tr>`;
    return;
  }

  exchanges.forEach((ex) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${ex.started_at ? new Date(ex.started_at).toLocaleString() : "--"}</td>
      <td><span class="badge-tag NORMAL" style="font-size:0.65rem">${escapeHtml(ex.mode)}</span></td>
      <td>${ex.initial_level_m.toFixed(2)} m</td>
      <td>${ex.final_level_m !== null && ex.final_level_m !== undefined ? `${ex.final_level_m.toFixed(2)} m` : "--"}</td>
      <td>${ex.completed_at ? new Date(ex.completed_at).toLocaleTimeString() : "<span style='color:var(--color-warning)'>In Progress</span>"}</td>
      <td><code>${escapeHtml(ex.operator_id)}</code></td>
      <td>${escapeHtml(ex.notes || "-")}</td>
    `;
    table.appendChild(tr);
  });
}

async function handleSaveWaterTargets() {
  const pondId = state.activePondId;
  const target = parseFloat(document.getElementById("waterTargetInput").value);
  const min = parseFloat(document.getElementById("waterMinInput").value);
  const max = parseFloat(document.getElementById("waterMaxInput").value);
  const feedback = document.getElementById("waterTargetFeedback");

  if (isNaN(target) || isNaN(min) || isNaN(max)) {
    alert("Please enter valid numeric values for targets and boundaries.");
    return;
  }
  if (min >= max) {
    alert("Min safe level must be strictly less than Max freeboard limit.");
    return;
  }
  if (target < min || target > max) {
    alert("Target depth must be between Min safe level and Max freeboard limit.");
    return;
  }

  try {
    await api.updatePondWaterTargets(pondId, { target_m: target, min_m: min, max_m: max });
    if (feedback) {
      feedback.textContent = "✓ Boundaries saved";
      setTimeout(() => { feedback.textContent = ""; }, 3000);
    }
    const waterStatus = await api.getPondWaterStatus(pondId);
    const exchanges = await api.getWaterExchanges(pondId);
    populateWaterTab(pondId, waterStatus, exchanges);
    await loadOverview();
  } catch (err) {
    alert("Save boundaries failed: " + err.message);
  }
}

async function handleSetNormalOutlet(gateState) {
  const pondId = state.activePondId;
  try {
    await api.updatePondOutlets(pondId, { normal_outlet_state: gateState });
    const waterStatus = await api.getPondWaterStatus(pondId);
    const exchanges = await api.getWaterExchanges(pondId);
    populateWaterTab(pondId, waterStatus, exchanges);
    await loadOverview();
  } catch (err) {
    alert("Update normal outlet failed: " + err.message);
  }
}

async function handleToggleFullDrainLock() {
  const pondId = state.activePondId;
  try {
    const current = await api.getPondWaterStatus(pondId);
    const currentlyLocked = current.full_drain_locked !== false;

    if (currentlyLocked) {
      const reason = prompt(
        "EMERGENCY/OVERRIDE: You are unlocking the full-drain monk.\n" +
        "Enter explicit operational authorization reason:",
        "Authorized crop harvest drainage"
      );
      if (!reason || reason.trim().length === 0) {
        alert("Unlock cancelled. Operational reason is strictly required.");
        return;
      }
      await api.updatePondOutlets(pondId, {
        full_drain_locked: false,
        drain_lock_reason: reason.trim(),
      });
    } else {
      await api.updatePondOutlets(pondId, {
        full_drain_locked: true,
        full_drain_outlet_state: "CLOSED",
        drain_lock_reason: "Active batch biological containment",
      });
    }

    const waterStatus = await api.getPondWaterStatus(pondId);
    const exchanges = await api.getWaterExchanges(pondId);
    populateWaterTab(pondId, waterStatus, exchanges);
    await loadOverview();
  } catch (err) {
    alert("Toggle lock failed: " + err.message);
  }
}

async function handleLogWaterExchange() {
  const pondId = state.activePondId;
  const mode = document.getElementById("exchangeModeSelect").value;
  const initLevel = parseFloat(document.getElementById("exchangeInitialLevelInput").value);
  const finalLevel = parseFloat(document.getElementById("exchangeFinalLevelInput").value);
  const notes = document.getElementById("exchangeNotesInput").value;

  if (isNaN(initLevel) || initLevel < 0) {
    alert("Please enter a valid initial water depth.");
    return;
  }

  try {
    await api.logWaterExchange({
      pond_id: pondId,
      mode: mode,
      initial_level_m: initLevel,
      final_level_m: isNaN(finalLevel) ? null : finalLevel,
      notes: notes ? notes.trim() : null,
    });

    document.getElementById("exchangeNotesInput").value = "";
    const waterStatus = await api.getPondWaterStatus(pondId);
    const exchanges = await api.getWaterExchanges(pondId);
    populateWaterTab(pondId, waterStatus, exchanges);
    await loadOverview();
  } catch (err) {
    alert("Log water exchange failed: " + err.message);
  }
}

async function handleUpdatePumpFeeder() {
  const txId = document.getElementById("pumpTxSelect").value;
  try {
    await api.updatePumpConfig({ transformer_id: txId });
    await loadOverview();
    alert(`Pump feeder updated to ${txId.toUpperCase()}`);
  } catch (err) {
    alert("Update pump feeder failed: " + err.message);
  }
}

async function handleTogglePumpSim() {
  try {
    const pump = await api.getPumpStatus();
    const currentlyRunning = pump.physical_state === "RUNNING";
    const pumpKw = pump.rating_kw || 0.0;

    if (!currentlyRunning && pumpKw <= 0) {
      alert("Cannot simulate pump operation: Motor electrical rating is unconfigured. Enter verified nameplate kW first via pump config.");
      return;
    }

    const nextState = currentlyRunning ? "OFF" : "RUNNING";
    const nextKw = currentlyRunning ? 0.0 : pumpKw;
    const nextAmps = currentlyRunning ? 0.0 : Math.round((pumpKw * 1000) / (1.732 * 415 * 0.85) * 10) / 10;

    await api.updatePumpState({
      desired_state: nextState,
      physical_state: nextState,
      current_draw_amps: nextAmps,
      power_kw: nextKw,
    });
    await loadOverview();
  } catch (err) {
    alert("Toggle pump state failed: " + err.message);
  }
}

async function handleEvaluatePumpAdvisory() {
  const targetPond = document.getElementById("advisoryTargetPond").value.trim();
  try {
    const adv = await api.getPumpAdvisory("pump-river-intake-01", targetPond || null);
    const badge = document.getElementById("advisoryActionBadge");
    if (badge) {
      badge.textContent = adv.proposed_action;
      badge.className = `badge-tag ${adv.proposed_action === "START" ? "NORMAL" : "WARNING"}`;
    }
    const elHeadroom = document.getElementById("advisoryHeadroom");
    if (elHeadroom) elHeadroom.textContent = `${adv.transformer_headroom_kw.toFixed(1)} kW`;
    const elReason = document.getElementById("advisoryReason");
    if (elReason) elReason.textContent = adv.reason;
  } catch (err) {
    alert("Evaluate advisory failed: " + err.message);
  }
}

async function handleSetAeratorOverride(aeratorId, desiredState) {
  const pondId = state.activePondId;
  if (!pondId) return;
  try {
    await api.setAeratorOverride(pondId, aeratorId, desiredState);
    const detail = await api.getPondDetailFull(pondId);
    if (detail) populatePondDetailTabs(detail);
    await loadOverview();
  } catch (err) {
    alert("Set aerator override failed: " + err.message);
  }
}
window.handleSetAeratorOverride = handleSetAeratorOverride;




