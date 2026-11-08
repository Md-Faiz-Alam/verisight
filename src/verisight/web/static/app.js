"use strict";

// All data from files and the model is inserted with textContent, never as HTML.
const $ = (id) => document.getElementById(id);

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const state = {
  config: null,
  dataset: null,
  demo: false,
  dashboard: null,
  relation: null,
  filters: [],
  charts: [],
  dashboardRequest: 0,
};

const DEMO_QUESTIONS = [
  "How many orders were shipped?",
  "What is the total amount of orders placed by customers in the NA region?",
  "How many customers have never placed an order?",
  "What was the total amount of orders placed in March 2025?",
  "How many days passed between the first and the last order date?",
];

const ISSUE_LABELS = {
  missing_values: "Missing values",
  missing_value_markers: "Missing-value markers",
  formatted_numbers: "Formatted numbers",
  label_variants: "Label variants",
  trimmed_column_name: "Padded column name",
  named_blank_column: "Column without a header",
  total_row: "Rows that hold totals",
  high_cardinality: "Mostly unique values",
  constant_column: "Single repeated value",
  duplicate_rows: "Duplicate rows",
};

// Load-time clean-ups first: they explain how messy values were read.
const ISSUE_ORDER = {
  total_row: 0,
  label_variants: 0,
  missing_value_markers: 1,
  formatted_numbers: 2,
  trimmed_column_name: 3,
  named_blank_column: 3,
};
const SEVERITY_ORDER = { error: 0, warning: 1, info: 2 };
const FINDINGS_SHOWN = 5;

/* ---------- theme ---------- */

function storedTheme() {
  try { return localStorage.getItem("verisight-theme"); } catch { return null; }
}

function applyTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme;
}

function toggleTheme() {
  const current = document.documentElement.dataset.theme
    || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = current === "dark" ? "light" : "dark";
  applyTheme(next);
  try { localStorage.setItem("verisight-theme", next); } catch { /* private mode */ }
}

/* ---------- API ---------- */

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error("Could not reach the VeriSight server. Check your connection.");
  }
  if (response.status === 204) return null;
  let body = null;
  try { body = await response.json(); } catch { /* non-JSON error page */ }
  if (!response.ok) {
    const detail = body && (body.message ? body : body.detail);
    const message = detail && typeof detail.message === "string"
      ? detail.message
      : `The request failed (HTTP ${response.status}).`;
    const error = new Error(message);
    error.code = detail && detail.code;
    throw error;
  }
  return body;
}

/* ---------- formatting ---------- */

// Numbers are shown exactly as the server sent them: digits are grouped, never
// rounded. JSON numbers are safe integers or doubles, which round-trip exactly;
// exact decimals and integers beyond 2^53 arrive as decimal strings.
const PLAIN_DECIMAL = /^([+-]?)(\d+)(\.\d+)?$/;

function exactNumber(value) {
  if (value === null || value === undefined) return "";
  const text = String(value);
  const match = PLAIN_DECIMAL.exec(text);
  if (!match) return text;
  const [, sign, whole, fraction = ""] = match;
  if (whole.length > 1 && whole.startsWith("0")) return text;
  return `${sign}${BigInt(whole).toLocaleString("en-US")}${fraction}`;
}

function formatCell(value) {
  if (value === null || value === undefined) return "∅";
  // Text cells such as "00123" are never reformatted.
  if (typeof value === "number") return exactNumber(value);
  return String(value);
}

function percent(ratio) {
  if (typeof ratio !== "number") return "";
  return ratio > 0 && ratio < 0.001 ? "<0.1%" : `${(ratio * 100).toFixed(ratio < 0.1 ? 1 : 0)}%`;
}

const SQL_KEYWORDS = new Set((
  "select distinct from where and or not in is null as join left right inner outer full on group by order having " +
  "limit offset union all with case when then else end between like ilike count sum avg min max cast date timestamp " +
  "lower upper trim coalesce nullif over partition desc asc exists interval extract round strftime date_diff"
).split(" "));

