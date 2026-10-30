/**
 * Aqua OS - API Client & Resilient Real-Time SSE Streamer
 * Handles JWT credentials in sessionStorage, REST requests, and reconnecting SSE streams.
 */

class AquaAPIClient {
  constructor(baseUrl = "") {
    this.baseUrl = baseUrl;
    this.token = sessionStorage.getItem("aqua_token") || null;
    this.currentUser = JSON.parse(sessionStorage.getItem("aqua_user") || "null");
    this.eventSource = null;
    this.reconnectAttempts = 0;
    this.maxReconnectDelay = 10000;
    this.reconnectTimer = null;
    this.isExplicitDisconnect = false;
  }

  setSession(token, user) {
    this.token = token;
    this.currentUser = user;
    if (token) {
      sessionStorage.setItem("aqua_token", token);
      sessionStorage.setItem("aqua_user", JSON.stringify(user));
    } else {
      sessionStorage.removeItem("aqua_token");
      sessionStorage.removeItem("aqua_user");
    }
  }

  isAuthenticated() {
    return Boolean(this.token);
  }

  getHeaders() {
    const headers = { "Content-Type": "application/json" };
    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }
    return headers;
  }

  async request(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    const opts = Object.assign(
      {
        headers: this.getHeaders(),
      },
      options
    );

    const res = await fetch(url, opts);
    if (res.status === 401) {
      this.setSession(null, null);
      throw new Error("UNAUTHORIZED");
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `Request failed with HTTP ${res.status}`);
    }
    return res.json();
  }

  async login(username, password) {
    const res = await this.request("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    this.setSession(res.access_token, res.user);
    return res;
  }

  logout() {
    this.isExplicitDisconnect = true;
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
    this.setSession(null, null);
  }

  async getDashboardOverview(farmId = "farm-alpha") {
    return this.request(`/api/v1/dashboard/overview?farm_id=${encodeURIComponent(farmId)}`);
  }

  async getFarmOperationsIntelligence(farmId = "farm-alpha") {
    return this.request(`/api/v1/dashboard/operations?farm_id=${encodeURIComponent(farmId)}`);
  }

  async getDailyOperationsPlanner(farmId = "farm-alpha", targetDate = null) {
    let url = `/api/v1/dashboard/planner?farm_id=${encodeURIComponent(farmId)}`;
    if (targetDate) url += `&target_date=${encodeURIComponent(targetDate)}`;
    return this.request(url);
  }

  async getFarmActions(farmId = "farm-alpha", pondId = null, category = null, severity = null) {
    let url = `/api/v1/dashboard/actions?farm_id=${encodeURIComponent(farmId)}`;
    if (pondId) url += `&pond_id=${encodeURIComponent(pondId)}`;
    if (category) url += `&category=${encodeURIComponent(category)}`;
    if (severity) url += `&severity=${encodeURIComponent(severity)}`;
    return this.request(url);
  }

  async getPondDetails(pondId, farmId = "farm-alpha") {
    return this.request(`/api/v1/ponds/${encodeURIComponent(pondId)}?farm_id=${encodeURIComponent(farmId)}`);
  }

  async getPondHistory(pondId, farmId = "farm-alpha", limit = 100) {
    return this.request(
      `/api/v1/telemetry/history/${encodeURIComponent(pondId)}?farm_id=${encodeURIComponent(farmId)}&limit=${limit}`
    );
  }

  async getSimulatorStatus() {
    return this.request("/api/v1/simulator/status");
  }

  async startSimulator(intervalSeconds = 3.0) {
    return this.request("/api/v1/simulator/start", {
      method: "POST",
      body: JSON.stringify({ interval_seconds: intervalSeconds }),
    });
  }

  async stopSimulator() {
    return this.request("/api/v1/simulator/stop", { method: "POST" });
  }

  async stepSimulator() {
    return this.request("/api/v1/simulator/step", { method: "POST" });
  }

  async injectScenario(pondId, scenarioType, durationHours = 6.0) {
    return this.request("/api/v1/simulator/scenario", {
      method: "POST",
      body: JSON.stringify({
        pond_id: pondId,
        scenario_type: scenarioType,
        duration_hours: durationHours,
      }),
    });
  }

  async applySimulationDataset(datasetId, payload) {
    return this.request(`/api/v1/simulator/datasets/${encodeURIComponent(datasetId)}/apply`, {
      method: "POST", body: JSON.stringify(payload),
    });
  }

  async queueEdgeDryRunCommand(payload) {
    return this.request("/api/v1/edge/commands", { method: "POST", body: JSON.stringify(payload) });
  }

  async simulateEdgeCommandResult(commandId, payload) {
    return this.request(`/api/v1/edge/commands/${encodeURIComponent(commandId)}/simulate-result`, {
      method: "POST", body: JSON.stringify(payload),
    });
  }

  async getFarmPower(farmId = "farm-alpha") {
    return this.request(`/api/v1/farm/power?farm_id=${encodeURIComponent(farmId)}`);
  }

  async getPondDetailFull(pondId, farmId = "farm-alpha") {
    return this.request(`/api/v1/ponds/${encodeURIComponent(pondId)}/detail?farm_id=${encodeURIComponent(farmId)}`);
  }

  async getPondSensors(pondId, farmId = "farm-alpha") {
    return this.request(`/api/v1/ponds/${encodeURIComponent(pondId)}/sensors?farm_id=${encodeURIComponent(farmId)}`);
  }

  async calibrateSensor(pondId, sensorId, offset, slope, farmId = "farm-alpha") {
    return this.request(`/api/v1/ponds/${encodeURIComponent(pondId)}/sensors/${encodeURIComponent(sensorId)}/calibration?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify({ offset: parseFloat(offset), slope: parseFloat(slope) }),
    });
  }

  async getPondAeration(pondId, farmId = "farm-alpha") {
    return this.request(`/api/v1/ponds/${encodeURIComponent(pondId)}/aeration?farm_id=${encodeURIComponent(farmId)}`);
  }

  async triggerAerationDryRun(pondId, farmId = "farm-alpha") {
    return this.request(`/api/v1/ponds/${encodeURIComponent(pondId)}/aeration/dry-run?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
    });
  }

  async setAeratorOverride(pondId, aeratorId, desiredState, farmId = "farm-alpha") {
    return this.request(`/api/v1/ponds/${encodeURIComponent(pondId)}/aeration/override?farm_id=${encodeURIComponent(farmId)}`, {
      method: "PUT",
      body: JSON.stringify({ aerator_id: aeratorId, desired_state: desiredState }),
    });
  }

  async getPondStocking(pondId, farmId = "farm-alpha") {
    return this.request(`/api/v1/ponds/${encodeURIComponent(pondId)}/stocking?farm_id=${encodeURIComponent(farmId)}`);
  }

  async updatePondStocking(pondId, data, farmId = "farm-alpha") {
    return this.request(`/api/v1/ponds/${encodeURIComponent(pondId)}/stocking?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async getPondFeeding(pondId, farmId = "farm-alpha", batchId = null, startDate = null, endDate = null, limit = 50) {
    let url = `/api/v1/ponds/${encodeURIComponent(pondId)}/feeding?farm_id=${encodeURIComponent(farmId)}&limit=${limit}`;
    if (batchId) url += `&batch_id=${encodeURIComponent(batchId)}`;
    if (startDate) url += `&start_date=${encodeURIComponent(startDate)}`;
    if (endDate) url += `&end_date=${encodeURIComponent(endDate)}`;
    return this.request(url);
  }

  async logPondFeeding(pondId, data, farmId = "farm-alpha") {
    return this.request(`/api/v1/ponds/${encodeURIComponent(pondId)}/feeding?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async getPondFeedingSummary(pondId, farmId = "farm-alpha", batchId = null, days = 14) {
    let url = `/api/v1/ponds/${encodeURIComponent(pondId)}/feeding/summary?farm_id=${encodeURIComponent(farmId)}&days=${days}`;
    if (batchId) url += `&batch_id=${encodeURIComponent(batchId)}`;
    return this.request(url);
  }

  async getPondFeedingAdvisories(pondId, farmId = "farm-alpha", batchId = null) {
    let url = `/api/v1/ponds/${encodeURIComponent(pondId)}/feeding/advisories?farm_id=${encodeURIComponent(farmId)}`;
    if (batchId) url += `&batch_id=${encodeURIComponent(batchId)}`;
    return this.request(url);
  }

  // Feed Inventory Management Endpoints
  async getFeedInventorySummary(farmId = "farm-alpha") {
    return this.request(`/api/v1/feed-inventory/summary?farm_id=${encodeURIComponent(farmId)}`);
  }

  async getFeedProducts(farmId = "farm-alpha", activeOnly = false) {
    return this.request(`/api/v1/feed-inventory/products?farm_id=${encodeURIComponent(farmId)}&active_only=${activeOnly}`);
  }

  async createFeedProduct(data, farmId = "farm-alpha") {
    return this.request(`/api/v1/feed-inventory/products?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async updateFeedProduct(productId, data, farmId = "farm-alpha") {
    return this.request(`/api/v1/feed-inventory/products/${encodeURIComponent(productId)}?farm_id=${encodeURIComponent(farmId)}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  async recordStockReceipt(data, farmId = "farm-alpha") {
    return this.request(`/api/v1/feed-inventory/receipts?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async recordStockAdjustment(data, farmId = "farm-alpha") {
    return this.request(`/api/v1/feed-inventory/adjustments?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async getFeedTransactions(farmId = "farm-alpha", productId = null, transactionType = null, pondId = null, startDate = null, endDate = null, limit = 50) {
    let url = `/api/v1/feed-inventory/transactions?farm_id=${encodeURIComponent(farmId)}&limit=${limit}`;
    if (productId) url += `&product_id=${encodeURIComponent(productId)}`;
    if (transactionType) url += `&transaction_type=${encodeURIComponent(transactionType)}`;
    if (pondId) url += `&pond_id=${encodeURIComponent(pondId)}`;
    if (startDate) url += `&start_date=${encodeURIComponent(startDate)}`;
    if (endDate) url += `&end_date=${encodeURIComponent(endDate)}`;
    return this.request(url);
  }

  // Feed Planning & Ration Intelligence Endpoints
  async getFeedPlanOverview(farmId = "farm-alpha", targetDate = null) {
    let url = `/api/v1/feed-plans/overview?farm_id=${encodeURIComponent(farmId)}`;
    if (targetDate) url += `&target_date=${encodeURIComponent(targetDate)}`;
    return this.request(url);
  }

  async getRationRecommendation(pondId, farmId = "farm-alpha", sessionsCount = 4) {
    return this.request(`/api/v1/feed-plans/recommendation/${encodeURIComponent(pondId)}?farm_id=${encodeURIComponent(farmId)}&sessions_count=${sessionsCount}`);
  }

  async listFeedPlans(farmId = "farm-alpha", pondId = null, batchId = null, status = null, dateFrom = null, dateTo = null, limit = 50) {
    let url = `/api/v1/feed-plans?farm_id=${encodeURIComponent(farmId)}&limit=${limit}`;
    if (pondId) url += `&pond_id=${encodeURIComponent(pondId)}`;
    if (batchId) url += `&batch_id=${encodeURIComponent(batchId)}`;
    if (status) url += `&status=${encodeURIComponent(status)}`;
    if (dateFrom) url += `&date_from=${encodeURIComponent(dateFrom)}`;
    if (dateTo) url += `&date_to=${encodeURIComponent(dateTo)}`;
    return this.request(url);
  }

  async getFeedPlan(planId, farmId = "farm-alpha") {
    return this.request(`/api/v1/feed-plans/${encodeURIComponent(planId)}?farm_id=${encodeURIComponent(farmId)}`);
  }

  async createFeedPlan(data, farmId = "farm-alpha") {
    return this.request(`/api/v1/feed-plans?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async updateFeedPlan(planId, data, farmId = "farm-alpha") {
    return this.request(`/api/v1/feed-plans/${encodeURIComponent(planId)}?farm_id=${encodeURIComponent(farmId)}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  async approveFeedPlan(planId, farmId = "farm-alpha") {
    return this.request(`/api/v1/feed-plans/${encodeURIComponent(planId)}/approve?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
    });
  }

  async cancelFeedPlan(planId, farmId = "farm-alpha") {
    return this.request(`/api/v1/feed-plans/${encodeURIComponent(planId)}/cancel?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
    });
  }


  async getAlerts(farmId = "farm-alpha", pondId = null, status = null) {
    let url = `/api/v1/alerts?farm_id=${encodeURIComponent(farmId)}`;
    if (pondId) url += `&pond_id=${encodeURIComponent(pondId)}`;
    if (status) url += `&status=${encodeURIComponent(status)}`;
    return this.request(url);
  }

  async acknowledgeAlert(alertId, notes = "") {
    return this.request(`/api/v1/alerts/${encodeURIComponent(alertId)}/acknowledge`, {
      method: "POST",
      body: JSON.stringify({ notes }),
    });
  }

  async resolveAlert(alertId, notes = "") {
    return this.request(`/api/v1/alerts/${encodeURIComponent(alertId)}/resolve`, {
      method: "POST",
      body: JSON.stringify({ notes }),
    });
  }

  async getFarmProductionSummary(farmId = "farm-alpha") {
    return this.request(`/api/v1/production/farm/summary?farm_id=${encodeURIComponent(farmId)}`);
  }

  async getPondProductionIntelligence(pondId, farmId = "farm-alpha") {
    return this.request(`/api/v1/production/ponds/${encodeURIComponent(pondId)}/intelligence?farm_id=${encodeURIComponent(farmId)}`);
  }

  async getPondBatches(pondId, farmId = "farm-alpha", status = null) {
    let url = `/api/v1/production/ponds/${encodeURIComponent(pondId)}/batches?farm_id=${encodeURIComponent(farmId)}`;
    if (status) url += `&status=${encodeURIComponent(status)}`;
    return this.request(url);
  }

  async createPondBatch(pondId, data, farmId = "farm-alpha") {
    return this.request(`/api/v1/production/ponds/${encodeURIComponent(pondId)}/batches?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async closeBatch(batchId, status = "HARVESTED", harvestedBiomassKg = null, harvestNotes = null) {
    return this.request(`/api/v1/production/batches/${encodeURIComponent(batchId)}/close`, {
      method: "POST",
      body: JSON.stringify({
        status,
        harvested_biomass_kg: harvestedBiomassKg !== null ? parseFloat(harvestedBiomassKg) : null,
        harvest_notes: harvestNotes,
      }),
    });
  }

  async updateHarvestPlan(batchId, targetAbw, targetHarvestDate = null, salePrice = 5.50) {
    return this.request(`/api/v1/production/batches/${encodeURIComponent(batchId)}/harvest-plan`, {
      method: "POST",
      body: JSON.stringify({
        target_abw_g: parseFloat(targetAbw),
        target_harvest_date: targetHarvestDate,
        projected_sale_price_per_kg: parseFloat(salePrice),
      }),
    });
  }

  async getPondGrowthSamples(pondId, batchId = null, farmId = "farm-alpha") {
    let url = `/api/v1/production/ponds/${encodeURIComponent(pondId)}/samples?farm_id=${encodeURIComponent(farmId)}`;
    if (batchId) url += `&batch_id=${encodeURIComponent(batchId)}`;
    return this.request(url);
  }

  async recordGrowthSample(pondId, data, batchId = null, farmId = "farm-alpha") {
    let url = `/api/v1/production/ponds/${encodeURIComponent(pondId)}/samples?farm_id=${encodeURIComponent(farmId)}`;
    if (batchId) url += `&batch_id=${encodeURIComponent(batchId)}`;
    return this.request(url, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async getPondBiomassEstimation(pondId, farmId = "farm-alpha") {
    return this.request(`/api/v1/production/ponds/${encodeURIComponent(pondId)}/biomass?farm_id=${encodeURIComponent(farmId)}`);
  }

  async getPondHarvestForecast(pondId, farmId = "farm-alpha") {
    return this.request(`/api/v1/production/ponds/${encodeURIComponent(pondId)}/harvest-forecast?farm_id=${encodeURIComponent(farmId)}`);
  }

  async recordHarvest(data, farmId = "farm-alpha") {
    return this.request(`/api/v1/production/harvests?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async listHarvests(farmId = "farm-alpha", pondId = null, batchId = null, limit = 50) {
    let url = `/api/v1/production/harvests?farm_id=${encodeURIComponent(farmId)}&limit=${limit}`;
    if (pondId) url += `&pond_id=${encodeURIComponent(pondId)}`;
    if (batchId) url += `&batch_id=${encodeURIComponent(batchId)}`;
    return this.request(url);
  }

  async getBatchLifecycle(batchId) {
    return this.request(`/api/v1/production/batches/${encodeURIComponent(batchId)}/lifecycle`);
  }

  async getBatchEconomics(batchId) {
    return this.request(`/api/v1/production/batches/${encodeURIComponent(batchId)}/economics`);
  }

  async getFarmEconomics(farmId = "farm-alpha", pondId = null) {
    let url = `/api/v1/production/farm/economics?farm_id=${encodeURIComponent(farmId)}`;
    if (pondId) url += `&pond_id=${encodeURIComponent(pondId)}`;
    return this.request(url);
  }

  async getBatchesReadiness(farmId = "farm-alpha", pondId = null, status = null) {
    let url = `/api/v1/production/batches/readiness?farm_id=${encodeURIComponent(farmId)}`;
    if (pondId) url += `&pond_id=${encodeURIComponent(pondId)}`;
    if (status) url += `&status=${encodeURIComponent(status)}`;
    return this.request(url);
  }

  // --- Farm Expense & Purchase Ledger ---
  async recordExpense(data, farmId = "farm-alpha") {
    return this.request(`/api/v1/expenses?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async listExpenses(farmId = "farm-alpha", params = {}) {
    let url = `/api/v1/expenses?farm_id=${encodeURIComponent(farmId)}`;
    if (params.pondId) url += `&pond_id=${encodeURIComponent(params.pondId)}`;
    if (params.batchId) url += `&batch_id=${encodeURIComponent(params.batchId)}`;
    if (params.category) url += `&category=${encodeURIComponent(params.category)}`;
    if (params.status) url += `&status=${encodeURIComponent(params.status)}`;
    if (params.limit) url += `&limit=${encodeURIComponent(params.limit)}`;
    if (params.offset) url += `&offset=${encodeURIComponent(params.offset)}`;
    return this.request(url);
  }

  async getExpenseSummary(farmId = "farm-alpha", pondId = null) {
    let url = `/api/v1/expenses/summary?farm_id=${encodeURIComponent(farmId)}`;
    if (pondId) url += `&pond_id=${encodeURIComponent(pondId)}`;
    return this.request(url);
  }

  async getExpense(expenseId, farmId = "farm-alpha") {
    return this.request(`/api/v1/expenses/${encodeURIComponent(expenseId)}?farm_id=${encodeURIComponent(farmId)}`);
  }

  async correctExpense(expenseId, data, farmId = "farm-alpha") {
    return this.request(`/api/v1/expenses/${encodeURIComponent(expenseId)}/correct?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async reverseExpense(expenseId, reason, farmId = "farm-alpha") {
    return this.request(`/api/v1/expenses/${encodeURIComponent(expenseId)}/reverse?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify({ reversal_reason: reason }),
    });
  }

  async getBatchAttributedExpenses(batchId, farmId = "farm-alpha") {
    return this.request(`/api/v1/expenses/batches/${encodeURIComponent(batchId)}?farm_id=${encodeURIComponent(farmId)}`);
  }

  // --- Farm Cash Flow, Working Capital & Crop Budgets ---
  async recordCashTransaction(data, farmId = "farm-alpha") {
    return this.request(`/api/v1/finance/cash-transactions?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async listCashTransactions(farmId = "farm-alpha", params = {}) {
    let url = `/api/v1/finance/cash-transactions?farm_id=${encodeURIComponent(farmId)}`;
    if (params.entryType) url += `&entry_type=${encodeURIComponent(params.entryType)}`;
    if (params.category) url += `&category=${encodeURIComponent(params.category)}`;
    if (params.status) url += `&status=${encodeURIComponent(params.status)}`;
    if (params.startDate) url += `&start_date=${encodeURIComponent(params.startDate)}`;
    if (params.endDate) url += `&end_date=${encodeURIComponent(params.endDate)}`;
    if (params.pondId) url += `&pond_id=${encodeURIComponent(params.pondId)}`;
    if (params.batchId) url += `&batch_id=${encodeURIComponent(params.batchId)}`;
    if (params.limit) url += `&limit=${encodeURIComponent(params.limit)}`;
    if (params.offset) url += `&offset=${encodeURIComponent(params.offset)}`;
    return this.request(url);
  }

  async voidCashTransaction(transactionId, reason, farmId = "farm-alpha") {
    return this.request(`/api/v1/finance/cash-transactions/${encodeURIComponent(transactionId)}/void?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify({ void_reason: reason }),
    });
  }

  async getOutstandingPayables(farmId = "farm-alpha", pondId = null) {
    let url = `/api/v1/finance/obligations/payables?farm_id=${encodeURIComponent(farmId)}`;
    if (pondId) url += `&pond_id=${encodeURIComponent(pondId)}`;
    return this.request(url);
  }

  async getOutstandingReceivables(farmId = "farm-alpha", pondId = null) {
    let url = `/api/v1/finance/obligations/receivables?farm_id=${encodeURIComponent(farmId)}`;
    if (pondId) url += `&pond_id=${encodeURIComponent(pondId)}`;
    return this.request(url);
  }

  async getWorkingCapitalSummary(farmId = "farm-alpha", params = {}) {
    let url = `/api/v1/finance/working-capital/summary?farm_id=${encodeURIComponent(farmId)}`;
    if (params.startDate) url += `&start_date=${encodeURIComponent(params.startDate)}`;
    if (params.endDate) url += `&end_date=${encodeURIComponent(params.endDate)}`;
    return this.request(url);
  }

  async recordCropBudget(data, farmId = "farm-alpha") {
    return this.request(`/api/v1/finance/budgets?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async listBudgetsVsActuals(farmId = "farm-alpha", params = {}) {
    let url = `/api/v1/finance/budgets?farm_id=${encodeURIComponent(farmId)}`;
    if (params.batchId) url += `&batch_id=${encodeURIComponent(params.batchId)}`;
    if (params.pondId) url += `&pond_id=${encodeURIComponent(params.pondId)}`;
    return this.request(url);
  }

  async recordCashBalanceSnapshot(data, farmId = "farm-alpha") {
    return this.request(`/api/v1/finance/cash-balance?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async getLatestCashBalanceSnapshot(farmId = "farm-alpha") {
    return this.request(`/api/v1/finance/cash-balance?farm_id=${encodeURIComponent(farmId)}`);
  }

  // --- Pond Health, Mortality & Treatments ---
  async getPondHealthSummary(pondId, farmId = "farm-alpha") {
    return this.request(`/api/v1/health/ponds/${encodeURIComponent(pondId)}/summary?farm_id=${encodeURIComponent(farmId)}`);
  }

  async recordMortality(pondId, data, farmId = "farm-alpha") {
    return this.request(`/api/v1/health/ponds/${encodeURIComponent(pondId)}/mortality?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async correctMortality(mortalityId, data, farmId = "farm-alpha") {
    return this.request(`/api/v1/health/mortality/${encodeURIComponent(mortalityId)}/correct?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async listMortalities(pondId, farmId = "farm-alpha", limit = 50) {
    return this.request(`/api/v1/health/ponds/${encodeURIComponent(pondId)}/mortality?farm_id=${encodeURIComponent(farmId)}&limit=${limit}`);
  }

  async recordHealthObservation(pondId, data, farmId = "farm-alpha") {
    return this.request(`/api/v1/health/ponds/${encodeURIComponent(pondId)}/observations?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async listHealthObservations(pondId, farmId = "farm-alpha", limit = 50) {
    return this.request(`/api/v1/health/ponds/${encodeURIComponent(pondId)}/observations?farm_id=${encodeURIComponent(farmId)}&limit=${limit}`);
  }

  async recordTreatment(pondId, data, farmId = "farm-alpha") {
    return this.request(`/api/v1/health/ponds/${encodeURIComponent(pondId)}/treatments?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async listTreatments(pondId, farmId = "farm-alpha", limit = 50) {
    return this.request(`/api/v1/health/ponds/${encodeURIComponent(pondId)}/treatments?farm_id=${encodeURIComponent(farmId)}&limit=${limit}`);
  }

  async resetScenarios() {
    return this.request("/api/v1/simulator/reset", { method: "POST" });
  }

  // --- Water Management Endpoints ---
  async getPondWaterStatus(pondId, farmId = "farm-alpha") {
    return this.request(`/api/v1/water/ponds/${encodeURIComponent(pondId)}?farm_id=${encodeURIComponent(farmId)}`);
  }

  async updatePondWaterTargets(pondId, targets, farmId = "farm-alpha") {
    return this.request(`/api/v1/water/ponds/${encodeURIComponent(pondId)}/targets?farm_id=${encodeURIComponent(farmId)}`, {
      method: "PUT",
      body: JSON.stringify(targets),
    });
  }

  async updatePondOutlets(pondId, outletState, farmId = "farm-alpha") {
    return this.request(`/api/v1/water/ponds/${encodeURIComponent(pondId)}/outlets?farm_id=${encodeURIComponent(farmId)}`, {
      method: "PUT",
      body: JSON.stringify(outletState),
    });
  }

  async getPumpStatus(pumpId = "pump-river-intake-01", farmId = "farm-alpha") {
    return this.request(`/api/v1/water/pump?pump_id=${encodeURIComponent(pumpId)}&farm_id=${encodeURIComponent(farmId)}`);
  }

  async updatePumpConfig(config, pumpId = "pump-river-intake-01", farmId = "farm-alpha") {
    return this.request(`/api/v1/water/pump/config?pump_id=${encodeURIComponent(pumpId)}&farm_id=${encodeURIComponent(farmId)}`, {
      method: "PUT",
      body: JSON.stringify(config),
    });
  }

  async updatePumpState(state, pumpId = "pump-river-intake-01", farmId = "farm-alpha") {
    return this.request(`/api/v1/water/pump/state?pump_id=${encodeURIComponent(pumpId)}&farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(state),
    });
  }

  async getPumpAdvisory(pumpId = "pump-river-intake-01", targetPondId = null, farmId = "farm-alpha") {
    let url = `/api/v1/water/pump/advisory?pump_id=${encodeURIComponent(pumpId)}&farm_id=${encodeURIComponent(farmId)}`;
    if (targetPondId) url += `&target_pond_id=${encodeURIComponent(targetPondId)}`;
    return this.request(url);
  }

  async getWaterExchanges(pondId = null, farmId = "farm-alpha", limit = 50) {
    let url = `/api/v1/water/exchanges?farm_id=${encodeURIComponent(farmId)}&limit=${limit}`;
    if (pondId) url += `&pond_id=${encodeURIComponent(pondId)}`;
    return this.request(url);
  }

  async logWaterExchange(data, farmId = "farm-alpha") {
    return this.request(`/api/v1/water/exchanges?farm_id=${encodeURIComponent(farmId)}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async completeWaterExchange(exchangeId, data, farmId = "farm-alpha") {
    return this.request(`/api/v1/water/exchanges/${encodeURIComponent(exchangeId)}/complete?farm_id=${encodeURIComponent(farmId)}`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  }

  /**
   * Connect to real-time Server-Sent Events stream with backoff recovery.
   */
  connectStream(callbacks = {}) {
    if (!this.token) {
      if (callbacks.onStateChange) callbacks.onStateChange("DISCONNECTED");
      return;
    }

    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }

    this.isExplicitDisconnect = false;
    const streamUrl = `${this.baseUrl}/api/v1/dashboard/stream?token=${encodeURIComponent(this.token)}`;

    if (callbacks.onStateChange) callbacks.onStateChange(this.reconnectAttempts > 0 ? "RECONNECTING" : "CONNECTING");

    try {
      this.eventSource = new EventSource(streamUrl);

      this.eventSource.addEventListener("connected", (e) => {
        this.reconnectAttempts = 0;
        if (callbacks.onStateChange) callbacks.onStateChange("CONNECTED");
        if (callbacks.onConnected) callbacks.onConnected(JSON.parse(e.data));
      });

      this.eventSource.addEventListener("pond_update", (e) => {
        if (callbacks.onPondUpdate) callbacks.onPondUpdate(JSON.parse(e.data));
      });

      this.eventSource.addEventListener("simulator_cycle", (e) => {
        if (callbacks.onSimulatorCycle) callbacks.onSimulatorCycle(JSON.parse(e.data));
      });

      this.eventSource.addEventListener("heartbeat", (e) => {
        if (callbacks.onHeartbeat) callbacks.onHeartbeat(JSON.parse(e.data));
      });

      this.eventSource.onerror = () => {
        if (this.isExplicitDisconnect) return;

        if (this.eventSource) {
          this.eventSource.close();
          this.eventSource = null;
        }

        if (callbacks.onStateChange) callbacks.onStateChange("RECONNECTING");

        // Exponential backoff reconnect
        this.reconnectAttempts++;
        const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), this.maxReconnectDelay);

        if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
        this.reconnectTimer = setTimeout(() => {
          this.connectStream(callbacks);
        }, delay);
      };
    } catch {
      if (callbacks.onStateChange) callbacks.onStateChange("DISCONNECTED");
    }
  }
}

const api = new AquaAPIClient();

