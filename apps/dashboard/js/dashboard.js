(() => {
  'use strict';

  const FARM_ID = () => api.currentUser?.farm_id || 'farm-alpha';
  const $ = (selector, root = document) => root.querySelector(selector);
  const state = { overview: null, selectedPondId: null, refreshTimer: null, streamState: 'DISCONNECTED' };

  function setText(selector, value) {
    const node = $(selector);
    if (node) node.textContent = value == null || value === '' ? '—' : String(value);
  }

  function metric(pond, key) {
    const item = pond?.metrics?.[key];
    return item && Number.isFinite(Number(item.value))
      ? { value: Number(item.value), unit: item.unit || '', quality: item.quality || 'UNKNOWN' }
      : null;
  }

  function formatMetric(pond, key, digits = 1) {
    const item = metric(pond, key);
    return item ? `${item.value.toFixed(digits)} ${item.unit}`.trim() : 'No reading';
  }

  function statusClass(status) {
    const value = String(status || 'UNKNOWN').toUpperCase();
    if (value === 'CRITICAL' || value === 'EMERGENCY') return 'critical';
    if (value === 'WARNING') return 'watch';
    if (value === 'NORMAL') return 'normal';
    return 'degraded';
  }

  function showNotice(message, kind = 'info') {
    let notice = $('#apiNotice');
    if (!notice) {
      notice = document.createElement('div');
      notice.id = 'apiNotice';
      notice.setAttribute('role', 'status');
      notice.style.cssText = 'margin:12px 0;padding:12px 16px;border:1px solid #38536a;border-radius:10px;background:#102536;color:#e8f2fb';
      $('.app-shell')?.insertBefore(notice, $('main'));
    }
    notice.dataset.kind = kind;
    notice.textContent = message;
  }

  function clearNotice() {
    $('#apiNotice')?.remove();
  }

  function showLogin(error = '') {
    let panel = $('#aquaLogin');
    if (!panel) {
      panel = document.createElement('section');
      panel.id = 'aquaLogin';
      panel.style.cssText = 'position:fixed;inset:0;z-index:9999;background:#071421ee;display:grid;place-items:center;padding:20px';
      panel.innerHTML = `
        <form id="aquaLoginForm" style="width:min(420px,100%);padding:28px;background:#0c1d2c;border:1px solid #29465d;border-radius:16px;color:#e8f2fb">
          <div style="font-size:12px;letter-spacing:2px;color:#22e5c2">AQUA OS · SECURE ACCESS</div>
          <h2 style="margin:10px 0 6px">Farm sign in</h2>
          <p style="color:#8ea6b9;margin:0 0 20px">Sign in to load your farm's persisted operational data.</p>
          <label style="display:block;margin:12px 0 6px">Username</label>
          <input name="username" autocomplete="username" required style="width:100%;padding:12px;border-radius:8px;border:1px solid #38536a;background:#071421;color:#fff">
          <label style="display:block;margin:12px 0 6px">Password</label>
          <input name="password" type="password" autocomplete="current-password" required style="width:100%;padding:12px;border-radius:8px;border:1px solid #38536a;background:#071421;color:#fff">
          <p id="aquaLoginError" role="alert" style="color:#ff8794;min-height:20px"></p>
          <button type="submit" style="width:100%;padding:12px;border:0;border-radius:8px;background:#22e5c2;color:#062019;font-weight:700;cursor:pointer">Sign in</button>
        </form>`;
      document.body.appendChild(panel);
      $('#aquaLoginForm').addEventListener('submit', async (event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const button = $('button[type="submit"]', event.currentTarget);
        button.disabled = true;
        button.textContent = 'Signing in…';
        $('#aquaLoginError').textContent = '';
        try {
          await api.login(String(form.get('username')).trim(), String(form.get('password')));
          panel.remove();
          await loadOverview();
          connectLiveUpdates();
        } catch (err) {
          $('#aquaLoginError').textContent = err.message === 'UNAUTHORIZED' ? 'Invalid username or password.' : err.message;
        } finally {
          button.disabled = false;
          button.textContent = 'Sign in';
        }
      });
    }
    if (error) $('#aquaLoginError').textContent = error;
  }

  function renderPonds(ponds) {
    const grid = $('#pondGrid');
    if (!grid) return;
    grid.replaceChildren();
    if (!ponds.length) {
      grid.textContent = 'No ponds are configured for this farm.';
      return;
    }
    ponds.forEach((pond) => {
      const card = document.createElement('button');
      card.className = `pond-card ${statusClass(pond.status)}`;
      card.type = 'button';
      card.dataset.pondId = pond.pond_id;
      const name = document.createElement('span');
      name.className = 'pond-name';
      name.textContent = pond.name || pond.pond_id;
      const readings = document.createElement('div');
      readings.className = 'pond-reading';
      readings.textContent = `DO ${formatMetric(pond, 'dissolved_oxygen')} · Temp ${formatMetric(pond, 'temperature')} · pH ${formatMetric(pond, 'ph')}`;
      const status = document.createElement('span');
      status.className = 'pond-status';
      const freshness = pond.freshness_seconds == null ? 'No telemetry' : pond.is_stale ? `Stale · ${Math.round(pond.freshness_seconds)}s` : `Updated ${Math.round(pond.freshness_seconds)}s ago`;
      status.textContent = `${pond.status} · ${pond.is_simulated ? 'SIMULATED SOURCE' : 'MEASURED SOURCE'} · ${freshness}`;
      card.append(name, readings, status);
      card.addEventListener('click', () => selectPond(pond.pond_id));
      grid.appendChild(card);
    });
  }

  function renderOverview(data) {
    state.overview = data;
    const ponds = data.ponds || [];
    const summary = data.summary || {};
    const measured = ponds.filter(p => !p.is_simulated && !p.is_stale);
    const readings = key => measured.map(p => metric(p, key)).filter(Boolean).map(m => m.value);
    const average = values => values.length ? (values.reduce((a, b) => a + b, 0) / values.length).toFixed(1) : '—';

    const kpis = $$('.kpi-row .metric strong');
    if (kpis.length >= 4) {
      kpis[0].textContent = average(readings('dissolved_oxygen'));
      kpis[1].textContent = average(readings('temperature'));
      kpis[2].textContent = average(readings('ph'));
      kpis[3].textContent = average(readings('salinity'));
    }
    setText('.pond-count b', summary.total_ponds ?? ponds.length);
    const heading = $('.farm-panel h2');
    if (heading) heading.textContent = `Farm Overview · ${summary.total_ponds ?? ponds.length} ponds`;
    const foot = $('.farm-foot span:last-child');
    if (foot) foot.textContent = `${summary.normal_ponds || 0} Normal · ${summary.warning_ponds || 0} Warning · ${summary.critical_ponds || 0} Critical · ${summary.degraded_ponds || 0} Degraded · ${summary.unknown_ponds || 0} Unknown`;
    const critical = $('.critical b');
    if (critical) critical.textContent = `${summary.critical_ponds || 0} Critical`;
    renderPonds(ponds);
    const updated = new Date(data.evaluated_at);
    setText('.farm-foot span:first-child', `Evaluated: ${Number.isNaN(updated.getTime()) ? 'unknown' : updated.toLocaleString()}`);
    const edge = data.edge_status || {};
    const status = edge.is_connected ? 'EDGE CONNECTED' : edge.sovereign_mode_active ? 'OFFLINE EDGE MODE' : 'EDGE NOT CONNECTED';
    const automation = $('.auto-pill');
    if (automation) automation.textContent = status;
    const sourceNote = ponds.every(p => p.is_simulated) ? 'All current telemetry records are marked simulated; do not treat them as physical measurements.' :
      measured.length ? `${measured.length} ponds have fresh measured telemetry. Simulated and stale records are excluded from measured averages.` :
      'No fresh measured telemetry is available. Metrics are intentionally not estimated.';
    showNotice(sourceNote, measured.length ? 'success' : 'warning');
    if (state.selectedPondId && ponds.some(p => p.pond_id === state.selectedPondId)) selectPond(state.selectedPondId);
    else if (ponds.length) selectPond(ponds[0].pond_id);
  }

  function selectPond(pondId) {
    state.selectedPondId = pondId;
    const pond = state.overview?.ponds?.find(p => p.pond_id === pondId);
    if (!pond) return;
    const title = $('#pondTitle');
    if (title) title.textContent = `${pond.name} · Live Detail`;
    setText('#pondHeroTitle', pond.name);
    const values = {
      '#pondDO': formatMetric(pond, 'dissolved_oxygen'),
      '#pondTemp': formatMetric(pond, 'temperature'),
      '#pondph': formatMetric(pond, 'ph'),
      '#pondSalinity': formatMetric(pond, 'salinity'),
    };
    Object.entries(values).forEach(([selector, value]) => setText(selector, value));
    const badge = $('#pondCritical');
    if (badge) {
      badge.className = `status-chip ${statusClass(pond.status)}-chip`;
      badge.textContent = pond.is_safe ? 'Safety evaluation: safe' : `Attention required: ${pond.status}`;
    }
    const health = $('#sensorHealthPanel');
    if (health) health.textContent = `Data source: ${pond.is_simulated ? 'SIMULATED' : 'MEASURED'} · Freshness: ${pond.freshness_seconds == null ? 'No data' : Math.round(pond.freshness_seconds) + ' seconds'} · Aerator feedback: ${pond.aerator_status || 'UNKNOWN'} · ${(pond.active_alerts || []).join(' | ')}`;
  }

  async function loadOverview() {
    if (!api.isAuthenticated()) return showLogin();
    try {
      const data = await api.getDashboardOverview(FARM_ID());
      clearNotice();
      renderOverview(data);
    } catch (error) {
      if (error.message === 'UNAUTHORIZED') return showLogin('Your session expired. Please sign in again.');
      showNotice(`Unable to load farm data: ${error.message}. Displaying no cached or fabricated readings.`, 'error');
      const grid = $('#pondGrid');
      if (grid) grid.textContent = 'Farm data unavailable. Check API connectivity and permissions.';
    }
  }

  function connectLiveUpdates() {
    if (!api.isAuthenticated()) return;
    api.connectStream({
      onStateChange: (value) => {
        state.streamState = value;
        const node = $('.clock');
        if (node) node.title = `Live telemetry stream: ${value}`;
      },
      onPondUpdate: () => loadOverview(),
    });
  }

  function renderEmptyTrendCharts() {
    ['trendChart', 'pondChart'].forEach(id => {
      const canvas = document.getElementById(id);
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const parent = canvas.parentElement;
      if (parent && !parent.querySelector('.no-telemetry-state')) {
        const note = document.createElement('p');
        note.className = 'no-telemetry-state';
        note.textContent = 'Historical trend will appear when persisted telemetry is available.';
        note.style.color = '#8ea6b9';
        parent.appendChild(note);
      }
    });
  }

  document.addEventListener('click', event => {
    const view = event.target.closest('[data-view]');
    if (view) {
      $$('.view').forEach(section => section.classList.toggle('active', section.id === view.dataset.view));
      $$('.view-tab').forEach(tab => tab.classList.toggle('active', tab === view));
      if (view.dataset.view === 'pond' && state.selectedPondId) selectPond(state.selectedPondId);
    }
    const action = event.target.closest('[data-action]');
    if (action && action.dataset.action === 'logout') {
      api.logout();
      showLogin();
    }
  });

  const updateClock = () => {
    const node = $('#clock');
    if (node) node.textContent = new Date().toLocaleString('en-IN');
  };

  updateClock();
  setInterval(updateClock, 30000);
  renderEmptyTrendCharts();
  loadOverview().then(connectLiveUpdates);
  state.refreshTimer = setInterval(loadOverview, 15000);
})();