function highlightSql(sql) {
  const pre = h("pre");
  const pattern = /('(?:[^']|'')*')|("(?:[^"]|"")*")|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)|(\s+|[^\sA-Za-z0-9_'"]+)/g;
  let match;
  while ((match = pattern.exec(sql)) !== null) {
    const [token, single, , number, word] = match;
    if (single) pre.append(h("span", { class: "str", text: token }));
    else if (number) pre.append(h("span", { class: "num", text: token }));
    else if (word && SQL_KEYWORDS.has(word.toLowerCase())) pre.append(h("span", { class: "kw", text: token }));
    else pre.append(document.createTextNode(token));
  }
  return pre;
}

function codeBlock(sql) {
  const copy = h("button", { class: "copy", type: "button", text: "Copy" });
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(sql);
      copy.textContent = "Copied";
    } catch {
      copy.textContent = "Select and copy";
    }
    setTimeout(() => { copy.textContent = "Copy"; }, 1500);
  });
  return h("div", { class: "code" }, highlightSql(sql), copy);
}

/* ---------- dataset ---------- */

function columnRange(profile) {
  if (!profile) return "";
  if (profile.datetime_statistics) {
    const s = profile.datetime_statistics;
    return `${String(s.earliest).slice(0, 10)} → ${String(s.latest).slice(0, 10)}`;
  }
  if (profile.numeric_statistics) {
    const s = profile.numeric_statistics;
    return `${exactNumber(s.minimum)} → ${exactNumber(s.maximum)}`;
  }
  if (typeof profile.distinct_count === "number") return `${profile.distinct_count} distinct`;
  return "";
}

function renderTables(profile) {
  const container = $("tables");
  container.replaceChildren();
  const profiles = new Map((profile.profiles.tables || []).map((t) => [t.relation_name, t]));
  for (const table of profile.schema.tables) {
    const columnProfiles = new Map(
      ((profiles.get(table.relation_name) || {}).columns || []).map((c) => [c.name, c]),
    );
    const rows = table.columns.map((column) => {
      const info = columnProfiles.get(column.name);
      const missing = info && info.missing_count
        ? h("div", { class: "missing", text: `${info.missing_count} missing (${percent(info.missing_ratio)})` })
        : null;
      return h("tr", {},
        h("td", {}, column.name, h("div", { class: "type", text: column.logical_type })),
        h("td", {}, h("div", { text: columnRange(info) }), missing),
      );
    });
    container.append(h("details", { class: "table-card", open: profile.schema.tables.length === 1 },
      h("summary", {},
        h("b", { text: table.relation_name }),
        h("span", { text: `${table.row_count.toLocaleString()} rows · ${table.column_count} columns` })),
      h("table", { class: "columns" }, h("tbody", {}, rows)),
    ));
  }
}

function renderFindings(findings) {
  const list = $("findings");
  list.replaceChildren();
  const rank = (f) => (ISSUE_ORDER[f.issue_type] ?? 4) * 10 + (SEVERITY_ORDER[f.severity] ?? 3);
  const relevant = findings
    .filter((f) => f.issue_type !== "high_cardinality")
    .sort((a, b) => rank(a) - rank(b));
  $("finding-count").textContent = String(relevant.length);
  if (!relevant.length) {
    list.append(h("li", { class: "muted small", text: "No data-quality issues found." }));
    return;
  }
  const more = $("more-findings");
  more.hidden = relevant.length <= FINDINGS_SHOWN;
  more.textContent = `Show all ${relevant.length} findings`;
  relevant.forEach((finding, position) => {
    const where = finding.column_name
      ? `${finding.relation_name}.${finding.column_name}`
      : finding.relation_name || "dataset";
    const count = typeof finding.affected_count === "number"
      ? `${finding.affected_count.toLocaleString()}${finding.affected_ratio !== null && finding.affected_ratio !== undefined ? ` · ${percent(finding.affected_ratio)}` : ""}`
      : "";
    const examples = finding.evidence && Array.isArray(finding.evidence.examples)
      ? h("div", { class: "examples" }, finding.evidence.examples.map((e) => h("code", { text: e })))
      : null;
    list.append(h("li", { class: `finding ${finding.severity}`, hidden: position >= FINDINGS_SHOWN },
      h("div", { class: "finding-head" }, h("b", { text: where }), h("span", { text: count })),
      h("p", {}, h("strong", { text: `${ISSUE_LABELS[finding.issue_type] || finding.issue_type}. ` }), finding.message),
      examples,
    ));
  });
}

