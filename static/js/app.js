/* ═══════════════════════════════════════════════════════════════════════════
   Bids Agent — Frontend Application
   ═══════════════════════════════════════════════════════════════════════════ */

"use strict";

// ─── Constants ────────────────────────────────────────────────────────────────
const DESC_PREVIEW_LENGTH = 120;

// ─── State ────────────────────────────────────────────────────────────────────
const state = {
  selectedKeywords: new Set(),
  currentSearchId: null,
  currentResults: [],
  selectedResultIds: new Set(),
  currentMapping: null,   // active column mapping (list of {excel_col, result_field})
  savedMappings: [],
  availableFields: [],
  availableSources: [],
};

// ─── API helpers ──────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const res = await fetch("/api" + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `HTTP ${res.status} for ${path}`);
  }
  return res.json();
}

async function apiPost(path, body) {
  return api(path, { method: "POST", body: JSON.stringify(body) });
}

async function apiDelete(path) {
  return api(path, { method: "DELETE" });
}

// ─── Panel Navigation ─────────────────────────────────────────────────────────
function showPanel(name) {
  document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
  document.getElementById(`panel-${name}`).classList.add("active");
  document.querySelector(`.nav-btn[data-panel="${name}"]`).classList.add("active");
  if (name === "history") loadHistory();
  if (name === "results") loadResultsPanel();
  if (name === "mappings") loadMappingsPanel();
}

document.querySelectorAll(".nav-btn").forEach(btn => {
  btn.addEventListener("click", () => showPanel(btn.dataset.panel));
});

