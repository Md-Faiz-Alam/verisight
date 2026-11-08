"use strict";

// Dependency-free charts. Every label is set as text, never parsed as markup.
// Colours come from CSS variables, so a theme change needs no redraw.
const VSCharts = (() => {
  const SVG_NS = "http://www.w3.org/2000/svg";

  function svg(tag, attrs = {}, ...children) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === "text") node.textContent = value;
      else if (value !== null && value !== undefined) node.setAttribute(key, String(value));
    }
    node.append(...children);
    return node;
  }

  function toNumber(value) {
    const number = typeof value === "number" ? value : Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function compact(value) {
    const number = toNumber(value);
    if (number === null) return "–";
    const size = Math.abs(number);
    // Figures stay in full below 10,000, then shorten in thousands and up.
    const scale = [[1e12, "T", 1e12], [1e9, "B", 1e9], [1e6, "M", 1e6], [1e3, "K", 1e4]]
      .find(([, , from]) => size >= from);
    if (scale) {
      const scaled = number / scale[0];
      const fixed = scaled.toFixed(Math.abs(scaled) >= 100 ? 0 : 1).replace(/\.0$/, "");
      return `${fixed}${scale[1]}`;
    }
    const digits = size >= 100 || Number.isInteger(number) ? 0 : size >= 1 ? 2 : 3;
    return number.toLocaleString("en-US", { maximumFractionDigits: digits });
  }

  function niceScale(rawLow, rawHigh, count = 4) {
    const low = Math.min(rawLow, rawHigh);
    let high = Math.max(rawLow, rawHigh);
    if (low === high) high = low + (Math.abs(low) || 1);
    const rough = (high - low) / count;
    const power = 10 ** Math.floor(Math.log10(rough));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough);
    const start = Math.floor(low / step) * step;
    const end = Math.ceil(high / step) * step;
    const ticks = [];
    for (let tick = start; tick <= end + step / 2; tick += step) ticks.push(Math.round(tick / step) * step);
    return { start, end, ticks };
  }

  function tooltip(host) {
    const tip = document.createElement("div");
    tip.className = "chart-tip";
    tip.hidden = true;
    host.append(tip);
    return {
      show(x, y, title, lines) {
        const head = document.createElement("b");
        head.textContent = title;
        tip.replaceChildren(head, ...lines.map((line) => {
          const row = document.createElement("span");
          row.textContent = line;
          return row;
        }));
        tip.hidden = false;
        const room = host.clientWidth - tip.offsetWidth - 4;
        tip.style.left = `${Math.max(4, Math.min(x + 12, room))}px`;
        tip.style.top = `${Math.max(0, y - tip.offsetHeight - 10)}px`;
      },
      hide() { tip.hidden = true; },
    };
  }

  function yAxis(group, scale, y, left, right) {
    for (const tick of scale.ticks) {
      group.append(
        svg("line", { x1: left, x2: right, y1: y(tick), y2: y(tick), class: tick === 0 ? "axis-base" : "grid" }),
        svg("text", { x: left - 8, y: y(tick) + 4, class: "tick", "text-anchor": "end", text: compact(tick) }),
      );
    }
  }

  // One measure over time: a 2px line, a light wash, and a crosshair on hover.
  function line(host, { points, label }) {
    host.replaceChildren();
    const usable = points.map((p) => ({ ...p, number: toNumber(p.value) })).filter((p) => p.number !== null);
    if (usable.length < 2) return;
    const width = Math.max(host.clientWidth, 280);
    const height = 260;
    const margin = { top: 16, right: 18, bottom: 28, left: 58 };
    const values = usable.map((p) => p.number);
    const low = Math.min(...values);
    const high = Math.max(...values);
    const scale = niceScale(low >= 0 && low < high * 0.6 ? 0 : low, high);
    const x = (i) => margin.left + (i / (usable.length - 1)) * (width - margin.left - margin.right);
    const y = (v) => height - margin.bottom - ((v - scale.start) / (scale.end - scale.start)) * (height - margin.top - margin.bottom);
    const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, width, height, role: "img", "aria-label": `${label}: ${usable.length} periods, line chart. Open Table for the values.` });
    const grid = svg("g");
    yAxis(grid, scale, y, margin.left, width - margin.right);
    root.append(grid);
    const maxLabels = Math.max(2, Math.floor((width - margin.left - margin.right) / 86));
    const every = Math.max(1, Math.ceil((usable.length - 1) / (maxLabels - 1)));
    usable.forEach((p, i) => {
      if (i % every !== 0) return;
      root.append(svg("text", { x: x(i), y: height - 8, class: "tick", "text-anchor": i === 0 ? "start" : i === usable.length - 1 ? "end" : "middle", text: p.period }));
    });
    const path = usable.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.number).toFixed(1)}`).join("");
    const base = y(Math.max(scale.start, Math.min(0, scale.end)));
    root.append(
      svg("path", { d: `${path}L${x(usable.length - 1).toFixed(1)} ${base}L${x(0).toFixed(1)} ${base}Z`, class: "area" }),
      svg("path", { d: path, class: "line", pathLength: 1 }),
    );
    const last = usable[usable.length - 1];
    root.append(svg("circle", { cx: x(usable.length - 1), cy: y(last.number), r: 4, class: "dot" }));
    const cross = svg("line", { y1: margin.top, y2: height - margin.bottom, class: "cross", visibility: "hidden" });
    const focus = svg("circle", { r: 5, class: "dot", visibility: "hidden" });
    const hit = svg("rect", { x: margin.left, y: 0, width: width - margin.left - margin.right, height, class: "hit" });
    root.append(cross, focus, hit);
    host.append(root);
    const tip = tooltip(host);
    const clear = () => { cross.setAttribute("visibility", "hidden"); focus.setAttribute("visibility", "hidden"); tip.hide(); };
    hit.addEventListener("pointermove", (event) => {
      const box = root.getBoundingClientRect();
      const ratio = (event.clientX - box.left - margin.left) / (width - margin.left - margin.right);
      const index = Math.max(0, Math.min(usable.length - 1, Math.round(ratio * (usable.length - 1))));
      const point = usable[index];
      cross.setAttribute("x1", x(index));
      cross.setAttribute("x2", x(index));
      cross.setAttribute("visibility", "visible");
      focus.setAttribute("cx", x(index));
      focus.setAttribute("cy", y(point.number));
      focus.setAttribute("visibility", "visible");
      tip.show(x(index), y(point.number), point.period, [`${label}: ${compact(point.number)}`, `${point.rows.toLocaleString("en-US")} rows`]);
    });
    hit.addEventListener("pointerleave", clear);
  }

  // Equal-width ranges of one measure, as thin columns from a shared baseline.
  function histogram(host, { bins, label }) {
    host.replaceChildren();
    const width = Math.max(host.clientWidth, 240);
    const height = 200;
    const margin = { top: 12, right: 8, bottom: 26, left: 46 };
    const scale = niceScale(0, Math.max(...bins.map((b) => b.rows), 1), 3);
    const inner = width - margin.left - margin.right;
    const band = inner / bins.length;
    const columnWidth = Math.min(24, band - 2);
    const y = (v) => height - margin.bottom - (v / scale.end) * (height - margin.top - margin.bottom);
    const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, width, height, role: "img", "aria-label": `${label}: ${bins.length} equal ranges, column chart. Open Table for the values.` });
    const grid = svg("g");
    yAxis(grid, scale, y, margin.left, width - margin.right);
    root.append(grid);
    host.append(root);
    const tip = tooltip(host);
    bins.forEach((bin, i) => {
      const left = margin.left + band * i + (band - columnWidth) / 2;
      const top = y(bin.rows);
      const bottom = y(0);
      if (bin.rows > 0) {
        const radius = Math.min(4, bottom - top, columnWidth / 2);
        root.append(svg("path", {
          class: "column",
          d: `M${left} ${bottom}V${top + radius}Q${left} ${top} ${left + radius} ${top}H${left + columnWidth - radius}Q${left + columnWidth} ${top} ${left + columnWidth} ${top + radius}V${bottom}Z`,
        }));
      }
      const hit = svg("rect", { x: margin.left + band * i, y: 0, width: band, height, class: "hit" });
      hit.addEventListener("pointerenter", () => tip.show(left, top, `${compact(bin.low)} to ${compact(bin.high)}`, [`${bin.rows.toLocaleString("en-US")} rows`]));
      hit.addEventListener("pointerleave", () => tip.hide());
      root.append(hit);
    });
    const ends = [[margin.left, "start", bins[0].low], [width - margin.right, "end", bins[bins.length - 1].high]];
    for (const [x, anchor, value] of ends) {
      root.append(svg("text", { x, y: height - 8, class: "tick", "text-anchor": anchor, text: compact(value) }));
    }
  }

  return { compact, histogram, line, toNumber };
})();