function showAllFindings() {
  for (const item of $("findings").children) item.hidden = false;
  $("more-findings").hidden = true;
}

function renderExamples(profile, computed) {
  const container = $("examples");
  container.replaceChildren();
  for (const question of state.demo ? DEMO_QUESTIONS : computed) {
    container.append(h("button", {
      class: "chip",
      type: "button",
      text: question,
      onclick: () => { $("question").value = question; $("question").focus(); },
    }));
  }
}

/* ---------- views ---------- */

const VIEWS = ["overview", "ask", "data"];

function selectView(name, focusTab = false) {
  for (const view of VIEWS) {
    const active = view === name;
    const tab = $(`tab-${view}`);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    $(`view-${view}`).hidden = !active;
    if (active && focusTab) tab.focus();
  }
  // A hidden container has no width, so charts are drawn once it is visible.
  if (name === "overview" && state.dashboard) drawCharts();
}

function moveTab(event) {
  const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
  if (!step) return;
  event.preventDefault();
  const current = VIEWS.findIndex((view) => $(`tab-${view}`).getAttribute("aria-selected") === "true");
  selectView(VIEWS[(current + step + VIEWS.length) % VIEWS.length], true);
}

/* ---------- dashboard ---------- */

const prefersStill = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

function countUp(node, value) {
  const target = VSCharts.toNumber(value);
  const finish = () => { node.textContent = VSCharts.compact(value); };
  if (target === null || prefersStill()) { finish(); return; }
  const started = performance.now();
  const tick = (now) => {
    const progress = Math.min(1, (now - started) / 450);
    if (progress === 1 || !node.isConnected) { finish(); return; }
    node.textContent = VSCharts.compact(target * (1 - (1 - progress) ** 3));
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function dataTable(columns, rows) {
  return h("div", { class: "data-table-wrap" },
    h("table", { class: "result" },
      h("thead", {}, h("tr", {}, columns.map((c) => h("th", { text: c })))),
      h("tbody", {}, rows.map((row) => h("tr", {}, row.map((cell) => h("td", { text: formatCell(cell) })))))));
}

// One disclosure row per card, so the query and the values are always reachable.
function cardTools(sql, table) {
  const panel = h("div", { class: "tool-panel", hidden: true });
  const buttons = [];
  const open = (button, make) => {
    const showing = button.getAttribute("aria-expanded") === "true";
    for (const other of buttons) other.setAttribute("aria-expanded", "false");
    panel.hidden = showing;
    if (!showing) {
      button.setAttribute("aria-expanded", "true");
      panel.replaceChildren(make());
    }
  };
  const add = (text, make) => {
    const button = h("button", { class: "tool", type: "button", text, "aria-expanded": "false", onclick: () => open(button, make) });
    buttons.push(button);
  };
  if (table) add("Table", table);
  add("SQL", () => codeBlock(sql));
  return [h("div", { class: "card-tools" }, buttons), panel];
}

function card(size, title, subtitle, body, sql, table) {
  return h("article", { class: `card ${size}` },
    h("h3", { class: "card-title", text: title }),
    subtitle ? h("p", { class: "card-sub", text: subtitle }) : null,
    h("div", { class: "card-body" }, body),
    ...cardTools(sql, table));
}

function kpiRow(kpis) {
  return h("section", { class: "kpi-row", "aria-label": "Key figures" }, kpis.map((kpi) => {
    const value = h("p", { class: "kpi-value", title: formatCell(kpi.value) });
    countUp(value, kpi.value);
    return h("div", { class: "kpi" },
      h("p", { class: "kpi-label", text: kpi.label }),
      value,
      ...cardTools(kpi.sql, null));
  }));
}

function activeFilter(column) {
  return state.filters.find((f) => f.column === column);
}

function toggleFilter(column, key, label) {
  const same = activeFilter(column)?.value === key;
  state.filters = state.filters.filter((f) => f.column !== column);
  if (!same) state.filters.push({ column, value: key, label });
  loadDashboard();
}

function breakdownCard(item) {
  const values = item.bars.map((bar) => VSCharts.toNumber(bar.value) ?? 0);
  const widest = Math.max(...values.map(Math.abs), Number.MIN_VALUE);
  const selected = activeFilter(item.column);
  const rows = item.bars.map((bar, index) => {
    const fill = h("span", { class: "bar-fill" });
    fill.style.width = `${(Math.abs(values[index]) / widest) * 100}%`;
    const pressed = selected?.value === bar.key;
    return h("button", {
      class: "bar-row",
      type: "button",
      "aria-pressed": String(pressed),
      title: `${bar.label}: ${formatCell(bar.value)} from ${bar.rows.toLocaleString("en-US")} rows. Select to filter.`,
      onclick: () => toggleFilter(item.column, bar.key, bar.label),
    },
      h("span", { class: "bar-label", text: bar.label }),
      h("span", { class: "bar-track" }, fill),
      h("span", { class: "bar-value", text: VSCharts.compact(bar.value) }));
  });
  const shown = item.categories > item.bars.length
    ? `Top ${item.bars.length} of ${item.categories}`
    : `${item.categories} categories`;
  return card("", item.title, `${shown} · select one to filter`,
    h("div", { class: `bars${selected ? " has-selection" : ""}` }, rows), item.sql,
    () => dataTable(["Category", "Value", "Rows"], item.bars.map((b) => [b.label, b.value, b.rows])));
}

function drawCharts() {
  for (const { node, draw } of state.charts) {
    const width = node.clientWidth;
    if (width && width !== node.dataset.drawn) {
      node.dataset.drawn = width;
      draw(node);
    }
  }
}

function addChart(draw) {
  const node = h("div", { class: "chart" });
  state.charts.push({ node, draw });
  return node;
}

function renderRelations(data) {
  const box = $("relations");
  box.hidden = data.relations.length < 2;
  box.replaceChildren(h("span", { text: "Table" }), ...data.relations.map((relation) => h("button", {
    class: "pill-button",
    type: "button",
    "aria-pressed": String(relation.name === data.relation),
    text: relation.name,
    onclick: () => {
      if (relation.name === state.relation) return;
      state.relation = relation.name;
      state.filters = [];
      loadDashboard();
    },
  })));
}

function renderFilters() {
  const box = $("filters");
  box.hidden = !state.filters.length;
  box.replaceChildren(
    h("span", { text: "Showing only" }),
    ...state.filters.map((filter) => h("button", {
      class: "filter-chip",
      type: "button",
      "aria-label": `Remove filter ${filter.column} ${filter.label}`,
      onclick: () => toggleFilter(filter.column, filter.value, filter.label),
    }, filter.column.replace(/_/g, " "), " is ", h("b", { text: filter.label }), h("i", { "aria-hidden": "true", text: "×" }))),
    h("button", { class: "link-button", type: "button", text: "Clear all", onclick: () => { state.filters = []; loadDashboard(); } }),
  );
}

function renderDomain(data) {
  const { domain } = data;
  $("domain-name").textContent = domain.label;
  const names = state.dataset.files.map((f) => f.name).join(", ");
  const why = domain.matched.length ? ` · recognised from ${domain.matched.join(", ")}` : "";
  $("domain-detail").textContent = `${domain.focus} · ${names}${why}`;
}

function renderDashboard(data) {
  state.dashboard = data;
  state.relation = data.relation;
  state.charts = [];
  renderDomain(data);
  renderRelations(data);
  renderFilters();
  const note = $("totals-note");
  note.hidden = !data.excluded_totals.length;
  note.textContent = `Rows that hold totals of other rows are left out of these charts so nothing is counted twice: ${data.excluded_totals.join("; ")}.`;

  const parts = [];
  if (data.kpis.length) parts.push(kpiRow(data.kpis));
  if (data.trend) {
    const { trend } = data;
    const body = addChart((node) => VSCharts.line(node, { points: trend.points, label: trend.title }));
    parts.push(card(data.insights.length ? "wide" : "full", trend.title, `${trend.points.length} ${trend.grain}s`, body, trend.sql,
      () => dataTable(["Period", "Value", "Rows"], trend.points.map((p) => [p.period, p.value, p.rows]))));
  }
  if (data.insights.length) {
    const list = h("ul", { class: "insights" }, data.insights.map((insight) => h("li", {},
      h("p", { text: insight.text }),
      ...cardTools(insight.sql, null))));
    parts.push(h("article", { class: `card ${data.trend ? "side" : "full"}` },
      h("h3", { class: "card-title", text: "What stands out" }),
      h("p", { class: "card-sub", text: "Calculated from the data, not written by AI" }),
      list));
  }
  parts.push(...data.breakdowns.map(breakdownCard));
  for (const spread of data.histograms) {
    const body = addChart((node) => VSCharts.histogram(node, { bins: spread.bins, label: spread.title }));
    parts.push(card("", spread.title, `Number of rows in ${spread.bins.length} equal ranges`, body, spread.sql,
      () => dataTable(["From", "To", "Rows"], spread.bins.map((b) => [b.low, b.high, b.rows]))));
  }
  const dashboard = $("dashboard");
  dashboard.replaceChildren(...parts);
  drawCharts();
  renderExamples(state.dataset.profile, data.suggestions);
}

function dashboardSkeleton() {
  $("dashboard").replaceChildren(
    h("div", { class: "skeleton-card kpi-skeleton" }),
    ...[0, 1, 2, 3].map(() => h("div", { class: "skeleton-card" })),
  );
}

async function loadDashboard() {
  const request = ++state.dashboardRequest;
  const dashboard = $("dashboard");
  const error = $("dashboard-error");
  error.hidden = true;
  if (state.dashboard) dashboard.classList.add("updating");
  else dashboardSkeleton();
  try {
    const data = await api(`/api/datasets/${state.dataset.dataset_id}/dashboard`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        relation: state.relation,
        filters: state.filters.map(({ column, value }) => ({ column, value })),
      }),
    });
    // A slower earlier response must not replace a newer selection.
    if (request === state.dashboardRequest) renderDashboard(data);
  } catch (err) {
    if (request !== state.dashboardRequest) return;
    if (err.code === "dataset_not_found") { removeDataset(); return; }
    error.textContent = err.message;
    error.hidden = false;
    if (!state.dashboard) dashboard.replaceChildren();
  } finally {
    if (request === state.dashboardRequest) dashboard.classList.remove("updating");
  }
}