// ─── Toast ────────────────────────────────────────────────────────────────────
let toastTimer;
function toast(msg, type = "info") {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = `toast ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 3500);
}

// ─── Keyword Management ───────────────────────────────────────────────────────
async function initKeywords() {
  let presets = [];
  try { presets = await api("/keywords/defaults"); } catch { /* ignore */ }

  const container = document.getElementById("keyword-presets");
  presets.forEach(kw => {
    const btn = document.createElement("button");
    btn.className = "keyword-preset";
    btn.textContent = kw;
    btn.addEventListener("click", () => togglePresetKeyword(kw, btn));
    container.appendChild(btn);
  });
}

function togglePresetKeyword(kw, btn) {
  if (state.selectedKeywords.has(kw)) {
    state.selectedKeywords.delete(kw);
    btn.classList.remove("selected");
  } else {
    state.selectedKeywords.add(kw);
    btn.classList.add("selected");
  }
  renderSelectedKeywords();
}

function addCustomKeyword() {
  const input = document.getElementById("keyword-input");
  const kw = input.value.trim();
  if (!kw) return;
  state.selectedKeywords.add(kw);
  input.value = "";
  renderSelectedKeywords();
}

function renderSelectedKeywords() {
  const container = document.getElementById("selected-keywords");
  container.innerHTML = "";
  state.selectedKeywords.forEach(kw => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.innerHTML = `${escHtml(kw)} <button class="chip-remove" title="Remove">✕</button>`;
    chip.querySelector(".chip-remove").addEventListener("click", () => {
      state.selectedKeywords.delete(kw);
      // Un-highlight preset button if it exists
      document.querySelectorAll(".keyword-preset").forEach(btn => {
        if (btn.textContent === kw) btn.classList.remove("selected");
      });
      renderSelectedKeywords();
    });
    container.appendChild(chip);
  });
}

document.getElementById("btn-add-keyword").addEventListener("click", addCustomKeyword);
document.getElementById("keyword-input").addEventListener("keydown", e => {
  if (e.key === "Enter") addCustomKeyword();
});

// ─── Sources ──────────────────────────────────────────────────────────────────
async function initSources() {
  try { state.availableSources = await api("/sources"); } catch { return; }
  const container = document.getElementById("sources-list");
  state.availableSources.forEach(src => {
    const label = document.createElement("label");
    label.innerHTML = `<input type="checkbox" value="${src.key}" checked /> ${escHtml(src.label)}`;
    container.appendChild(label);
  });
}

function getSelectedSources() {
  return [...document.querySelectorAll("#sources-list input:checked")].map(i => i.value);
}

// ─── Search Types ─────────────────────────────────────────────────────────────
function getSelectedSearchTypes() {
  return [...document.querySelectorAll("#search-types input:checked")].map(i => i.value);
}

// ─── Available Fields ─────────────────────────────────────────────────────────
async function initFields() {
  try { state.availableFields = await api("/fields"); } catch { /* ignore */ }
}

// ─── Run Search ───────────────────────────────────────────────────────────────
document.getElementById("btn-search").addEventListener("click", runSearch);

async function runSearch() {
  const keywords = [...state.selectedKeywords].join(" ").trim();
  if (!keywords) {
    toast("Please select or type at least one keyword.", "error");
    return;
  }

  const searchTypes = getSelectedSearchTypes();
  if (!searchTypes.length) {
    toast("Please select at least one document type.", "error");
    return;
  }

  const sources = getSelectedSources();
  if (!sources.length) {
    toast("Please select at least one data source.", "error");
    return;
  }

  const maxResults = parseInt(document.getElementById("max-results").value, 10) || 25;
  const btn = document.getElementById("btn-search");
  const status = document.getElementById("search-status");

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Searching…';
  status.textContent = "Searching, please wait…";
  status.className = "search-status running";

  try {
    const data = await apiPost("/search", { keywords, search_types: searchTypes, sources, max_results: maxResults });
    state.currentSearchId = data.search_id;
    state.currentResults  = data.results || [];

    status.textContent = `✔ Found ${data.count} result(s)`;
    status.className   = "search-status";

    showPreview(state.currentResults);
    toast(`Search complete — ${data.count} result(s) found.`, "success");
  } catch (err) {
    status.textContent = `Error: ${err.message}`;
    status.className   = "search-status error";
    toast("Search failed: " + err.message, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span class="btn-icon">🔍</span> Search';
  }
}

// ─── Preview ──────────────────────────────────────────────────────────────────
function showPreview(results) {
  const wrap = document.getElementById("search-preview");
  document.getElementById("preview-count").textContent = results.length;
  const tableWrap = document.getElementById("preview-table-wrap");
  // Show first 5 results as a simple preview
  tableWrap.innerHTML = buildResultsTable(results.slice(0, 5), { showSelect: false });
  wrap.classList.remove("hidden");
}

document.getElementById("btn-goto-results").addEventListener("click", () => {
  loadResultsPanel();
  showPanel("results");
});

document.getElementById("btn-quick-export").addEventListener("click", () => {
  exportResults(state.currentSearchId, [], state.currentMapping);
});

// ─── Results Panel ────────────────────────────────────────────────────────────
async function loadResultsPanel() {
  const wrap = document.getElementById("results-table-wrap");
  const filter = document.getElementById("results-search-filter");

  // Reload the search filter dropdown
  try {
    const searches = await api("/searches");
    filter.innerHTML = '<option value="">All searches</option>';
    searches.forEach(s => {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.textContent = `#${s.id} — ${s.keywords} (${s.result_count} results, ${s.timestamp.slice(0,10)})`;
      filter.appendChild(opt);
    });
    // Pre-select the current search
    if (state.currentSearchId) filter.value = state.currentSearchId;
  } catch { /* ignore */ }

  await refreshResultsTable();

  // Reload mapping dropdown
  try {
    const mappings = await api("/mappings");
    state.savedMappings = mappings;
    const sel = document.getElementById("mapping-select");
    sel.innerHTML = '<option value="">Default mapping</option>';
    mappings.forEach(m => {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = m.mapping_name;
      sel.appendChild(opt);
    });
  } catch { /* ignore */ }
}

