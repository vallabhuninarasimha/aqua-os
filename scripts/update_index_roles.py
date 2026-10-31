# Script to update apps/dashboard/index.html with the 3 distinct role experiences
with open('apps/dashboard/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Locate <main id="dashboard" class="dashboard-page section-page active">
main_start_tag = '<main id="dashboard" class="dashboard-page section-page active">'
if main_start_tag not in content:
    raise ValueError("Could not find main dashboard tag")

parts = content.split(main_start_tag, 1)
before_main = parts[0] + main_start_tag
after_main = parts[1]

# 2. In after_main, find the end of </main>
main_end_tag = '</main>'
if main_end_tag not in after_main:
    raise ValueError("Could not find </main>")

main_body, after_end = after_main.split(main_end_tag, 1)

# Remove the old farmerModeContainer from main_body if present
if '<div id="farmerModeContainer"' in main_body:
    # Find up to </section> of zone 1 or similar
    fm_start = main_body.find('<div id="farmerModeContainer"')
    fm_end = main_body.find('<!-- ZONE 1:', fm_start)
    if fm_end != -1:
        main_body_core = main_body[fm_end:]
    else:
        main_body_core = main_body
else:
    main_body_core = main_body

manager_experience_html = """
        <!-- =================================================================== -->
        <!-- ROLE 1: MANAGER EXPERIENCE (Executive Crop Economics & Ops) -->
        <!-- =================================================================== -->
        <div id="roleViewManager" class="role-experience-view active">
          <!-- Executive Header & Crop Performance Ribbon -->
          <div class="manager-executive-header">
            <div class="executive-title-block">
              <div class="executive-badge">
                <span class="role-indicator-pill manager">📊 FARM MANAGER CONSOLE</span>
                <span class="crop-cycle-tag">Crop Cycle 2026-B &bull; Litopenaeus vannamei</span>
              </div>
              <h1 class="executive-heading" id="managerFacilityTitle">Alpha Coastal Shrimp Facility &mdash; Executive Oversight</h1>
              <p class="executive-subheading">Crop economics, biological survival velocity, high-impact decision sign-offs, and multi-tank operations.</p>
            </div>
            <div class="executive-actions">
              <button type="button" class="btn-outline-dark" id="btnExportShiftReport" title="Export Daily Operational Shift Report">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
                <span>Shift Report</span>
              </button>
              <button type="button" class="btn-primary-blue" id="btnScheduleHarvest" data-section="analytics">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                <span>Harvest Planner</span>
              </button>
            </div>
          </div>

          <!-- Executive KPI Ribbon -->
          <div class="executive-kpi-ribbon">
            <div class="executive-kpi-card">
              <span class="kpi-eyebrow">TOTAL ESTIMATED BIOMASS</span>
              <div class="kpi-value-row">
                <strong class="kpi-number" id="mgrBiomassVal">18,420</strong>
                <span class="kpi-unit">kg</span>
              </div>
              <div class="kpi-trend positive">&uarr; +420 kg (past 7 days)</div>
              <small class="kpi-caption">Target: 22,000 kg by Day 70</small>
            </div>

            <div class="executive-kpi-card">
              <span class="kpi-eyebrow">FARM SURVIVAL RATE</span>
              <div class="kpi-value-row">
                <strong class="kpi-number" id="mgrSurvivalVal">88.5%</strong>
              </div>
              <div class="kpi-trend positive">&uarr; +1.2% vs Baseline</div>
              <small class="kpi-caption">~354,000 live post-larvae</small>
            </div>

            <div class="executive-kpi-card">
              <span class="kpi-eyebrow">FEED CONVERSION RATIO (FCR)</span>
              <div class="kpi-value-row">
                <strong class="kpi-number" id="mgrFcrVal">1.28</strong>
              </div>
              <div class="kpi-trend positive">Optimal (Target &lt; 1.35)</div>
              <small class="kpi-caption">Feed Burn: 840 kg/day</small>
            </div>

            <div class="executive-kpi-card">
              <span class="kpi-eyebrow">PROJECTED NET CROP VALUE</span>
              <div class="kpi-value-row">
                <strong class="kpi-number" id="mgrCropVal">&#8377;73.68</strong>
                <span class="kpi-unit">Lakh</span>
              </div>
              <div class="kpi-trend positive">Est. Margin: +44.2%</div>
              <small class="kpi-caption">OpEx to Date: &#8377;14.85 Lakh</small>
            </div>
          </div>

          <!-- Production Tank Portfolio Grid (Tanks 01 to 04) -->
          <div class="manager-portfolio-section">
            <div class="section-title-bar">
              <h2>Production Tanks &mdash; Biometric &amp; Health Matrix</h2>
              <span class="subtext">Primary 4-Tank Cluster &amp; Expansion Units</span>
            </div>
            <div class="portfolio-grid" id="managerPortfolioGrid">
              <!-- Dynamically populated 4 core tanks -->
            </div>
          </div>

          <!-- Manager Decision Approvals Queue & Financial OpEx Row -->
          <div class="manager-decisions-opex-row">
            <!-- Left: AI Operational Decision Approvals Queue -->
            <div class="panel decision-queue-panel">
              <div class="panel-header">
                <div>
                  <h2 class="panel-title-text">AI Operational Decisions &mdash; Manager Sign-Off Required</h2>
                  <p class="panel-subtitle-text">Autonomous AI recommendations pending supervisor validation</p>
                </div>
                <span class="queue-count-badge" id="mgrPendingCount">3 PENDING</span>
              </div>
              <div class="decision-items-list" id="managerDecisionList">
                <!-- Dynamically loaded decision cards with Approve / Reject -->
              </div>
            </div>

            <!-- Right: Operational Expenditure Snapshot -->
            <div class="panel opex-snapshot-panel">
              <div class="panel-header">
                <div>
                  <h2 class="panel-title-text">Crop Cycle Expenditure</h2>
                  <p class="panel-subtitle-text">Cumulative OpEx breakdown vs budget</p>
                </div>
                <a href="#finance" class="panel-link-action" data-section="finance">Full Financials &rarr;</a>
              </div>
              <div class="opex-breakdown-list">
                <div class="opex-item">
                  <div class="opex-item-header">
                    <span>Power &amp; Grid Electricity (12,400 kWh)</span>
                    <strong>&#8377;48,200</strong>
                  </div>
                  <div class="opex-progress-bar"><div class="fill" style="width: 28%;"></div></div>
                </div>
                <div class="opex-item">
                  <div class="opex-item-header">
                    <span>Pellet Feed Consumption (3,800 kg)</span>
                    <strong>&#8377;1,42,800</strong>
                  </div>
                  <div class="opex-progress-bar"><div class="fill" style="width: 62%;"></div></div>
                </div>
                <div class="opex-item">
                  <div class="opex-item-header">
                    <span>Probiotics &amp; Mineral Supplements</span>
                    <strong>&#8377;28,500</strong>
                  </div>
                  <div class="opex-progress-bar"><div class="fill" style="width: 18%;"></div></div>
                </div>
                <div class="opex-item">
                  <div class="opex-item-header">
                    <span>Labor, Biosecurity &amp; Testing</span>
                    <strong>&#8377;45,000</strong>
                  </div>
                  <div class="opex-progress-bar"><div class="fill" style="width: 32%;"></div></div>
                </div>
              </div>
            </div>
          </div>
"""

farmer_experience_html = """
        <!-- =================================================================== -->
        <!-- ROLE 2: FARMER EXPERIENCE (రైతు మోడ్ - Touch-Friendly Bilingual Field Console) -->
        <!-- =================================================================== -->
        <div id="roleViewFarmer" class="role-experience-view" hidden>
          <!-- Top Bilingual Header -->
          <div class="farmer-field-header">
            <div class="farmer-title-box">
              <div class="farmer-role-badge">
                <span class="role-indicator-pill farmer">🌾 రైతు మోడ్ (FARMER CONSOLE)</span>
                <span class="crop-status-pill">సజీవ రొయ్యల క్షేత్రం &bull; Active Field</span>
              </div>
              <h1 class="farmer-title">రైతు ప్రత్యక్ష పర్యవేక్షణ &bull; Farmer Field Action Deck</h1>
              <p class="farmer-subtitle">చెరువుల వద్ద సులభమైన తెలుగు మరియు ఇంగ్లీష్ ఆపరేషన్లు &bull; Touch-friendly bilingual pondside controls</p>
            </div>
            <div class="farmer-header-weather">
              <span class="weather-pill">&#9728;&#65039; 28.5&deg;C ఎండ</span>
              <span class="weather-pill">&#128168; గాలి 12 km/h</span>
              <span class="weather-pill appetite-good">&#129424; దాణా ఆకలి: చురుకుగా ఉంది</span>
            </div>
          </div>

          <!-- Emergency Alert Banner (High Contrast Audio/Visual styling) -->
          <div id="farmerAlertBanner" class="farmer-emergency-banner warning">
            <div class="farmer-alert-icon-pulse">&#9888;&#65039;</div>
            <div class="farmer-alert-body">
              <div class="alert-headline-row">
                <h3 id="farmerAlertTitle">చెరువు 4 లో ఆక్సిజన్ తక్కువగా ఉంది &bull; Low Oxygen Warning in Tank 04</h3>
                <span class="alert-tag-immediate">తక్షణ చర్య &bull; Immediate Action</span>
              </div>
              <p id="farmerAlertDesc">ప్రస్తుత ఆక్సిజన్ రీడింగ్: <strong>2.8 mg/L</strong> (కనీసం 4.5 mg/L ఉండాలి). రొయ్యలు ఊపిరాడక చనిపోయే ప్రమాదం ఉంది.</p>
              <div class="farmer-quick-actions-bar">
                <button type="button" class="farmer-touch-btn emergency" id="farmerBtnAerator">
                  &#9654; అత్యవసర ఏరియేషన్ ప్రారంభించు (Safe Aeration DRY_RUN)
                </button>
                <button type="button" class="farmer-touch-btn halt-feed" id="farmerBtnStopFeed">
                  &#128721; దాణా ఆపండి (Halt Feeding)
                </button>
                <button type="button" class="farmer-touch-btn secondary" id="farmerBtnNotifyMgr">
                  &#128222; మేనేజర్‌కు సమాచారం ఇవ్వండి (Notify Manager)
                </button>
              </div>
            </div>
          </div>

          <!-- 4-Tank Large Touch Cards Grid -->
          <div class="farmer-tanks-section">
            <div class="farmer-section-title">
              <h2>నాలుగు చెరువుల ప్రత్యక్ష స్థితి &bull; Live Status of 4 Active Tanks</h2>
              <span>పెద్ద అక్షరాలు, తక్షణ బటన్లు &bull; Large high-visibility field indicators</span>
            </div>
            <div class="farmer-tanks-grid" id="farmerTanksGrid">
              <!-- Dynamically populated 4 large touch cards for Tank 01 to 04 -->
            </div>
          </div>

          <!-- Farmer Routine Checklist & Water Sample Logger -->
          <div class="farmer-field-ops-row">
            <!-- Routine Checklist -->
            <div class="panel farmer-checklist-panel">
              <div class="panel-header">
                <div>
                  <h2 class="panel-title-text">రైతు దినచర్య పనులు &bull; Daily Farmhand Task Checklist</h2>
                  <p class="panel-subtitle-text">ప్రతి పనిని పూర్తి చేసి టిక్ చేయండి &bull; Tap to complete routine chores</p>
                </div>
                <span class="queue-count-badge" id="farmerTaskCount">2/4 పూర్తయ్యాయి (2/4 Done)</span>
              </div>
              <div class="farmer-task-list">
                <label class="farmer-task-item done">
                  <input type="checkbox" checked disabled>
                  <div class="task-info">
                    <span class="task-title">06:30 AM &bull; ఉదయం దాణా &amp; కాస్ట్ ట్రే తనిఖీ (Morning Feed Tray Check)</span>
                    <small>Tank 01-04 కాస్ట్ ట్రేలలో 94% దాణా ఖాళీ అయ్యింది &bull; Good appetite</small>
                  </div>
                  <span class="task-check-icon">&check;</span>
                </label>
                <label class="farmer-task-item done">
                  <input type="checkbox" checked disabled>
                  <div class="task-info">
                    <span class="task-title">12:30 PM &bull; మధ్యాహ్నం ఆక్సిజన్ &amp; ఉష్ణోగ్రత రికార్డు (Noon DO Log)</span>
                    <small>సగటు DO: 5.6 mg/L, ఉష్ణోగ్రత: 28.4&deg;C సాధారణం &bull; Logged</small>
                  </div>
                  <span class="task-check-icon">&check;</span>
                </label>
                <label class="farmer-task-item" id="taskProbiotics">
                  <input type="checkbox" id="chkProbiotics">
                  <div class="task-info">
                    <span class="task-title">04:30 PM &bull; సాయంత్రం ప్రోబయోటిక్స్ వేయడం (Probiotic Application)</span>
                    <small>బాసిల్లస్ సబ్‌టిలిస్ 500 గ్రాములు నీటిలో కలపండి &bull; Ready for tank</small>
                  </div>
                  <button type="button" class="btn-sm-action" id="btnMarkProbiotic">పూర్తి చేయండి (Done)</button>
                </label>
                <label class="farmer-task-item" id="taskNightAero">
                  <input type="checkbox" id="chkNightAero">
                  <div class="task-info">
                    <span class="task-title">09:00 PM &bull; రాత్రి ఏరియేటర్లు &amp; మోటారు వైరింగ్ తనిఖీ (Night Aeration Check)</span>
                    <small>4 ఏరియేటర్లు ఆన్‌లో ఉన్నాయో లేదో ధృవీకరించండి &bull; Inspect contactors</small>
                  </div>
                  <button type="button" class="btn-sm-action" id="btnMarkNightAero">పూర్తి చేయండి (Done)</button>
                </label>
              </div>
            </div>

            <!-- Quick Water Sample Logging Card -->
            <div class="panel farmer-quick-log-panel">
              <div class="panel-header">
                <div>
                  <h2 class="panel-title-text">నీటి నాణ్యత నమూనా నమోదు &bull; Log Water Test</h2>
                  <p class="panel-subtitle-text">ఫీల్డ్ కిట్ కొలతలు ఇక్కడ నమోదు చేయండి &bull; Rapid pondside entry</p>
                </div>
              </div>
              <form id="farmerQuickLogForm" class="farmer-quick-form">
                <div class="form-row">
                  <label for="farmerLogTank">చెరువు ఎంచుకోండి (Select Tank):</label>
                  <select id="farmerLogTank" class="form-select">
                    <option value="pond-01">చెరువు 01 (Tank 01)</option>
                    <option value="pond-02">చెరువు 02 (Tank 02)</option>
                    <option value="pond-03">చెరువు 03 (Tank 03)</option>
                    <option value="pond-04">చెరువు 04 (Tank 04)</option>
                  </select>
                </div>
                <div class="form-grid-2">
                  <div class="form-row">
                    <label for="farmerLogDO">ఆక్సిజన్ DO (mg/L):</label>
                    <input type="number" step="0.1" id="farmerLogDO" value="5.8" class="form-input">
                  </div>
                  <div class="form-row">
                    <label for="farmerLogTemp">ఉష్ణోగ్రత Temp (&deg;C):</label>
                    <input type="number" step="0.1" id="farmerLogTemp" value="28.4" class="form-input">
                  </div>
                </div>
                <div class="form-grid-2">
                  <div class="form-row">
                    <label for="farmerLogPH">ఆమ్లత pH:</label>
                    <input type="number" step="0.1" id="farmerLogPH" value="7.8" class="form-input">
                  </div>
                  <div class="form-row">
                    <label for="farmerLogSal">ఉప్పుశాతం Salinity (ppt):</label>
                    <input type="number" step="1" id="farmerLogSal" value="24" class="form-input">
                  </div>
                </div>
                <button type="submit" class="farmer-touch-btn submit-btn" id="btnFarmerSubmitLog">
                  &#128190; రీడింగ్స్ సేవ్ చేయండి (Save Sample to Database)
                </button>
              </form>
            </div>
          </div>
        </div>
"""

tech_experience_html = """
        <!-- =================================================================== -->
        <!-- ROLE 3: TECHNICAL EXPERIENCE (Engineering & Hardware Diagnostics) -->
        <!-- =================================================================== -->
        <div id="roleViewTech" class="role-experience-view" hidden>
          <!-- Technical Header -->
          <div class="tech-console-header">
            <div class="tech-title-block">
              <div class="tech-badge">
                <span class="role-indicator-pill tech">&#9881;&#65039; HARDWARE &amp; IOT DIAGNOSTICS</span>
                <span class="protocol-tag">RS-485 Modbus RTU &bull; MQTT &bull; Sovereign Edge</span>
              </div>
              <h1 class="tech-heading">Engineering &amp; Hardware Diagnostics Console</h1>
              <p class="tech-subheading">Physical probe fleet telemetry, Modbus slave addresses, 3-phase motor electrical parameters, and edge loopback tests.</p>
            </div>
            <div class="tech-actions">
              <button type="button" class="btn-outline-dark" id="btnRunEdgePing">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
                <span>Ping Edge Gateway</span>
              </button>
              <button type="button" class="btn-outline-dark" id="btnExportDiagnosticsLog">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                <span>Export Diag Logs</span>
              </button>
              <button type="button" class="btn-primary-blue" id="btnTestDryRunLoopback">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M8 12h8"/><path d="M12 8v8"/></svg>
                <span>Run DRY_RUN Loopback</span>
              </button>
            </div>
          </div>

          <!-- Hardware Infrastructure Readiness Deck -->
          <div class="tech-hardware-deck">
            <div class="tech-stat-card">
              <div class="card-top">
                <span class="deck-label">EDGE GATEWAY</span>
                <span class="status-chip online"><i class="status-dot"></i> ONLINE</span>
              </div>
              <strong class="deck-value">gw-alpha-01</strong>
              <div class="deck-meta">Heartbeat: <strong>1.1s</strong> &bull; IP: 192.168.1.100</div>
              <small class="deck-sub">Uptime: 14d 6h 32m &bull; CPU: 12%</small>
            </div>

            <div class="tech-stat-card">
              <div class="card-top">
                <span class="deck-label">MODBUS RTU BUS</span>
                <span class="status-chip online"><i class="status-dot"></i> HEALTHY</span>
              </div>
              <strong class="deck-value">1.0 Hz Poll</strong>
              <div class="deck-meta">Baud: 9600 8N1 &bull; CRC Errors: <strong>0</strong></div>
              <small class="deck-sub">RS-485 Bus Active on COM3</small>
            </div>

            <div class="tech-stat-card">
              <div class="card-top">
                <span class="deck-label">MQTT TELEMETRY</span>
                <span class="status-chip online"><i class="status-dot"></i> CONNECTED</span>
              </div>
              <strong class="deck-value">18 ms Latency</strong>
              <div class="deck-meta">Ingest: <strong>10 pkt/s</strong> &bull; QoS: 1</div>
              <small class="deck-sub">Topic: aqua/telemetry/farm-alpha/#</small>
            </div>

            <div class="tech-stat-card">
              <div class="card-top">
                <span class="deck-label">SOVEREIGN EDGE CACHE</span>
                <span class="status-chip online"><i class="status-dot"></i> SYNCED</span>
              </div>
              <strong class="deck-value">0 Pending</strong>
              <div class="deck-meta">SQLite WAL: <strong>1.2 MB</strong> &bull; Queue: 0</div>
              <small class="deck-sub">All mutations safely written</small>
            </div>
          </div>

          <!-- Sensor Probe Fleet Matrix -->
          <div class="panel tech-sensor-table-panel">
            <div class="panel-header">
              <div>
                <h2 class="panel-title-text">Deployed Sensor Probe Fleet &amp; Calibration Health</h2>
                <p class="panel-subtitle-text">Modbus slave node register mapping, supply voltage, and calibration validity</p>
              </div>
              <div class="table-actions">
                <input type="text" id="techSensorFilterInput" class="table-search-input" placeholder="Filter sensors...">
              </div>
            </div>
            <div class="table-scroll-wrapper">
              <table class="data-table-styled" id="techSensorTable">
                <thead>
                  <tr>
                    <th>Sensor Tag</th>
                    <th>Parameter</th>
                    <th>Tank ID</th>
                    <th>Protocol &amp; Address</th>
                    <th>Supply V</th>
                    <th>Signal RSSI</th>
                    <th>Calibration Validity</th>
                    <th>Raw Engineering Val</th>
                    <th>Interlock Mode</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody id="techSensorTableBody">
                  <!-- Dynamically populated rows from /api/v1/sensors -->
                </tbody>
              </table>
            </div>
          </div>

          <!-- 3-Phase Power Diagnostics & Actuator Contactor Interlocks -->
          <div class="tech-power-contactor-row">
            <!-- 3-Phase Power Diagnostics -->
            <div class="panel tech-power-panel">
              <div class="panel-header">
                <div>
                  <h2 class="panel-title-text">3-Phase Electrical Telemetry (Transformer Substation TX-01)</h2>
                  <p class="panel-subtitle-text">415V Line-to-Line voltages, phase current draw, and power factor</p>
                </div>
                <span class="badge-status">NOMINAL</span>
              </div>
              <div class="power-phases-grid">
                <div class="phase-card">
                  <span class="phase-tag">LINE L1-L2</span>
                  <strong class="phase-volts">412 V</strong>
                  <span class="phase-current">Current: <strong>7.2 A</strong></span>
                  <div class="phase-bar"><div class="fill" style="width: 72%;"></div></div>
                </div>
                <div class="phase-card">
                  <span class="phase-tag">LINE L2-L3</span>
                  <strong class="phase-volts">415 V</strong>
                  <span class="phase-current">Current: <strong>7.3 A</strong></span>
                  <div class="phase-bar"><div class="fill" style="width: 73%;"></div></div>
                </div>
                <div class="phase-card">
                  <span class="phase-tag">LINE L3-L1</span>
                  <strong class="phase-volts">410 V</strong>
                  <span class="phase-current">Current: <strong>7.1 A</strong></span>
                  <div class="phase-bar"><div class="fill" style="width: 71%;"></div></div>
                </div>
              </div>
              <div class="power-summary-stats">
                <div class="stat-item"><span>Phase Imbalance:</span> <strong>0.8%</strong> (Target &lt; 2.0%)</div>
                <div class="stat-item"><span>Total Active Power:</span> <strong>4.82 kW</strong></div>
                <div class="stat-item"><span>Power Factor (cos &phi;):</span> <strong>0.88</strong></div>
                <div class="stat-item"><span>Thermal Overload Status:</span> <b class="text-green">NORMAL (NO TRIP)</b></div>
              </div>
            </div>

            <!-- Actuator Contactor Auxiliary Verification & Safety Interlocks -->
            <div class="panel tech-contactor-panel">
              <div class="panel-header">
                <div>
                  <h2 class="panel-title-text">Actuator Contactor Feedback &amp; DRY_RUN Interlocks</h2>
                  <p class="panel-subtitle-text">Auxiliary NC/NO contact verification and edge safety gating</p>
                </div>
                <span class="badge-amber">DRY_RUN ACTIVE</span>
              </div>
              <div class="contactor-items-list" id="techContactorList">
                <div class="contactor-item">
                  <div class="contactor-info">
                    <strong>Pond 01 Aerator 01 (Contactor K1)</strong>
                    <small>Relay Ch 1 &bull; Auxiliary Feedback: VERIFIED CLOSED</small>
                  </div>
                  <span class="status-chip online">CLOSED (RUNNING)</span>
                  <span class="mode-tag">DRY_RUN</span>
                </div>
                <div class="contactor-item">
                  <div class="contactor-info">
                    <strong>Pond 01 Aerator 02 (Contactor K2)</strong>
                    <small>Relay Ch 2 &bull; Auxiliary Feedback: VERIFIED CLOSED</small>
                  </div>
                  <span class="status-chip online">CLOSED (RUNNING)</span>
                  <span class="mode-tag">DRY_RUN</span>
                </div>
                <div class="contactor-item">
                  <div class="contactor-info">
                    <strong>Pond 04 Aerator 01 (Contactor K13)</strong>
                    <small>Relay Ch 13 &bull; Auxiliary Feedback: VERIFIED CLOSED</small>
                  </div>
                  <span class="status-chip online">CLOSED (RUNNING)</span>
                  <span class="mode-tag">DRY_RUN</span>
                </div>
                <div class="contactor-item">
                  <div class="contactor-info">
                    <strong>River Intake Pump Contactor (Pump 01)</strong>
                    <small>High-Voltage Interlock: COIL DE-ENERGIZED</small>
                  </div>
                  <span class="status-chip stopped">OPEN (STANDBY)</span>
                  <span class="mode-tag">SAFETY GATED</span>
                </div>
              </div>
              <div class="safety-advisory-box">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                <span>Hardware Safety Interlock: All high-voltage 415V actuator contactors are strictly in software DRY_RUN mode until certified commissioning.</span>
              </div>
            </div>
          </div>

          <!-- Hardware Diagnostic Log Terminal -->
          <div class="panel tech-log-terminal-panel">
            <div class="panel-header">
              <div>
                <h2 class="panel-title-text">Edge Diagnostics &amp; Modbus Packet Feed</h2>
                <p class="panel-subtitle-text">Real-time serial frame telemetry, CRC evaluations, and gateway loopbacks</p>
              </div>
              <button type="button" class="btn-xs-dark" id="btnClearTechLog">Clear Log</button>
            </div>
            <pre class="tech-log-terminal" id="techLogTerminal">[2026-10-31T05:00:01.120Z] [INFO] Edge gateway gw-alpha-01 online. Modbus RTU polling active on COM3 (9600 8N1).
[2026-10-31T05:00:02.145Z] [MODBUS] Node 1 (Tank 01 Optical DO) Query: 01 03 00 00 00 02 C4 0B -&gt; Response: 01 03 04 40 BA 00 00 6C 4F -&gt; DO: 5.82 mg/L (CRC: OK)
[2026-10-31T05:00:02.210Z] [MODBUS] Node 1 (Tank 01 PT1000 Temp) Query: 01 03 00 02 00 02 65 CB -&gt; Response: 01 03 04 41 E3 33 33 2C 19 -&gt; Temp: 28.4 &deg;C (CRC: OK)
[2026-10-31T05:00:03.180Z] [MODBUS] Node 2 (Tank 02 Optical DO) Query: 02 03 00 00 00 02 C4 38 -&gt; Response: 02 03 04 40 B4 7A E1 1E 2D -&gt; DO: 5.64 mg/L (CRC: OK)
[2026-10-31T05:00:04.220Z] [POWER] Substation TX-01 3-Phase Meter Query: 0A 03 00 10 00 06 05 71 -&gt; L1: 412V, L2: 415V, L3: 410V (Imbalance: 0.8% - OK)
[2026-10-31T05:00:05.010Z] [SAFETY] Sovereign edge actuator safety check: DRY_RUN mode enforced. Physical 415V relays locked.</pre>
          </div>
        </div>
"""

new_dashboard_content = (
    before_main +
    "\n" +
    manager_experience_html +
    "\n" +
    main_body_core +
    "\n        </div><!-- End #roleViewManager -->\n" +
    farmer_experience_html +
    "\n" +
    tech_experience_html +
    "\n      " +
    main_end_tag +
    after_end
)

with open('apps/dashboard/index.html', 'w', encoding='utf-8') as f:
    f.write(new_dashboard_content)

print("index.html updated successfully with Manager, Farmer, and Tech role containers!")