function showDataset(data) {
  state.dataset = data;
  state.dashboard = null;
  state.relation = null;
  state.filters = [];
  state.charts = [];
  $("hero").hidden = true;
  $("workspace").hidden = false;
  const names = data.files.map((f) => f.name).join(", ");
  $("domain-name").textContent = "Reading your data";
  $("domain-detail").textContent = names;
  $("dataset-expiry").textContent = `${names} · deleted automatically after ${Math.round(data.expires_in_seconds / 60)} minutes`;
  renderTables(data.profile);
  renderFindings(data.profile.quality_findings);
  renderExamples(data.profile, []);
  $("answers").replaceChildren();
  selectView("overview");
  loadDashboard();
}

async function upload(fileList, demo = false) {
  const zone = $("dropzone");
  const error = $("upload-error");
  error.hidden = true;
  zone.classList.add("busy");
  $("demo-button").disabled = true;
  try {
    let data;
    if (demo) {
      data = await api("/api/datasets/demo", { method: "POST" });
    } else {
      const form = new FormData();
      for (const file of fileList) form.append("files", file);
      data = await api("/api/datasets", { method: "POST", body: form });
    }
    state.demo = demo;
    showDataset(data);
  } catch (err) {
    error.textContent = err.message;
    error.hidden = false;
  } finally {
    zone.classList.remove("busy");
    $("demo-button").disabled = false;
    $("file-input").value = "";
  }
}