document.getElementById("results-search-filter").addEventListener("change", refreshResultsTable);

async function refreshResultsTable() {
  const wrap = document.getElementById("results-table-wrap");
  const searchId = document.getElementById("results-search-filter").value;

  try {
    let results;
    if (searchId) {
      const data = await api(`/searches/${searchId}`);
      results = data.results;
    } else {
      results = await api("/results");
    }

    state.currentResults = results;
    state.selectedResultIds.clear();

    if (!results.length) {
      wrap.innerHTML = '<p class="empty-state">No results found for this search.</p>';
      return;
    }

    wrap.innerHTML = `<div class="table-wrap">${buildResultsTable(results, { showSelect: true })}</div>`;
    attachTableEvents(wrap);
  } catch (err) {
    wrap.innerHTML = `<p class="empty-state">Error loading results: ${err.message}</p>`;
  }
}

function buildResultsTable(results, { showSelect = false } = {}) {
  const COLS = [
    { key: "title",       label: "Name / Title" },
    { key: "number",      label: "Number" },
    { key: "site",        label: "Site" },
    { key: "description", label: "Description" },
    { key: "city",        label: "City" },
    { key: "state",       label: "State" },
    { key: "company",     label: "Company / Agency" },
    { key: "due_date",    label: "Due Date" },
    { key: "source_name", label: "Source" },
  ];

  let thead = "<thead><tr>";
  if (showSelect) thead += '<th class="select-col"><input type="checkbox" id="select-all" title="Select all" /></th>';
  COLS.forEach(c => { thead += `<th>${c.label}</th>`; });
  thead += "</tr></thead>";

  let tbody = "<tbody>";
  results.forEach(r => {
    tbody += `<tr data-id="${r.id || ""}">`;
    if (showSelect) tbody += `<td class="select-col"><input type="checkbox" class="row-select" data-id="${r.id}" /></td>`;

    COLS.forEach(c => {
      if (c.key === "title" && r.source_url) {
        tbody += `<td><a href="${escHtml(r.source_url)}" target="_blank" rel="noopener">${escHtml(r.title || "")}</a></td>`;
      } else if (c.key === "description") {
        const full = r.description || "";
        const short = full.length > DESC_PREVIEW_LENGTH ? full.slice(0, DESC_PREVIEW_LENGTH) + "…" : full;
        tbody += `<td class="desc-cell">
          <span class="short-desc">${escHtml(short)}</span>
          <span class="full-desc">${escHtml(full)}</span>
          ${full.length > DESC_PREVIEW_LENGTH ? '<a class="toggle-desc" href="#">more</a>' : ""}
        </td>`;
      } else if (c.key === "site") {
        const url = r.source_url || r.site || "";
        const display = r.site || (url ? new URL(url).hostname : "");
        tbody += `<td>${url ? `<a href="${escHtml(url)}" target="_blank" rel="noopener">${escHtml(display)}</a>` : ""}</td>`;
      } else {
        tbody += `<td>${escHtml(r[c.key] || "")}</td>`;
      }
    });

    tbody += "</tr>";
  });
  tbody += "</tbody>";

  return `<table>${thead}${tbody}</table>`;
}

function attachTableEvents(wrap) {
  // Select-all checkbox
  const selectAll = wrap.querySelector("#select-all");
  if (selectAll) {
    selectAll.addEventListener("change", () => {
      wrap.querySelectorAll(".row-select").forEach(cb => {
        cb.checked = selectAll.checked;
        const id = parseInt(cb.dataset.id, 10);
        if (selectAll.checked) state.selectedResultIds.add(id);
        else state.selectedResultIds.delete(id);
      });
    });
  }

  // Individual row checkboxes
  wrap.querySelectorAll(".row-select").forEach(cb => {
    cb.addEventListener("change", () => {
      const id = parseInt(cb.dataset.id, 10);
      if (cb.checked) state.selectedResultIds.add(id);
      else state.selectedResultIds.delete(id);
    });
  });

  // Description expand/collapse
  wrap.querySelectorAll(".toggle-desc").forEach(link => {
    link.addEventListener("click", e => {
      e.preventDefault();
      const cell = link.closest(".desc-cell");
      const expanded = cell.classList.toggle("expanded");
      link.textContent = expanded ? "less" : "more";
    });
  });
}

