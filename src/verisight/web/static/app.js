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

const state = { config: null, dataset: null, demo: false };

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
  high_cardinality: "Mostly unique values",
  constant_column: "Single repeated value",
  duplicate_rows: "Duplicate rows",
};

// Load-time clean-ups first: they explain how messy values were read.
const ISSUE_ORDER = {
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

function suggestions(profile) {
  if (state.demo) return DEMO_QUESTIONS;
  const table = profile.schema.tables[0];
  const numeric = table.columns.find((c) => ["integer", "float", "decimal"].includes(c.logical_type) && !/id$/i.test(c.name));
  const label = table.columns.find((c) => c.logical_type === "string");
  const list = [`How many rows does ${table.relation_name} have?`];
  if (numeric) list.push(`What is the average ${numeric.name}?`);
  if (numeric && label) list.push(`Which ${label.name} has the highest total ${numeric.name}?`);
  return list;
}

function renderExamples(profile) {
  const container = $("examples");
  container.replaceChildren();
  for (const question of suggestions(profile)) {
    container.append(h("button", {
      class: "chip",
      type: "button",
      text: question,
      onclick: () => { $("question").value = question; $("question").focus(); },
    }));
  }
}

function showDataset(data) {
  state.dataset = data;
  $("hero").hidden = true;
  $("workspace").hidden = false;
  const names = data.files.map((f) => f.name).join(", ");
  $("dataset-expiry").textContent = `${names} · deleted automatically after ${Math.round(data.expires_in_seconds / 60)} minutes`;
  renderTables(data.profile);
  renderFindings(data.profile.quality_findings);
  renderExamples(data.profile);
  $("answers").replaceChildren();
  $("question").focus();
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

function failureText(answer) {
  const failure = answer.failure || {};
  if (failure.kind && FAILURE_TEXT[failure.kind]) return FAILURE_TEXT[failure.kind];
  if (answer.status === "incomplete") {
    return "VeriSight could not finish with a number it can verify, so it does not present one.";
  }
  if (answer.assessment && Array.isArray(answer.assessment.violations) && answer.assessment.violations.length) {
    return "The answer did not include a verified number of the requested kind. Try “Anything” or rephrase the question.";
  }
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