async function removeDataset() {
  if (state.dataset) {
    try { await api(`/api/datasets/${state.dataset.dataset_id}`, { method: "DELETE" }); } catch { /* already gone */ }
  }
  state.dataset = null;
  state.dashboard = null;
  state.dashboardRequest += 1;
  $("workspace").hidden = true;
  $("hero").hidden = false;
}

/* ---------- answers ---------- */

const FAILURE_TEXT = {
  provider_unavailable: "Gemini was busy or unavailable while answering. Wait a minute and ask again.",
  provider_error: "Gemini returned an error while answering. Try again or rephrase the question.",
  prompt_budget_exceeded: "This dataset is too large to describe to the model in one request. Try fewer or narrower files.",
  synthesis_error: "The model's answer could not be matched to the SQL results, so it is not presented as verified.",
};

const CROSS_CHECK_FAILURE = {
  multiple_claims: "This answer has several numbers, and the independent second check covers one number at a time, so it is not shown as verified.",
  not_a_single_number: "The number matches its SQL, but a second query did not return one number to compare it with, so it is not shown as verified.",
  provider_failed: "The number matches its SQL, but Gemini was unavailable for the independent second check, so it is not shown as verified.",
  query_failed: "The number matches its SQL, but the independent second query could not be run, so it is not shown as verified.",
  time_budget_exhausted: "The number matches its SQL, but time ran out before the independent second check finished, so it is not shown as verified.",
};