// ─── Export ───────────────────────────────────────────────────────────────────
document.getElementById("btn-export-selected").addEventListener("click", () => {
  if (!state.selectedResultIds.size) {
    toast("No rows selected. Select rows using the checkboxes.", "error");
    return;
  }
  exportResults(null, [...state.selectedResultIds], state.currentMapping);
});

document.getElementById("btn-export-all").addEventListener("click", () => {
  const searchId = document.getElementById("results-search-filter").value || null;
  exportResults(searchId, [], state.currentMapping);
});

async function exportResults(searchId, resultIds, mapping) {
  try {
    toast("Preparing Excel export…");
    const body = { column_mapping: mapping || undefined };
    if (searchId) body.search_id = parseInt(searchId, 10);
    if (resultIds && resultIds.length) body.result_ids = resultIds;

    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${res.status}`);
    }

    // Trigger file download
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    const cd   = res.headers.get("Content-Disposition") || "";
    const fnMatch = cd.match(/filename="?([^"]+)"?/);
    a.download = fnMatch ? fnMatch[1] : "bids_export.xlsx";
    a.href = url;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast("Excel file downloaded!", "success");
  } catch (err) {
    toast("Export failed: " + err.message, "error");
  }
}

// ─── History Panel ────────────────────────────────────────────────────────────
async function loadHistory() {
  const wrap = document.getElementById("history-table-wrap");
  try {
    const searches = await api("/searches");
    if (!searches.length) {
      wrap.innerHTML = '<p class="empty-state">No searches yet.</p>';
      return;
    }
    let html = `<div class="table-wrap"><table>
      <thead><tr>
        <th>#</th><th>Keywords</th><th>Types</th><th>Sources</th>
        <th>Results</th><th>Date</th><th>Actions</th>
      </tr></thead><tbody>`;
    searches.forEach(s => {
      let types, srcs;
      try { types = JSON.parse(s.search_types || "[]").join(", "); } catch { types = s.search_types || ""; }
      try { srcs  = JSON.parse(s.sources  || "[]").join(", ");  } catch { srcs  = s.sources  || ""; }
      html += `<tr class="history-row">
        <td>${s.id}</td>
        <td>${escHtml(s.keywords)}</td>
        <td>${escHtml(types)}</td>
        <td>${escHtml(srcs)}</td>
        <td>${s.result_count}</td>
        <td>${s.timestamp.slice(0,16).replace("T"," ")}</td>
        <td>
          <button class="btn btn-sm btn-secondary history-load" data-id="${s.id}">Load</button>
          <button class="btn btn-sm btn-success history-export" data-id="${s.id}">Export ⬇</button>
        </td>
      </tr>`;
    });
    html += "</tbody></table></div>";
    wrap.innerHTML = html;

    wrap.querySelectorAll(".history-load").forEach(btn => {
      btn.addEventListener("click", () => {
        document.getElementById("results-search-filter").value = btn.dataset.id;
        showPanel("results");
      });
    });
    wrap.querySelectorAll(".history-export").forEach(btn => {
      btn.addEventListener("click", () => exportResults(btn.dataset.id, [], state.currentMapping));
    });
  } catch (err) {
    wrap.innerHTML = `<p class="empty-state">Error: ${err.message}</p>`;
  }
}

// ─── Mappings Panel ───────────────────────────────────────────────────────────
async function loadMappingsPanel() {
  const wrap = document.getElementById("mappings-list-wrap");
  try {
    const mappings = await api("/mappings");
    state.savedMappings = mappings;
    if (!mappings.length) {
      wrap.innerHTML = '<p class="empty-state">No saved mappings yet. Use the editor to create one.</p>';
      return;
    }
    let html = `<div class="table-wrap"><table>
      <thead><tr><th>#</th><th>Name</th><th>Columns</th><th>Created</th><th>Actions</th></tr></thead><tbody>`;
    mappings.forEach(m => {
      const fields = JSON.parse(m.field_mappings || "[]");
      const colList = fields.map(f => `${f.excel_col}→${f.result_field}`).join(", ");
      html += `<tr>
        <td>${m.id}</td>
        <td>${escHtml(m.mapping_name)}</td>
        <td><small>${escHtml(colList)}</small></td>
        <td>${m.created_at.slice(0,16).replace("T"," ")}</td>
        <td>
          <button class="btn btn-sm btn-secondary mapping-use" data-id="${m.id}">Use</button>
          <button class="btn btn-sm btn-danger mapping-delete" data-id="${m.id}">Delete</button>
        </td>
      </tr>`;
    });
    html += "</tbody></table></div>";
    wrap.innerHTML = html;

    wrap.querySelectorAll(".mapping-use").forEach(btn => {
      btn.addEventListener("click", () => {
        const m = mappings.find(x => x.id == btn.dataset.id);
        if (m) {
          state.currentMapping = JSON.parse(m.field_mappings);
          toast(`Mapping "${m.mapping_name}" activated.`, "success");
        }
      });
    });

    wrap.querySelectorAll(".mapping-delete").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!confirm("Delete this mapping?")) return;
        try {
          await apiDelete(`/mappings/${btn.dataset.id}`);
          toast("Mapping deleted.");
          loadMappingsPanel();
        } catch (err) { toast(err.message, "error"); }
      });
    });
  } catch (err) {
    wrap.innerHTML = `<p class="empty-state">Error: ${err.message}</p>`;
  }
}

