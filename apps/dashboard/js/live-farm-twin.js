/* Aqua OS Live Farm Digital Twin — High-Fidelity 2.5D Canvas Visualizer
 * Self-contained visual simulation representing Reservoir + Tanks 01 to 04.
 * Strictly decoupled from physical hardware actuation (DRY_RUN simulation only).
 */
(() => {
  "use strict";

  const canvas = document.getElementById("aquaFarmTwinCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  const tanks = [
    { id: 1, name: "Tank 01", doc: 42, do: 5.82, temp: 28.4, ph: 7.85, sal: 24.2, nh3: 0.08, level: 1.25, fans: [true, true, true, true], phase: 0.1 },
    { id: 2, name: "Tank 02", doc: 42, do: 5.64, temp: 28.7, ph: 7.90, sal: 24.5, nh3: 0.12, level: 1.22, fans: [true, true, true, false], phase: 0.9 },
    { id: 3, name: "Tank 03", doc: 35, do: 5.91, temp: 28.2, ph: 7.80, sal: 23.8, nh3: 0.05, level: 1.28, fans: [true, true, true, true], phase: 1.8 },
    { id: 4, name: "Tank 04", doc: 35, do: 4.88, temp: 29.1, ph: 7.95, sal: 25.1, nh3: 0.19, level: 1.20, fans: [true, true, true, true], phase: 2.7 }
  ];

  const reservoir = { name: "Reservoir Basin", capacity: "450 m³", level: 0.88, turbidity: "Low", phase: 1.2 };

  const state = {
    selected: 0,
    night: (new Date().getHours() < 6 || new Date().getHours() >= 18),
    feeding: false,
    feedUntil: 0,
    paused: false,
    zoom: 1.0,
    orbit: 0,
    drag: null,
    last: 0,
    raf: 0,
    particles: []
  };

  let width = 0, height = 0, dpr = 1, simTime = 0;
  const $ = id => document.getElementById(id);
  const clamp = (v, min, max) => Math.max(min, Math.min(max, v));

  // Initialize circulating water & aerator froth particles
  for (let i = 0; i < 60; i++) {
    state.particles.push({
      tankIdx: i % 4,
      u: Math.random(),
      v: Math.random(),
      speed: 0.0008 + Math.random() * 0.0012,
      size: 1.5 + Math.random() * 2.5,
      alpha: 0.2 + Math.random() * 0.5
    });
  }

  function resize() {
    const r = canvas.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return;
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = Math.round(r.width);
    height = Math.round(r.height);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  if (window.ResizeObserver) {
    const ro = new ResizeObserver(() => {
      resize();
      metrics();
    });
    ro.observe(canvas);
  }

  // Positioning coordinates for 4 rectangular tanks in 2x2 grid or linear cascade
  function tankCenter(i) {
    // Linear cascade down the farm terrain
    const startX = width * 0.36;
    const startY = height * 0.28;
    const offsetX = (i % 2 === 0 ? -1 : 1) * width * 0.16;
    const row = Math.floor(i / 2);
    const offsetY = row * height * 0.28;
    return {
      x: startX + offsetX + (state.orbit * width * 0.3),
      y: startY + offsetY
    };
  }

  function poly(points, fill, stroke, line = 1) {
    ctx.beginPath();
    points.forEach((p, idx) => idx ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y));
    ctx.closePath();
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = line; ctx.stroke(); }
  }

  function tankShape(i) {
    const c = tankCenter(i);
    const w = Math.min(width * 0.28, 290) * state.zoom;
    const h = Math.min(height * 0.13, 115) * state.zoom;
    const angle = -0.35 + (state.orbit * 0.4);
    const ux = Math.cos(angle), uy = Math.sin(angle);
    const vx = -Math.sin(angle) * 0.75, vy = Math.cos(angle) * 0.75;
    const pt = (a, b) => ({
      x: c.x + (ux * a * w / 2) + (vx * b * h / 2),
      y: c.y + (uy * a * w / 2) + (vy * b * h / 2)
    });
    return {
      c, w, h, pt,
      corners: [pt(-1, -1), pt(1, -1), pt(1, 1), pt(-1, 1)],
      bundDepth: 18 * state.zoom
    };
  }

  function drawRotor(x, y, r, on, angle) {
    ctx.save();
    ctx.translate(x, y);

    // Motor casing
    ctx.fillStyle = "#0c1e28";
    ctx.beginPath();
    ctx.ellipse(0, 4, r * 1.1, r * 0.45, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#1e3745";
    ctx.fillRect(-r * 0.15, -r * 0.35, r * 0.3, r * 0.9);

    // Rotating paddle wheel
    ctx.rotate(angle);
    ctx.strokeStyle = on ? "#38bdf8" : "#64748b";
    ctx.lineWidth = 1.8;
    ctx.fillStyle = on ? "#0284c7" : "#475569";
    for (let k = 0; k < 6; k++) {
      ctx.rotate(Math.PI / 3);
      ctx.beginPath();
      ctx.roundRect(-r * 0.12, -r * 0.95, r * 0.24, r * 0.6, 2);
      ctx.fill();
      ctx.stroke();
    }
    // Hub cap
    ctx.beginPath();
    ctx.arc(0, 0, r * 0.25, 0, Math.PI * 2);
    ctx.fillStyle = on ? "#e0f2fe" : "#94a3b8";
    ctx.fill();
    ctx.restore();
  }

  function drawWater(i, t) {
    const tank = tankShape(i);
    const p = tank.corners;
    const d = tank.bundDepth;

    // Draw Concrete Bund Wall Thickness (Isometric 2.5D Drop)
    const baseP = p.map(pt => ({ x: pt.x, y: pt.y + d }));
    ctx.save();
    // South-facing concrete walls
    poly([p[3], p[2], baseP[2], baseP[3]], state.night ? "#07131b" : "#132b36", state.night ? "#0d202d" : "#1e3e4d", 1);
    poly([p[2], p[1], baseP[1], baseP[2]], state.night ? "#091722" : "#193542", state.night ? "#0f2636" : "#23495b", 1);

    // Concrete top rim
    poly(p, state.night ? "#0b1d28" : "#1b3846", state.night ? "#1e3a4b" : "#326277", 2);

    // Inset water polygon
    const inset = p.map(pt => {
      return {
        x: tank.c.x + (pt.x - tank.c.x) * 0.93,
        y: tank.c.y + (pt.y - tank.c.y) * 0.88
      };
    });

    // Clip to water area
    ctx.save();
    ctx.beginPath();
    inset.forEach((v, idx) => idx ? ctx.lineTo(v.x, v.y) : ctx.moveTo(v.x, v.y));
    ctx.closePath();
    ctx.clip();

    // Water depth gradient
    const grad = ctx.createLinearGradient(tank.c.x, tank.c.y - tank.h, tank.c.x, tank.c.y + tank.h);
    if (state.night) {
      grad.addColorStop(0, "#052233");
      grad.addColorStop(0.5, "#031724");
      grad.addColorStop(1, "#020f18");
    } else {
      grad.addColorStop(0, "#0e4d64");
      grad.addColorStop(0.5, "#083747");
      grad.addColorStop(1, "#042531");
    }
    ctx.fillStyle = grad;
    ctx.fillRect(tank.c.x - tank.w, tank.c.y - tank.h * 1.5, tank.w * 2, tank.h * 3);

    // Subtle water surface ripples
    for (let n = 0; n < 14; n++) {
      const rx = tank.c.x + Math.sin(simTime * 0.0003 + n * 2.1 + i) * tank.w * 0.44;
      const ry = tank.c.y + Math.cos(simTime * 0.00025 + n * 1.6 + i) * tank.h * 0.35;
      ctx.beginPath();
      ctx.ellipse(rx, ry, 10 + (n % 12), 2.5, Math.sin(n) * 0.15, 0, Math.PI * 2);
      ctx.strokeStyle = state.night ? "rgba(56, 189, 248, 0.12)" : "rgba(103, 232, 249, 0.22)";
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    // Aerator dynamic circulation froth
    const runningFans = t.fans.filter(Boolean).length;
    if (runningFans > 0 && !state.feeding) {
      for (let n = 0; n < runningFans * 4; n++) {
        const f = ((simTime * 0.00015) + (n / (runningFans * 4)) + (i * 0.15)) % 1;
        const fx = tank.c.x - tank.w * 0.38 + f * tank.w * 0.76;
        const fy = tank.c.y + Math.sin(f * Math.PI * 4 + simTime * 0.001) * tank.h * 0.26;
        ctx.beginPath();
        ctx.arc(fx, fy, 2.2 + Math.sin(f * 10) * 1.2, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(224, 242, 254, 0.45)";
        ctx.fill();
      }
    }

    ctx.restore(); // Exit clip

    // Water rim highlight
    poly(inset, null, state.night ? "rgba(56, 189, 248, 0.25)" : "rgba(103, 232, 249, 0.45)", 1.2);

    // 4 Paddlewheel aerators along the bank
    for (let k = 0; k < 4; k++) {
      const frac = (k - 1.5) / 4.2;
      const pos = tank.pt(frac, 0.82);
      const isRunning = t.fans[k] && !state.feeding;
      drawRotor(pos.x, pos.y, Math.max(8, Math.min(14, width * 0.012)), isRunning, simTime * 0.004 * (isRunning ? 1 : 0) + k * 0.3);

      if (isRunning) {
        // Aeration water spray/froth ring
        ctx.beginPath();
        ctx.ellipse(pos.x, pos.y + 7, 12 * state.zoom, 4 * state.zoom, 0, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(56, 189, 248, 0.55)";
        ctx.lineWidth = 1.4;
        ctx.stroke();
      }
    }

    // Floating Sensor Buoy with blinking green LED
    const buoyPos = tank.pt(0.2, -0.2);
    ctx.beginPath();
    ctx.arc(buoyPos.x, buoyPos.y, 5 * state.zoom, 0, Math.PI * 2);
    ctx.fillStyle = "#f59e0b";
    ctx.fill();
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1;
    ctx.stroke();

    const ledGlow = (Math.sin(simTime * 0.005 + i) + 1) * 0.5;
    ctx.beginPath();
    ctx.arc(buoyPos.x, buoyPos.y - 4, 2, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(16, 185, 129, ${0.4 + ledGlow * 0.6})`;
    ctx.fill();

    // Floating Tank Identifier Badge
    const labelPos = tank.pt(-0.35, -0.45);
    const isSelected = state.selected === i;
    ctx.fillStyle = isSelected ? "rgba(14, 165, 233, 0.88)" : "rgba(15, 23, 42, 0.82)";
    ctx.beginPath();
    ctx.roundRect(labelPos.x - 42, labelPos.y - 12, 84, 24, 6);
    ctx.fill();
    ctx.strokeStyle = isSelected ? "#38bdf8" : "rgba(255, 255, 255, 0.15)";
    ctx.lineWidth = isSelected ? 2 : 1;
    ctx.stroke();

    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 11px system-ui, -apple-system, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(t.name, labelPos.x, labelPos.y + 4);

    // Selection Glowing Halo
    if (isSelected) {
      ctx.strokeStyle = "#38bdf8";
      ctx.lineWidth = 2.8;
      poly(p, null, ctx.strokeStyle, 2.8);
    }
  }

  function drawReservoir(t) {
    const c = { x: width * 0.72 + (state.orbit * width * 0.2), y: height * 0.18 };
    const w = Math.min(width * 0.24, 240) * state.zoom;
    const h = Math.min(height * 0.12, 95) * state.zoom;
    const p = [
      { x: c.x - w * 0.5, y: c.y - h * 0.2 },
      { x: c.x + w * 0.5, y: c.y - h * 0.65 },
      { x: c.x + w * 0.5, y: c.y + h * 0.35 },
      { x: c.x - w * 0.5, y: c.y + h * 0.8 }
    ];

    // Reservoir concrete foundation
    poly(p, state.night ? "#091722" : "#173747", state.night ? "#142d3d" : "#27556c", 3);

    const inset = p.map(pt => ({
      x: c.x + (pt.x - c.x) * 0.92,
      y: c.y + (pt.y - c.y) * 0.86
    }));

    ctx.save();
    ctx.beginPath();
    inset.forEach((pt, idx) => idx ? ctx.lineTo(pt.x, pt.y) : ctx.moveTo(pt.x, pt.y));
    ctx.closePath();
    ctx.clip();

    const rGrad = ctx.createLinearGradient(c.x, c.y - h, c.x, c.y + h);
    rGrad.addColorStop(0, state.night ? "#042235" : "#0d5b76");
    rGrad.addColorStop(1, state.night ? "#02121d" : "#062b38");
    ctx.fillStyle = rGrad;
    ctx.fillRect(c.x - w, c.y - h * 1.5, w * 2, h * 3);

    // Reservoir water swirl
    for (let n = 0; n < 10; n++) {
      const rx = c.x + Math.sin(simTime * 0.0002 + n * 2.3) * w * 0.4;
      const ry = c.y + Math.cos(simTime * 0.00018 + n * 1.7) * h * 0.35;
      ctx.beginPath();
      ctx.ellipse(rx, ry, 12, 3, 0, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(103, 232, 249, 0.28)";
      ctx.stroke();
    }
    ctx.restore();

    poly(inset, null, "rgba(56, 189, 248, 0.4)", 1.2);

    // Label
    ctx.fillStyle = "rgba(15, 23, 42, 0.82)";
    ctx.beginPath();
    ctx.roundRect(c.x - 45, c.y - 10, 90, 20, 5);
    ctx.fill();
    ctx.strokeStyle = "rgba(255, 255, 255, 0.2)";
    ctx.stroke();
    ctx.fillStyle = "#e0f2fe";
    ctx.font = "bold 10px system-ui";
    ctx.textAlign = "center";
    ctx.fillText("RESERVOIR BASIN", c.x, c.y + 4);

    // Intake Canal Pipeline to Tanks (Flowing Pulses)
    ctx.beginPath();
    ctx.moveTo(c.x - w * 0.4, c.y + h * 0.5);
    ctx.quadraticCurveTo(width * 0.52, height * 0.24, width * 0.42, height * 0.32);
    ctx.strokeStyle = "rgba(56, 189, 248, 0.4)";
    ctx.lineWidth = 3;
    ctx.setLineDash([6, 8]);
    ctx.lineDashOffset = -simTime * 0.015;
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function drawFarm(ts) {
    ctx.clearRect(0, 0, width, height);

    // Sky / Environment background
    const bg = ctx.createLinearGradient(0, 0, 0, height);
    if (state.night) {
      bg.addColorStop(0, "#030b14");
      bg.addColorStop(0.5, "#061320");
      bg.addColorStop(1, "#071726");
    } else {
      bg.addColorStop(0, "#0c2536");
      bg.addColorStop(0.5, "#0f3246");
      bg.addColorStop(1, "#0a2231");
    }
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, width, height);

    // Celestial Sun or Moon
    ctx.beginPath();
    ctx.arc(width * 0.12, height * 0.14, state.night ? 14 : 22, 0, Math.PI * 2);
    ctx.fillStyle = state.night ? "#f1f5f9" : "#fbbf24";
    ctx.shadowColor = state.night ? "#94a3b8" : "#f59e0b";
    ctx.shadowBlur = state.night ? 16 : 28;
    ctx.fill();
    ctx.shadowBlur = 0;

    // Farm ground earthen plateau
    ctx.save();
    ctx.translate(width * 0.48, height * 0.52);
    ctx.rotate(-0.35 + (state.orbit * 0.4));
    ctx.fillStyle = state.night ? "#0f232f" : "#1e4453";
    ctx.fillRect(-width * 0.45, -height * 0.48, width * 0.9, height * 0.96);
    ctx.strokeStyle = state.night ? "rgba(30, 58, 77, 0.4)" : "rgba(56, 189, 248, 0.15)";
    ctx.lineWidth = 2;
    ctx.strokeRect(-width * 0.45, -height * 0.48, width * 0.9, height * 0.96);
    ctx.restore();

    // Render Reservoir first (top-layer in background)
    drawReservoir(ts);

    // Render 4 Tanks from back to front
    for (let i = 0; i < 4; i++) {
      drawWater(i, tanks[i]);
    }

    // Feeding cycle banner overlay
    if (state.feeding) {
      ctx.fillStyle = "rgba(15, 23, 42, 0.85)";
      ctx.beginPath();
      ctx.roundRect(width * 0.5 - 120, 18, 240, 32, 8);
      ctx.fill();
      ctx.strokeStyle = "#f59e0b";
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.fillStyle = "#fbbf24";
      ctx.font = "bold 11px system-ui";
      ctx.textAlign = "center";
      ctx.fillText("🥣 FEEDING CYCLE DEMO · AERATORS AUTO-PAUSED", width * 0.5, 38);
    }

    if (state.paused) {
      ctx.fillStyle = "rgba(3, 11, 20, 0.75)";
      ctx.fillRect(0, 0, width, height);
      ctx.fillStyle = "#ffffff";
      ctx.font = "bold 18px system-ui";
      ctx.textAlign = "center";
      ctx.fillText("SIMULATION PAUSED", width / 2, height / 2);
    }
  }

  function metrics() {
    const t = tanks[state.selected];
    const nameEl = $("farmTwinSelectedName");
    const statusEl = $("farmTwinSelectedStatus");
    const metricsEl = $("farmTwinMetrics");
    const equipEl = $("farmTwinEquipment");
    const assetListEl = $("farmTwinAssetList");

    if (nameEl) nameEl.textContent = t.name;
    if (statusEl) {
      const isLowDO = t.do < 5.0;
      statusEl.textContent = isLowDO ? "ATTENTION · LOW DO (SIMULATION)" : "OPTIMAL · DRY_RUN (SIMULATION)";
      statusEl.className = "live-farm-status " + (isLowDO ? "status-warning" : "status-normal");
    }

    if (metricsEl) {
      metricsEl.innerHTML = [
        ["Dissolved Oxygen", t.do.toFixed(2), "mg/L", t.do >= 5.0 ? "good" : "warning"],
        ["Water Temperature", t.temp.toFixed(1), "°C", "good"],
        ["Acidity / pH", t.ph.toFixed(2), "pH", "good"],
        ["Salinity", t.sal.toFixed(1), "ppt", "good"],
        ["Ammonia (NH₃)", t.nh3.toFixed(2), "mg/L", t.nh3 < 0.15 ? "good" : "warning"],
        ["Pond Depth Level", t.level.toFixed(2), "m", "good"]
      ].map(([label, val, unit, status]) => `
        <div class="live-farm-metric">
          <span>${label}</span>
          <strong class="${status === 'warning' ? 'text-amber' : ''}">${val} <small>${unit}</small></strong>
          <small class="metric-note">Simulation Value</small>
        </div>
      `).join("");
    }

    if (equipEl) {
      equipEl.innerHTML = t.fans.map((on, k) => `
        <button type="button" class="live-farm-action ${on && !state.feeding ? 'live-farm-action-primary' : ''}" data-fan="${k}">
          ⚡ Aerator 0${k + 1}: ${on && !state.feeding ? 'RUNNING' : 'STOPPED'} (DRY_RUN)
        </button>
      `).join("");

      equipEl.querySelectorAll("[data-fan]").forEach(btn => {
        btn.addEventListener("click", () => {
          const idx = Number(btn.dataset.fan);
          t.fans[idx] = !t.fans[idx];
          metrics();
        });
      });
    }

    if (assetListEl) {
      assetListEl.innerHTML = `
        <button class="live-farm-asset-button" data-asset="reservoir">
          <div><b>Reservoir Basin</b><small>Capacity 450 m³ • Low Turbidity</small></div>
          <span class="badge-blue">SOURCE</span>
        </button>
      ` + tanks.map((v, i) => `
        <button class="live-farm-asset-button ${i === state.selected ? 'active' : ''}" data-asset="${i}">
          <div><b>${v.name}</b><small>DOC: ${v.doc}d • DO: ${v.do.toFixed(1)} mg/L</small></div>
          <span class="badge-status">${v.fans.filter(Boolean).length}/4 Aerators</span>
        </button>
      `).join("");

      assetListEl.querySelectorAll("[data-asset]").forEach(btn => {
        btn.addEventListener("click", () => {
          if (btn.dataset.asset === "reservoir") return;
          state.selected = Number(btn.dataset.asset);
          metrics();
        });
      });
    }
  }

  function tick(ts) {
    if (!state.last) state.last = ts;
    const dt = Math.min(50, ts - state.last);
    state.last = ts;
    simTime += dt;

    if (width <= 10 || height <= 10) {
      resize();
    }

    if (!state.paused) {
      tanks.forEach((t, i) => {
        const s = simTime / 1000;
        t.do = clamp(5.65 + i * 0.08 + Math.sin(s * 0.04 + i) * 0.15, 4.4, 7.2);
        t.temp = clamp(28.4 + i * 0.15 + Math.sin(s * 0.02 + i * 0.5) * 0.2, 27.0, 31.5);
        t.ph = clamp(7.85 + i * 0.02 + Math.sin(s * 0.01 + i) * 0.02, 7.5, 8.4);
        t.sal = clamp(24.0 + i * 0.3 + Math.sin(s * 0.005 + i) * 0.1, 15.0, 35.0);
      });
    }

    const clockEl = $("farmTwinClock");
    if (clockEl) clockEl.textContent = new Date().toLocaleTimeString();

    const envEl = $("farmTwinEnvironment");
    if (envEl) envEl.textContent = (state.night ? "Night Environment" : "Daylight Environment") + " · Digital Twin Simulation";

    if (state.feeding && Date.now() > state.feedUntil) {
      state.feeding = false;
      const feedBtn = $("farmTwinFeed");
      if (feedBtn) feedBtn.textContent = "▶ Start feeding demo";
      metrics();
    }

    drawFarm(ts);
    state.raf = requestAnimationFrame(tick);
  }

  function selectAt(x, y) {
    for (let i = 0; i < 4; i++) {
      const p = tankShape(i).corners;
      const minX = Math.min(...p.map(v => v.x)), maxX = Math.max(...p.map(v => v.x));
      const minY = Math.min(...p.map(v => v.y)), maxY = Math.max(...p.map(v => v.y));
      if (x >= minX && x <= maxX && y >= minY && y <= maxY) {
        state.selected = i;
        metrics();
        return;
      }
    }
  }

  // Pointer event interactions for dragging & clicking tanks
  canvas.addEventListener("pointerdown", e => {
    state.drag = { x: e.clientX, y: e.clientY, moved: false };
    canvas.setPointerCapture(e.pointerId);
  });

  canvas.addEventListener("pointermove", e => {
    if (!state.drag) return;
    const dx = e.clientX - state.drag.x;
    if (Math.abs(dx) > 3) state.drag.moved = true;
    state.orbit = clamp(state.orbit + dx * 0.0015, -0.35, 0.35);
    state.drag.x = e.clientX;
  });

  canvas.addEventListener("pointerup", e => {
    if (state.drag && !state.drag.moved) {
      const r = canvas.getBoundingClientRect();
      selectAt(e.clientX - r.left, e.clientY - r.top);
    }
    state.drag = null;
  });

  canvas.addEventListener("wheel", e => {
    e.preventDefault();
    state.zoom = clamp(state.zoom + (e.deltaY < 0 ? 0.05 : -0.05), 0.8, 1.35);
  }, { passive: false });

  // Toolbar Actions
  const btnDayNight = $("farmTwinDayNight");
  if (btnDayNight) {
    btnDayNight.addEventListener("click", () => {
      state.night = !state.night;
    });
  }

  const btnFeed = $("farmTwinFeed");
  if (btnFeed) {
    btnFeed.addEventListener("click", () => {
      state.feeding = !state.feeding;
      state.feedUntil = Date.now() + 25000;
      btnFeed.textContent = state.feeding ? "■ Stop feeding demo" : "▶ Start feeding demo";
      metrics();
    });
  }

  const btnReset = $("farmTwinReset");
  if (btnReset) {
    btnReset.addEventListener("click", () => {
      tanks.forEach(t => t.fans = [true, true, true, true]);
      state.feeding = false;
      state.paused = false;
      state.zoom = 1.0;
      state.orbit = 0;
      if (btnFeed) btnFeed.textContent = "▶ Start feeding demo";
      metrics();
    });
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      cancelAnimationFrame(state.raf);
    } else {
      state.last = 0;
      state.raf = requestAnimationFrame(tick);
    }
  });

  window.addEventListener("resize", resize);

  // Global trigger for section navigation
  window.initLiveFarmTwin = () => {
    resize();
    metrics();
  };

  // Initial setup
  resize();
  metrics();
  state.raf = requestAnimationFrame(tick);
})();