function crossCheckFailure(check) {
  if (check.status === "disagreed") {
    return `A second query, written without seeing the first, returned ${exactNumber(check.independent_value)} instead of ${exactNumber(check.primary_value)}. Compare both queries below before using either number.`;
  }
  return CROSS_CHECK_FAILURE[check.reason];
}

function failureText(answer) {
  const failure = answer.failure || {};
  if (failure.kind && FAILURE_TEXT[failure.kind]) return FAILURE_TEXT[failure.kind];
  if (answer.status === "incomplete") {
    return "VeriSight could not finish with a number it can verify, so it does not present one.";
  }
  if (answer.assessment && Array.isArray(answer.assessment.violations) && answer.assessment.violations.length) {
    return "The answer did not include a verified number of the requested kind. Try “Anything” or rephrase the question.";
  }
  if (answer.cross_check) return crossCheckFailure(answer.cross_check);
  return "At least one number in the answer does not match the SQL result, so it is not shown as verified.";
}

function citedCells(claims) {
  const cited = new Set();
  for (const item of claims) {
    for (const ref of [item.claim.left, item.claim.right]) {
      if (ref) cited.add(`${ref.observation_index}:${ref.row_index}:${ref.column}`);
    }
  }
  return cited;
}

function resultTable(step, index, cited) {
  if (!step.columns.length) return null;
  const head = h("tr", {}, step.columns.map((c) => h("th", { text: c })));
  const body = step.rows.map((row, r) => h("tr", {}, row.map((cell, c) => h("td", {
    class: cited.has(`${index}:${r}:${step.columns[c]}`) ? "cited" : null,
    text: formatCell(cell),
  }))));
  return h("div", { class: "result-wrap" }, h("table", { class: "result" }, h("thead", {}, head), h("tbody", {}, body)));
}