document.getElementById("btn-new-mapping").addEventListener("click", openMapperModal);

// ─── Column Mapper Modal ──────────────────────────────────────────────────────
function openMapperModal() {
  buildMapperUI();
  document.getElementById("modal-mapper").classList.remove("hidden");
}

function closeMapperModal() {
  document.getElementById("modal-mapper").classList.add("hidden");
}

document.getElementById("btn-modal-close").addEventListener("click", closeMapperModal);
document.getElementById("modal-backdrop").addEventListener("click", closeMapperModal);

function buildMapperUI() {
  // Available fields
  const fieldsDiv = document.getElementById("mapper-fields");
  fieldsDiv.innerHTML = "";
  state.availableFields.forEach(f => {
    const div = document.createElement("div");
    div.className = "draggable-field";
    div.draggable = true;
    div.dataset.field = f.key;
    div.textContent = f.label;
    div.addEventListener("dragstart", e => {
      e.dataTransfer.setData("text/plain", f.key);
      div.classList.add("dragging");
    });
    div.addEventListener("dragend", () => div.classList.remove("dragging"));
    fieldsDiv.appendChild(div);
  });

  // Current mapping rows
  const mapping = state.currentMapping || getDefaultMapping();
  const colList = document.getElementById("mapper-columns");
  colList.innerHTML = "";
  mapping.forEach(m => addMapperRow(m.excel_col, m.result_field));
}

function getDefaultMapping() {
  return [
    { excel_col: "Name / Title",    result_field: "title" },
    { excel_col: "Number",          result_field: "number" },
    { excel_col: "Site",            result_field: "site" },
    { excel_col: "Description",     result_field: "description" },
    { excel_col: "City",            result_field: "city" },
    { excel_col: "State",           result_field: "state" },
    { excel_col: "Company / Agency",result_field: "company" },
    { excel_col: "Due Date",        result_field: "due_date" },
    { excel_col: "Source URL",      result_field: "source_url" },
  ];
}

