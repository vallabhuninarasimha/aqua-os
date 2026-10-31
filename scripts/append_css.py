role_styles = """

/* ==========================================================================
   MULTI-TENANT FACILITY SELECTOR & RBAC STYLING
   ========================================================================== */
.tenant-farm-selector-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(15, 23, 42, 0.75);
  border: 1px solid rgba(56, 189, 248, 0.25);
  border-radius: 8px;
  padding: 4px 10px;
  margin-right: 8px;
}

.tenant-select-label {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--teal-accent, #38bdf8);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  cursor: pointer;
}

.tenant-select-dropdown {
  background: rgba(8, 14, 26, 0.85);
  border: 1px solid rgba(148, 163, 184, 0.2);
  color: #ffffff;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 6px;
  outline: none;
  cursor: pointer;
}

.tenant-select-dropdown:focus {
  border-color: #38bdf8;
  box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2);
}

.tenant-badge {
  display: inline-block;
  font-size: 9px;
  font-weight: 800;
  color: #38bdf8;
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.3);
  padding: 3px 6px;
  border-radius: 4px;
  letter-spacing: 0.06em;
}

/* ==========================================================================
   LIVE FARM VIEW LAYOUT & VISUAL CONTAINER FIXES
   ========================================================================== */
.live-farm-page.active {
  display: flex !important;
  flex-direction: column;
  gap: 16px;
  min-height: calc(100vh - 80px);
}

.live-farm-stage {
  position: relative;
  min-height: 480px;
  height: 58vh;
  overflow: hidden;
  border: 1px solid rgba(56, 189, 248, 0.35);
  border-radius: 16px;
  background: radial-gradient(ellipse at 50% 30%, #0c2b3a 0%, #061722 55%, #030c14 100%);
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.35), inset 0 0 20px rgba(56, 189, 248, 0.05);
}

.live-farm-status.status-normal {
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.3);
  color: #34d399;
}

.live-farm-status.status-warning {
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.4);
  color: #fbbf24;
}

/* ==========================================================================
   ROLE-SPECIFIC ROOT CONTAINER STYLING
   ========================================================================== */
.role-experience-view {
  display: flex;
  flex-direction: column;
  gap: 20px;
  width: 100%;
}

.role-experience-view[hidden] {
  display: none !important;
}

.role-indicator-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.08em;
  padding: 4px 10px;
  border-radius: 999px;
  text-transform: uppercase;
}

.role-indicator-pill.manager {
  background: rgba(56, 189, 248, 0.15);
  border: 1px solid rgba(56, 189, 248, 0.35);
  color: #38bdf8;
}

.role-indicator-pill.farmer {
  background: rgba(16, 185, 129, 0.18);
  border: 1px solid rgba(16, 185, 129, 0.4);
  color: #34d399;
}

.role-indicator-pill.tech {
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.35);
  color: #fbbf24;
}

.crop-cycle-tag, .crop-status-pill, .protocol-tag {
  display: inline-block;
  font-size: 10px;
  font-weight: 600;
  color: var(--text-muted);
  background: rgba(255, 255, 255, 0.05);
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
}

/* ==========================================================================
   1. MANAGER EXPERIENCE STYLING
   ========================================================================== */
.manager-executive-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px;
  background: linear-gradient(135deg, rgba(13, 24, 41, 0.9) 0%, rgba(10, 18, 30, 0.85) 100%);
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 14px;
}

.executive-title-block .executive-badge {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.executive-heading {
  font-size: 20px;
  font-weight: 800;
  color: #ffffff;
  letter-spacing: -0.01em;
  margin: 0 0 4px;
}

.executive-subheading {
  font-size: 11px;
  color: var(--text-muted);
  margin: 0;
}

.executive-actions {
  display: flex;
  gap: 10px;
}

.executive-kpi-ribbon {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}

.executive-kpi-card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 12px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  transition: transform 0.15s ease, border-color 0.15s ease;
}

.executive-kpi-card:hover {
  transform: translateY(-2px);
  border-color: rgba(56, 189, 248, 0.35);
}

.kpi-eyebrow {
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.1em;
  color: var(--text-muted);
  text-transform: uppercase;
}

.kpi-value-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin: 6px 0 4px;
}

.kpi-number {
  font-size: 26px;
  font-weight: 800;
  color: #ffffff;
  font-variant-numeric: tabular-nums;
}

.kpi-unit {
  font-size: 12px;
  font-weight: 600;
  color: var(--teal-accent);
}

.kpi-trend {
  font-size: 11px;
  font-weight: 700;
}

.kpi-trend.positive {
  color: #34d399;
}

.kpi-caption {
  font-size: 9px;
  color: var(--text-muted);
  margin-top: 4px;
}

/* Manager 4-Tank Portfolio Section */
.manager-portfolio-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-title-bar {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.section-title-bar h2 {
  font-size: 15px;
  font-weight: 700;
  color: #ffffff;
  margin: 0;
}

.section-title-bar .subtext {
  font-size: 11px;
  color: var(--text-muted);
}

.portfolio-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}

.portfolio-card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 12px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.portfolio-card:hover {
  border-color: #38bdf8;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
}

.portfolio-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.portfolio-card-head h3 {
  font-size: 16px;
  font-weight: 700;
  color: #ffffff;
  margin: 0;
}

.portfolio-tag {
  font-size: 9px;
  font-weight: 800;
  padding: 3px 7px;
  border-radius: 999px;
}

.portfolio-tag.optimal {
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.35);
  color: #34d399;
}

.portfolio-tag.normal {
  background: rgba(56, 189, 248, 0.15);
  border: 1px solid rgba(56, 189, 248, 0.35);
  color: #38bdf8;
}

.portfolio-tag.attention {
  background: rgba(245, 158, 11, 0.18);
  border: 1px solid rgba(245, 158, 11, 0.4);
  color: #fbbf24;
}

.portfolio-metrics-table {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  font-size: 10px;
}

.portfolio-metric-box {
  background: rgba(14, 28, 44, 0.5);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 6px 8px;
}

.portfolio-metric-box span {
  display: block;
  color: var(--text-muted);
  font-size: 8px;
  text-transform: uppercase;
}

.portfolio-metric-box strong {
  display: block;
  font-size: 12px;
  color: #ffffff;
  margin-top: 2px;
}

/* Manager Decision Queue & OpEx Snapshot */
.manager-decisions-opex-row {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 16px;
}

.decision-queue-panel, .opex-snapshot-panel {
  padding: 16px;
}

.decision-items-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}

.decision-card-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  background: rgba(14, 28, 44, 0.6);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 10px 14px;
}

.decision-info-block {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.decision-title-text {
  font-size: 11px;
  font-weight: 700;
  color: #ffffff;
}

.decision-sub-text {
  font-size: 9px;
  color: var(--text-muted);
}

.decision-btn-group {
  display: flex;
  gap: 6px;
}

.btn-approve-sm {
  background: rgba(16, 185, 129, 0.2);
  border: 1px solid #10b981;
  color: #34d399;
  font-size: 9px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
}

.btn-approve-sm:hover {
  background: #10b981;
  color: #ffffff;
}

.btn-reject-sm {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.35);
  color: #f87171;
  font-size: 9px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
}

.opex-breakdown-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 12px;
}

.opex-item-header {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.opex-item-header strong {
  color: #ffffff;
}

.opex-progress-bar {
  height: 6px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 3px;
  overflow: hidden;
}

.opex-progress-bar .fill {
  height: 100%;
  background: linear-gradient(90deg, #0ea5e9, #38bdf8);
  border-radius: 3px;
}

/* ==========================================================================
   2. FARMER EXPERIENCE STYLING (రైతు మోడ్ - SUNLIGHT-READY BILINGUAL)
   ========================================================================== */
.farmer-field-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  background: linear-gradient(135deg, rgba(8, 28, 20, 0.95) 0%, rgba(6, 20, 15, 0.9) 100%);
  border: 1px solid rgba(16, 185, 129, 0.35);
  border-radius: 14px;
  padding: 18px 20px;
}

.farmer-title {
  font-size: 22px;
  font-weight: 800;
  color: #ffffff;
  margin: 0 0 4px;
}

.farmer-subtitle {
  font-size: 12px;
  color: #a7f3d0;
  margin: 0;
}

.farmer-header-weather {
  display: flex;
  gap: 8px;
}

.weather-pill {
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.25);
  color: #e6fffa;
  font-size: 11px;
  font-weight: 700;
  padding: 6px 12px;
  border-radius: 8px;
}

.weather-pill.appetite-good {
  background: rgba(56, 189, 248, 0.15);
  border-color: rgba(56, 189, 248, 0.35);
  color: #7dd3fc;
}

/* Farmer Emergency Alert Banner */
.farmer-emergency-banner {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  padding: 16px 20px;
  border-radius: 12px;
  background: rgba(245, 158, 11, 0.12);
  border: 2px solid #f59e0b;
  box-shadow: 0 8px 24px rgba(245, 158, 11, 0.15);
}

.farmer-emergency-banner.critical {
  background: rgba(239, 68, 68, 0.16);
  border-color: #ef4444;
  box-shadow: 0 8px 24px rgba(239, 68, 68, 0.2);
}

.farmer-alert-icon-pulse {
  font-size: 28px;
  animation: pulse-alert 1.5s infinite;
}

@keyframes pulse-alert {
  0% { transform: scale(1); }
  50% { transform: scale(1.15); }
  100% { transform: scale(1); }
}

.alert-headline-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 4px;
}

.alert-headline-row h3 {
  font-size: 16px;
  font-weight: 800;
  color: #ffffff;
  margin: 0;
}

.alert-tag-immediate {
  background: #ef4444;
  color: #ffffff;
  font-size: 9px;
  font-weight: 800;
  padding: 2px 8px;
  border-radius: 4px;
}

.farmer-quick-actions-bar {
  display: flex;
  gap: 10px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.farmer-touch-btn {
  font-size: 12px;
  font-weight: 800;
  padding: 10px 16px;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  transition: transform 0.1s ease, filter 0.15s ease;
}

.farmer-touch-btn:active {
  transform: scale(0.98);
}

.farmer-touch-btn.emergency {
  background: #0284c7;
  color: #ffffff;
  border: 1px solid #38bdf8;
}

.farmer-touch-btn.emergency:hover {
  filter: brightness(1.15);
}

.farmer-touch-btn.halt-feed {
  background: #dc2626;
  color: #ffffff;
  border: 1px solid #f87171;
}

.farmer-touch-btn.secondary {
  background: rgba(255, 255, 255, 0.08);
  color: #e2e8f0;
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.farmer-touch-btn.submit-btn {
  background: #059669;
  color: #ffffff;
  width: 100%;
  margin-top: 8px;
  font-size: 13px;
}

/* 4-Tank Large Touch Cards */
.farmer-tanks-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.farmer-section-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.farmer-section-title h2 {
  font-size: 16px;
  font-weight: 800;
  color: #ffffff;
  margin: 0;
}

.farmer-section-title span {
  font-size: 11px;
  color: var(--text-muted);
}

.farmer-tanks-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.farmer-tank-card {
  background: var(--bg-card);
  border: 2px solid rgba(16, 185, 129, 0.3);
  border-radius: 14px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
}

.farmer-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.farmer-card-head h3 {
  font-size: 20px;
  font-weight: 800;
  color: #ffffff;
  margin: 0;
}

.farmer-status-chip {
  font-size: 11px;
  font-weight: 800;
  padding: 4px 10px;
  border-radius: 999px;
}

.farmer-status-chip.good {
  background: rgba(16, 185, 129, 0.2);
  border: 1px solid #10b981;
  color: #34d399;
}

.farmer-status-chip.warn {
  background: rgba(245, 158, 11, 0.2);
  border: 1px solid #f59e0b;
  color: #fbbf24;
}

.farmer-vital-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}

.farmer-vital-tile {
  background: rgba(14, 28, 44, 0.7);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 10px 8px;
  text-align: center;
}

.farmer-vital-tile .telugu-lbl {
  display: block;
  font-size: 9px;
  font-weight: 700;
  color: var(--teal-accent);
}

.farmer-vital-tile .eng-lbl {
  display: block;
  font-size: 8px;
  color: var(--text-muted);
}

.farmer-vital-tile .vital-val {
  font-size: 19px;
  font-weight: 800;
  color: #ffffff;
  margin: 4px 0 2px;
}

.farmer-vital-tile .vital-val small {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-muted);
}

.farmer-vital-tile.warning-tile {
  border-color: #f59e0b;
  background: rgba(245, 158, 11, 0.1);
}

.farmer-card-actions {
  display: grid;
  grid-template-columns: 1.5fr 1fr 1fr;
  gap: 8px;
}

.farmer-action-btn-tile {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(56, 189, 248, 0.25);
  color: #e2e8f0;
  font-size: 10px;
  font-weight: 700;
  padding: 8px 6px;
  border-radius: 6px;
  cursor: pointer;
  text-align: center;
}

.farmer-action-btn-tile.primary {
  background: rgba(2, 132, 199, 0.2);
  border-color: #0284c7;
  color: #38bdf8;
}

.farmer-action-btn-tile:hover {
  background: rgba(56, 189, 248, 0.2);
  color: #ffffff;
}

/* Farmer Field Ops Row */
.farmer-field-ops-row {
  display: grid;
  grid-template-columns: 1.3fr 1fr;
  gap: 16px;
}

.farmer-checklist-panel, .farmer-quick-log-panel {
  padding: 16px;
}

.farmer-task-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}

.farmer-task-item {
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(14, 28, 44, 0.6);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 10px 14px;
}

.farmer-task-item.done {
  opacity: 0.75;
  border-color: rgba(16, 185, 129, 0.3);
}

.farmer-task-item .task-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
}

.farmer-task-item .task-title {
  font-size: 11px;
  font-weight: 700;
  color: #ffffff;
}

.farmer-task-item .task-info small {
  font-size: 9px;
  color: var(--text-muted);
}

.task-check-icon {
  color: #10b981;
  font-weight: 800;
  font-size: 14px;
}

.btn-sm-action {
  background: rgba(56, 189, 248, 0.15);
  border: 1px solid #38bdf8;
  color: #38bdf8;
  font-size: 9px;
  font-weight: 700;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
}

.farmer-quick-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}

.form-grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-row label {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
}

.form-select, .form-input {
  background: rgba(8, 14, 26, 0.85);
  border: 1px solid var(--border-card);
  color: #ffffff;
  font-size: 11px;
  padding: 6px 10px;
  border-radius: 6px;
  outline: none;
}

.form-select:focus, .form-input:focus {
  border-color: #10b981;
}

/* ==========================================================================
   3. TECHNICAL EXPERIENCE STYLING (HARDWARE, MODBUS, 3-PHASE, EDGE)
   ========================================================================== */
.tech-console-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  background: linear-gradient(135deg, rgba(28, 20, 10, 0.95) 0%, rgba(20, 14, 6, 0.9) 100%);
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: 14px;
  padding: 18px 20px;
}

.tech-heading {
  font-size: 20px;
  font-weight: 800;
  color: #ffffff;
  margin: 0 0 4px;
}

.tech-subheading {
  font-size: 11px;
  color: #fde68a;
  margin: 0;
}

.tech-actions {
  display: flex;
  gap: 8px;
}

.tech-hardware-deck {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}

.tech-stat-card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 12px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
}

.tech-stat-card .card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.deck-label {
  font-size: 9px;
  font-weight: 800;
  color: var(--text-muted);
  letter-spacing: 0.08em;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 9px;
  font-weight: 800;
  padding: 2px 7px;
  border-radius: 999px;
}

.status-chip.online {
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.35);
  color: #34d399;
}

.status-chip.stopped {
  background: rgba(148, 163, 184, 0.15);
  border: 1px solid rgba(148, 163, 184, 0.3);
  color: #94a3b8;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.deck-value {
  font-size: 18px;
  font-weight: 800;
  color: #ffffff;
  margin: 8px 0 4px;
}

.deck-meta {
  font-size: 10px;
  color: #e2e8f0;
}

.deck-sub {
  font-size: 9px;
  color: var(--text-muted);
  margin-top: 4px;
}

.tech-sensor-table-panel {
  padding: 16px;
}

.table-scroll-wrapper {
  overflow-x: auto;
  margin-top: 12px;
}

.table-search-input {
  background: rgba(8, 14, 26, 0.8);
  border: 1px solid var(--border-card);
  color: #ffffff;
  font-size: 10px;
  padding: 4px 8px;
  border-radius: 6px;
  outline: none;
}

.tech-power-contactor-row {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 16px;
}

.tech-power-panel, .tech-contactor-panel {
  padding: 16px;
}

.power-phases-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin: 14px 0;
}

.phase-card {
  background: rgba(14, 28, 44, 0.6);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.phase-tag {
  font-size: 8px;
  font-weight: 800;
  color: var(--teal-accent);
}

.phase-volts {
  font-size: 20px;
  font-weight: 800;
  color: #ffffff;
}

.phase-current {
  font-size: 10px;
  color: var(--text-muted);
}

.phase-bar {
  height: 4px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 2px;
  overflow: hidden;
  margin-top: 4px;
}

.phase-bar .fill {
  height: 100%;
  background: #38bdf8;
}

.power-summary-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  font-size: 10px;
  color: var(--text-muted);
  border-top: 1px solid var(--border-subtle);
  padding-top: 12px;
}

.power-summary-stats strong {
  color: #ffffff;
}

.contactor-items-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 12px 0;
}

.contactor-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  background: rgba(14, 28, 44, 0.6);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 8px 12px;
}

.contactor-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.contactor-info strong {
  font-size: 11px;
  color: #ffffff;
}

.contactor-info small {
  font-size: 9px;
  color: var(--text-muted);
}

.mode-tag {
  font-size: 8px;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

.safety-advisory-box {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: 6px;
  padding: 8px 10px;
  color: #fbbf24;
  font-size: 9px;
  line-height: 1.4;
}

.tech-log-terminal-panel {
  padding: 16px;
}

.tech-log-terminal {
  background: #050b14;
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 8px;
  padding: 12px 14px;
  font-family: 'SF Mono', Consolas, Monaco, monospace;
  font-size: 10px;
  color: #94a3b8;
  height: 180px;
  overflow-y: auto;
  line-height: 1.6;
  white-space: pre-wrap;
  margin-top: 10px;
}

@media (max-width: 1200px) {
  .executive-kpi-ribbon, .portfolio-grid, .tech-hardware-deck {
    grid-template-columns: repeat(2, 1fr);
  }
  .farmer-tanks-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .manager-decisions-opex-row, .farmer-field-ops-row, .tech-power-contactor-row {
    grid-template-columns: 1fr;
  }
}
"""

with open('apps/dashboard/css/dashboard.css', 'a', encoding='utf-8') as f:
    f.write(role_styles)

print("dashboard.css updated with full role and multi-tenant styles!")