function claimLine(item) {
  const { claim, verification } = item;
  const ok = verification.status === "supported" || verification.status === "supported_rounded";
  const cell = (ref) => h("code", { text: ref.column });
  const evidence = claim.operation === "difference"
    ? [cell(claim.left), " − ", cell(claim.right)]
    : [cell(claim.left)];
  return h("li", {},
    h("span", { class: `mark ${ok ? "ok" : "bad"}`, text: ok ? "✓" : "✕" }),
    h("span", {}, `${claim.operation} `, h("code", { text: String(claim.expected) })),
    h("span", { text: ok ? "matches result cell" : "does not match result cell" }),
    h("span", {}, ...evidence, verification.actual !== null ? ` = ${verification.actual}` : ""),
  );
}

function headline(item) {
  // The verifier's own decimal string, so every digit can be traced to the cell.
  const { claim, verification } = item;
  const exact = verification.status === "supported";
  const shown = exact ? verification.actual : claim.expected;
  const note = exact
    ? "equals the SQL result cell exactly"
    : `rounded from the SQL result ${exactNumber(verification.actual)}`;
  return h("div", { class: "headline" },
    h("span", { class: "big-number", title: String(shown), text: exactNumber(shown) }),
    h("span", { class: "verified-note", text: note }));
}

function renderAnswer(card, question, answer) {
  const verified = answer.outcome === "verified";
  const pill = verified
    ? h("span", { class: "pill ok", text: "✓ Verified" })
    : h("span", { class: "pill warn", text: "⚠ Not verified" });
  const claims = answer.claims || [];
  const body = h("div", { class: "answer-body" });

  if (verified && claims.length === 1) {
    body.append(headline(claims[0]));
  }
  if (verified) {
    body.append(h("p", { class: "verified-note", text: "Cross-checked: a second query, written without seeing the first, returned the same number." }));
  }
  if (answer.answer) {
    body.append(h("p", { class: verified ? "answer-text" : "answer-text muted", text: answer.answer }));
  }
  if (!verified) body.append(h("div", { class: "notice warn", text: failureText(answer) }));
  if (answer.review_required) {
    body.append(h("div", { class: "notice warn", text: "Review suggested: the rows or counting unit used by the SQL may differ from what the question means. Check the SQL below." }));
  }
  if (claims.length) body.append(h("ul", { class: "claims" }, claims.map(claimLine)));

  if (answer.steps && answer.steps.length) {
    const cited = citedCells(claims);
    body.append(h("h4", { class: "steps-title", text: `SQL it ran (${answer.steps.length})` }));
    answer.steps.forEach((step, index) => {
      body.append(h("div", { class: "step" },
        answer.steps.length > 1 ? h("p", { class: "step-question", text: `${index + 1}. ${step.question}` }) : null,
        codeBlock(step.sql),
        resultTable(step, index, cited)));
    });
  }
  if (answer.cross_check && answer.cross_check.sql) {
    body.append(h("h4", { class: "steps-title", text: "Independent second query" }));
    body.append(h("div", { class: "step" }, codeBlock(answer.cross_check.sql)));
  }
  const calls = (answer.model_calls || []).length;
  const meta = [`${answer.elapsed_seconds}s`];
  if (calls) meta.push(`${calls} model call${calls === 1 ? "" : "s"}`);
  if (answer.recovery) meta.push("recovery query used");
  body.append(h("div", { class: "meta" }, meta.map((m) => h("span", { text: m }))));

  card.replaceChildren(
    h("div", { class: "answer-head" }, h("p", { class: "answer-question", text: question }), pill),
    body,
  );
}

