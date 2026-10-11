/**
 * Aqua OS - Self-Contained SVG Trend Chart Renderer (Zero External Dependencies)
 * 100% Offline-capable, lightweight, native SVG vector graphics.
 */

class SVGTimeSeriesChart {
  constructor(containerId, options = {}) {
    this.container = document.getElementById(containerId);
    this.options = Object.assign(
      {
        width: 700,
        height: 220,
        padding: { top: 20, right: 30, bottom: 30, left: 45 },
        lineColor: "#38bdf8",
        fillColor: "rgba(56, 189, 248, 0.12)",
        unit: "",
        metricName: "Value",
      },
      options
    );
  }

  render(dataPoints, thresholds = null) {
    if (!this.container) return;
    this.container.innerHTML = "";

    if (!dataPoints || dataPoints.length === 0) {
      this.container.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b;font-size:0.85rem;">
          No historical telemetry points available for this time window.
        </div>`;
      return;
    }

    const { width, height, padding, lineColor, fillColor, unit } = this.options;
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;

    // Extract values & timestamps
    const values = dataPoints.map((d) => d.value);
    const times = dataPoints.map((d) => new Date(d.timestamp).getTime());

    let minVal = Math.min(...values);
    let maxVal = Math.max(...values);

    // Expand bounds if thresholds are given
    if (thresholds) {
      if (thresholds.min_critical !== undefined) minVal = Math.min(minVal, thresholds.min_critical);
      if (thresholds.max_critical !== undefined) maxVal = Math.max(maxVal, thresholds.max_critical);
      if (thresholds.min_warning !== undefined) minVal = Math.min(minVal, thresholds.min_warning);
      if (thresholds.max_warning !== undefined) maxVal = Math.max(maxVal, thresholds.max_warning);
    }

    // Add 10% breathing room
    const range = maxVal - minVal || 1.0;
    minVal = Math.max(0, minVal - range * 0.1);
    maxVal = maxVal + range * 0.1;

    const minTime = Math.min(...times);
    const maxTime = Math.max(...times);
    const timeSpan = maxTime - minTime || 1;

    // Coordinate mapping functions
    const getX = (t) => padding.left + ((t - minTime) / timeSpan) * chartW;
    const getY = (v) => padding.top + chartH - ((v - minVal) / (maxVal - minVal)) * chartH;

    // Build SVG
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("style", "width:100%;height:100%;overflow:visible;");

    // Gridlines & Y-axis labels
    const steps = 4;
    for (let i = 0; i <= steps; i++) {
      const val = minVal + (i / steps) * (maxVal - minVal);
      const y = getY(val);

      // Grid line
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", padding.left);
      line.setAttribute("y1", y);
      line.setAttribute("x2", width - padding.right);
      line.setAttribute("y2", y);
      line.setAttribute("stroke", "#1f2937");
      line.setAttribute("stroke-dasharray", "3,3");
      svg.appendChild(line);

      // Y-axis Label
      const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      text.setAttribute("x", padding.left - 6);
      text.setAttribute("y", y + 3);
      text.setAttribute("text-anchor", "end");
      text.setAttribute("fill", "#6b7280");
      text.setAttribute("font-size", "10");
      text.setAttribute("font-family", "ui-monospace, monospace");
      text.textContent = val.toFixed(1);
      svg.appendChild(text);
    }

    // Threshold lines if provided
    if (thresholds) {
      if (thresholds.min_critical !== undefined && thresholds.min_critical >= minVal && thresholds.min_critical <= maxVal) {
        const yCrit = getY(thresholds.min_critical);
        const critLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
        critLine.setAttribute("x1", padding.left);
        critLine.setAttribute("y1", yCrit);
        critLine.setAttribute("x2", width - padding.right);
        critLine.setAttribute("y2", yCrit);
        critLine.setAttribute("stroke", "#ef4444");
        critLine.setAttribute("stroke-width", "1.5");
        critLine.setAttribute("stroke-dasharray", "4,2");
        svg.appendChild(critLine);
      }
      if (thresholds.min_warning !== undefined && thresholds.min_warning >= minVal && thresholds.min_warning <= maxVal) {
        const yWarn = getY(thresholds.min_warning);
        const warnLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
        warnLine.setAttribute("x1", padding.left);
        warnLine.setAttribute("y1", yWarn);
        warnLine.setAttribute("x2", width - padding.right);
        warnLine.setAttribute("y2", yWarn);
        warnLine.setAttribute("stroke", "#f59e0b");
        warnLine.setAttribute("stroke-width", "1.5");
        warnLine.setAttribute("stroke-dasharray", "4,2");
        svg.appendChild(warnLine);
      }
    }

    // Time Axis (X-axis) Labels (start, middle, end)
    const timeLabels = [
      { time: minTime, x: padding.left, anchor: "start" },
      { time: minTime + timeSpan / 2, x: padding.left + chartW / 2, anchor: "middle" },
      { time: maxTime, x: width - padding.right, anchor: "end" },
    ];

    timeLabels.forEach((tl) => {
      const d = new Date(tl.time);
      const timeStr = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
      const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      text.setAttribute("x", tl.x);
      text.setAttribute("y", height - 8);
      text.setAttribute("text-anchor", tl.anchor);
      text.setAttribute("fill", "#6b7280");
      text.setAttribute("font-size", "10");
      text.setAttribute("font-family", "ui-monospace, monospace");
      text.textContent = timeStr;
      svg.appendChild(text);
    });

    // Build Path Coordinates
    const points = dataPoints.map((d) => ({
      x: getX(new Date(d.timestamp).getTime()),
      y: getY(d.value),
      d: d,
    }));

    const pathStr = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");

    // Fill Area under curve
    if (points.length > 1) {
      const firstX = points[0].x.toFixed(1);
      const lastX = points[points.length - 1].x.toFixed(1);
      const bottomY = (padding.top + chartH).toFixed(1);
      const areaStr = `${pathStr} L ${lastX} ${bottomY} L ${firstX} ${bottomY} Z`;

      const areaPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
      areaPath.setAttribute("d", areaStr);
      areaPath.setAttribute("fill", fillColor);
      svg.appendChild(areaPath);
    }

    // Line Path
    const linePath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    linePath.setAttribute("d", pathStr);
    linePath.setAttribute("fill", "none");
    linePath.setAttribute("stroke", lineColor);
    linePath.setAttribute("stroke-width", "2.5");
    linePath.setAttribute("stroke-linejoin", "round");
    linePath.setAttribute("stroke-linecap", "round");
    svg.appendChild(linePath);

    // Point Markers with Tooltip interaction
    points.forEach((p) => {
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("cx", p.x.toFixed(1));
      circle.setAttribute("cy", p.y.toFixed(1));
      circle.setAttribute("r", "3.5");
      circle.setAttribute("fill", "#fff");
      circle.setAttribute("stroke", lineColor);
      circle.setAttribute("stroke-width", "2");

      const timeFmt = new Date(p.d.timestamp).toLocaleTimeString();
      const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
      title.textContent = `[${timeFmt}] ${p.d.value.toFixed(2)} ${unit} (${p.d.quality || "GOOD"})`;
      circle.appendChild(title);

      svg.appendChild(circle);
    });

    this.container.appendChild(svg);
  }
}