function addMapperRow(colName = "", fieldKey = "") {
  const colList = document.getElementById("mapper-columns");
  const row = document.createElement("div");
  row.className = "mapper-row";

  const colInput = document.createElement("input");
  colInput.type = "text";
  colInput.placeholder = "Excel column name";
  colInput.value = colName;

  const arrow = document.createElement("span");
  arrow.className = "arrow";
  arrow.textContent = "←";

  // Field select
  const fieldSel = document.createElement("select");
  const blank = document.createElement("option");
  blank.value = ""; blank.textContent = "— select field —";
  fieldSel.appendChild(blank);
  state.availableFields.forEach(f => {
    const opt = document.createElement("option");
    opt.value = f.key;
    opt.textContent = f.label;
    if (f.key === fieldKey) opt.selected = true;
    fieldSel.appendChild(opt);
  });

  // Drop target support
  fieldSel.addEventListener("dragover", e => { e.preventDefault(); fieldSel.classList.add("drag-over"); });
  fieldSel.addEventListener("dragleave", () => fieldSel.classList.remove("drag-over"));
  fieldSel.addEventListener("drop", e => {
    e.preventDefault();
    const key = e.dataTransfer.getData("text/plain");
    fieldSel.value = key;
    fieldSel.classList.remove("drag-over");
  });

  const removeBtn = document.createElement("button");
  removeBtn.className = "btn btn-sm btn-danger btn-remove-col";
  removeBtn.textContent = "✕";
  removeBtn.addEventListener("click", () => row.remove());

  row.append(colInput, arrow, fieldSel, removeBtn);
  colList.appendChild(row);
}

document.getElementById("btn-add-col").addEventListener("click", () => addMapperRow());

document.getElementById("btn-reset-mapping").addEventListener("click", () => {
  state.currentMapping = null;
  buildMapperUI();
  toast("Mapping reset to default.");
});

document.getElementById("btn-apply-mapping").addEventListener("click", () => {
  state.currentMapping = collectMapping();
  toast("Mapping applied. It will be used for the next export.", "success");
  closeMapperModal();
});

document.getElementById("btn-save-mapping").addEventListener("click", async () => {
  const name = document.getElementById("mapping-name-input").value.trim();
  if (!name) { toast("Please enter a name for the mapping.", "error"); return; }
  const mapping = collectMapping();
  if (!mapping.length) { toast("Add at least one column to the mapping.", "error"); return; }
  try {
    await apiPost("/mappings", { name, field_mappings: mapping });
    state.currentMapping = mapping;
    toast(`Mapping "${name}" saved!`, "success");
    closeMapperModal();
    loadMappingsPanel();
  } catch (err) { toast(err.message, "error"); }
});

function collectMapping() {
  const rows = document.querySelectorAll("#mapper-columns .mapper-row");
  const mapping = [];
  rows.forEach(row => {
    const colName  = row.querySelector("input").value.trim();
    const fieldKey = row.querySelector("select").value;
    if (colName && fieldKey) mapping.push({ excel_col: colName, result_field: fieldKey });
  });
  return mapping;
}

// ─── Mapping select on Results panel ─────────────────────────────────────────
document.getElementById("mapping-select").addEventListener("change", () => {
  const id = document.getElementById("mapping-select").value;
  if (!id) {
    state.currentMapping = null;
    toast("Using default mapping.");
    return;
  }
  const m = state.savedMappings.find(x => x.id == id);
  if (m) {
    state.currentMapping = JSON.parse(m.field_mappings);
    toast(`Mapping "${m.mapping_name}" selected.`, "success");
  }
});

document.getElementById("btn-open-mapper").addEventListener("click", openMapperModal);

// ─── Utility ──────────────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ─── Initialise ───────────────────────────────────────────────────────────────
(async function init() {
  await Promise.all([initKeywords(), initSources(), initFields()]);
})();