function renderError(card, question, message) {
  card.replaceChildren(
    h("div", { class: "answer-head" },
      h("p", { class: "answer-question", text: question }),
      h("span", { class: "pill bad", text: "✕ Not answered" })),
    h("div", { class: "answer-body" }, h("div", { class: "notice bad", text: message })),
  );
}

function pendingCard(question) {
  const timer = h("span", { text: "0s" });
  const card = h("article", { class: "panel answer" },
    h("div", { class: "answer-head" },
      h("p", { class: "answer-question", text: question }),
      h("span", { class: "pill pending" }, h("span", { class: "spinner" }), "Working ", timer)),
    h("div", { class: "answer-body" },
      h("p", { class: "muted small", text: "Planning SQL, running it on your data, then checking every number. This usually takes 10–60 seconds." }),
      h("div", { class: "skeleton" }), h("div", { class: "skeleton short" })));
  const started = Date.now();
  const interval = setInterval(() => { timer.textContent = `${Math.round((Date.now() - started) / 1000)}s`; }, 1000);
  return { card, stop: () => clearInterval(interval) };
}

async function ask(event) {
  event.preventDefault();
  const question = $("question").value.trim();
  const error = $("ask-error");
  error.hidden = true;
  if (!question || !state.dataset) return;
  if (!$("consent").checked) {
    error.textContent = "Tick the box to allow sending the schema and sample values to Gemini.";
    error.hidden = false;
    return;
  }
  const apiKey = $("api-key").value.trim();
  if (!state.config.server_key && !apiKey) {
    error.textContent = "Add your Gemini API key to ask questions.";
    error.hidden = false;
    $("api-key").focus();
    return;
  }
  const answerType = document.querySelector('input[name="answer-type"]:checked').value;
  const { card, stop } = pendingCard(question);
  $("answers").prepend(card);
  const button = $("ask-button");
  button.disabled = true;
  try {
    const answer = await api(`/api/datasets/${state.dataset.dataset_id}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, answer_type: answerType, consent: true, api_key: apiKey || null }),
    });
    renderAnswer(card, question, answer);
  } catch (err) {
    renderError(card, question, err.message);
    if (err.code === "dataset_not_found") removeDataset();
  } finally {
    stop();
    button.disabled = false;
  }
}

/* ---------- start ---------- */

async function start() {
  applyTheme(storedTheme());
  $("theme-toggle").addEventListener("click", toggleTheme);
  const zone = $("dropzone");
  $("file-input").addEventListener("change", (e) => { if (e.target.files.length) upload(e.target.files); });
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("dragging"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragging"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("dragging");
    if (e.dataTransfer.files.length) upload(e.dataTransfer.files);
  });
  $("demo-button").addEventListener("click", () => upload(null, true));
  $("remove-button").addEventListener("click", removeDataset);
  $("more-findings").addEventListener("click", showAllFindings);
  $("ask-form").addEventListener("submit", ask);
  for (const view of VIEWS) {
    $(`tab-${view}`).addEventListener("click", () => selectView(view));
    $(`tab-${view}`).addEventListener("keydown", moveTab);
  }
  new ResizeObserver(() => drawCharts()).observe($("view-overview"));
  $("question").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("ask-form").requestSubmit(); }
  });
  try {
    state.config = await api("/api/config");
    $("key-field").hidden = state.config.server_key;
    $("dropzone-hint").textContent =
      `CSV, JSON, XLSX or XLS · up to ${state.config.max_files} files, ${state.config.max_upload_mb} MB each · files can be joined`;
  } catch (err) {
    state.config = { server_key: false };
    $("key-field").hidden = false;
    $("upload-error").textContent = err.message;
    $("upload-error").hidden = false;
  }
}

applyTheme(storedTheme());
document.addEventListener("DOMContentLoaded", start);
