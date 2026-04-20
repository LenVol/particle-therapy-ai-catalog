from __future__ import annotations

import json
from pathlib import Path
from typing import Any


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AI/ML in Particle Therapy Catalog</title>
  <meta name="description" content="A curated catalog of repositories and datasets at the intersection of particle therapy and AI/ML.">
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <div class="page-shell">
    <header class="hero">
      <div class="hero-inner">
        <div class="hero-copy">
          <span class="eyebrow">AI + PARTICLE THERAPY</span>
          <h1>Research Atlas</h1>
          <p class="hero-text">
            A curated, searchable catalog of tools, models, datasets, and records related to
            particle therapy, proton therapy, hadron therapy, and machine learning.
          </p>
        </div>

        <div class="hero-panel">
          <div class="hero-stat">
            <span class="hero-stat-label">Visible items</span>
            <span class="hero-stat-value" id="heroVisibleCount">0</span>
          </div>
          <div class="hero-stat">
            <span class="hero-stat-label">Current tab</span>
            <span class="hero-stat-value" id="heroCurrentTab">Tools</span>
          </div>
        </div>
      </div>
    </header>

    <main class="main-content">
      <section class="tabs">
        <button class="tab-button active" id="tabTools" type="button">Tools</button>
        <button class="tab-button" id="tabDatasets" type="button">Data &amp; Records</button>
      </section>

      <section class="controls">
        <div class="controls-grid">
          <label class="control">
            <span>Search</span>
            <input id="search" type="search" placeholder="Search titles, descriptions, categories, tags...">
          </label>

          <label class="control">
            <span>Source</span>
            <select id="sourceFilter">
              <option value="">All sources</option>
            </select>
          </label>

          <label class="control">
            <span>Category / Tag</span>
            <select id="tagFilter">
              <option value="">All categories</option>
            </select>
          </label>

          <label class="control">
            <span>Sort by</span>
            <select id="sortBy">
              <option value="popularity">Popularity</option>
              <option value="updated">Last updated</option>
              <option value="name">Name</option>
            </select>
          </label>
        </div>

        <div class="controls-actions">
          <button id="resetFilters" type="button">Reset filters</button>
        </div>
      </section>

      <section class="stats-bar" id="stats"></section>
      <section class="cards-grid" id="results"></section>
    </main>
  </div>

  <script src="app.js"></script>
</body>
</html>
"""


APP_JS = r"""function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function loadJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    if (response.status === 404) return [];
    throw new Error(`Failed to load ${path}: ${response.status}`);
  }
  return await response.json();
}

function uniqueSorted(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

function formatDate(value) {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toISOString().slice(0, 10);
}

function buildStats(items, mode) {
  if (mode === "datasets") {
    const totalDownloads = items.reduce((sum, item) => sum + (item.downloads || 0), 0);
    return `
      <div class="stat-pill">
        <span class="stat-label">Shown</span>
        <span class="stat-value">${items.length}</span>
      </div>
      <div class="stat-pill">
        <span class="stat-label">Downloads shown</span>
        <span class="stat-value">${totalDownloads}</span>
      </div>
    `;
  }

  const totalStars = items.reduce((sum, item) => sum + (item.stars || 0), 0);
  return `
    <div class="stat-pill">
      <span class="stat-label">Shown</span>
      <span class="stat-value">${items.length}</span>
    </div>
    <div class="stat-pill">
      <span class="stat-label">Stars shown</span>
      <span class="stat-value">${totalStars}</span>
    </div>
  `;
}

function getToolSearchBlob(item) {
  const cls = item.classification || {};
  return [
    item.full_name,
    item.description,
    (item.topics || []).join(" "),
    (cls.categories || []).join(" "),
    cls.summary || "",
    item.manual_note || "",
    (item.manual_tags || []).join(" "),
    cls.likely_tool_type || ""
  ].join(" ").toLowerCase();
}

function getDatasetSearchBlob(item) {
  return [
    item.title,
    item.summary,
    (item.tags || []).join(" "),
    (item.creators || []).join(" "),
    item.source || "",
    item.license || "",
    item.record_type || "",
    item.kind || "",
    item.doi || ""
  ].join(" ").toLowerCase();
}

function getItemSource(item, mode) {
  return mode === "datasets" ? (item.source || "") : (item.platform || item.source || "");
}

function getItemTags(item, mode) {
  if (mode === "datasets") return item.tags || [];
  const cls = item.classification || {};
  return [...(cls.categories || []), ...(item.topics || []), ...(item.manual_tags || [])];
}

function sortItems(items, sortBy, mode) {
  const sorted = [...items];

  sorted.sort((a, b) => {
    if (sortBy === "updated") {
      return (b.updated_at || "").localeCompare(a.updated_at || "");
    }

    if (sortBy === "name") {
      const aName = mode === "datasets" ? (a.title || "") : (a.full_name || "");
      const bName = mode === "datasets" ? (b.title || "") : (b.full_name || "");
      return aName.localeCompare(bName);
    }

    if (mode === "datasets") {
      return ((b.downloads || 0) + (b.likes || 0)) - ((a.downloads || 0) + (a.likes || 0));
    }

    return (b.stars || 0) - (a.stars || 0);
  });

  return sorted;
}

function matchesFilters(item, filters, mode) {
  const query = filters.query.trim().toLowerCase();
  const blob = mode === "datasets" ? getDatasetSearchBlob(item) : getToolSearchBlob(item);

  if (query && !blob.includes(query)) return false;
  if (filters.source && getItemSource(item, mode) !== filters.source) return false;

  if (filters.tag) {
    const tags = getItemTags(item, mode);
    if (!tags.includes(filters.tag)) return false;
  }

  return true;
}

function renderToolCard(item) {
  const cls = item.classification || {};
  const categories = cls.categories || [];
  const warnings = cls.warnings || [];
  const topics = item.topics || [];
  const sourceLabel = item.platform || item.source || "unknown";

  return `
    <a class="repo-card" href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">
      <div class="repo-card-top">
        <div>
          <div class="repo-kicker">${escapeHtml(sourceLabel)} · ${escapeHtml(cls.likely_tool_type || "unclear")}</div>
          <h2 class="repo-title">${escapeHtml(item.full_name || "")}</h2>
          <p class="repo-summary">${escapeHtml(cls.summary || item.description || "No description available.")}</p>
        </div>
      </div>

      <div class="repo-meta-row">
        <span>★ ${item.stars || 0}</span>
        <span>Updated ${escapeHtml(formatDate(item.updated_at))}</span>
        <span>${escapeHtml(item.language || "Unknown")}</span>
      </div>

      ${
        categories.length
          ? `<div class="chip-row">${categories.slice(0, 4).map(x => `<span class="chip chip-primary">${escapeHtml(x)}</span>`).join("")}</div>`
          : `<div class="chip-row"></div>`
      }

      <div class="hover-panel">
        ${
          topics.length
            ? `<div class="hover-block">
                <div class="hover-label">Topics</div>
                <div class="chip-row">${topics.slice(0, 8).map(x => `<span class="chip chip-subtle">${escapeHtml(x)}</span>`).join("")}</div>
              </div>`
            : ""
        }

        ${
          warnings.length
            ? `<div class="hover-block">
                <div class="hover-label">Notes</div>
                <ul class="hover-list warning-list">${warnings.slice(0, 2).map(x => `<li>${escapeHtml(x)}</li>`).join("")}</ul>
              </div>`
            : ""
        }

        ${
          item.manual_note
            ? `<div class="hover-block">
                <div class="hover-label">Curator note</div>
                <p class="hover-note">${escapeHtml(item.manual_note)}</p>
              </div>`
            : ""
        }
      </div>
    </a>
  `;
}

function renderDatasetCard(item) {
  return `
    <a class="repo-card dataset-card" href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">
      <div class="repo-card-top">
        <div>
          <div class="repo-kicker">${escapeHtml(item.source || "record")} · ${escapeHtml(item.record_type || item.kind || "record")}${item.doi ? ` · DOI` : ""}</div>
          <h2 class="repo-title">${escapeHtml(item.title || "")}</h2>
          <p class="repo-summary">${escapeHtml(item.summary || "No description available.")}</p>
        </div>
      </div>

      <div class="repo-meta-row">
        <span>Downloads ${item.downloads || 0}</span>
        <span>Updated ${escapeHtml(formatDate(item.updated_at))}</span>
        <span>${escapeHtml(item.license || "Unknown license")}</span>
      </div>

      ${
        (item.tags || []).length
          ? `<div class="chip-row">${(item.tags || []).slice(0, 6).map(x => `<span class="chip chip-primary">${escapeHtml(x)}</span>`).join("")}</div>`
          : `<div class="chip-row"></div>`
      }

      <div class="hover-panel">
        ${
          (item.creators || []).length
            ? `<div class="hover-block">
                <div class="hover-label">Creators</div>
                <p class="hover-note">${escapeHtml((item.creators || []).slice(0, 6).join(", "))}</p>
              </div>`
            : ""
        }

        ${
          item.doi
            ? `<div class="hover-block">
                <div class="hover-label">DOI</div>
                <p class="hover-note">${escapeHtml(item.doi)}</p>
              </div>`
            : ""
        }
      </div>
    </a>
  `;
}

function renderCards(items, mode) {
  const results = document.getElementById("results");
  if (!results) return;

  if (!items.length) {
    results.innerHTML = `
      <div class="empty-state">
        <h2>No items match the current filters.</h2>
        <p>Try a broader search or reset the filters.</p>
      </div>
    `;
    return;
  }

  results.innerHTML = items.map(item => (
    mode === "datasets" ? renderDatasetCard(item) : renderToolCard(item)
  )).join("");
}

function populateSelect(selectEl, values, placeholderLabel) {
  if (!selectEl) return;
  const current = selectEl.value;
  selectEl.innerHTML = `<option value="">${placeholderLabel}</option>`;
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    selectEl.appendChild(option);
  }
  selectEl.value = current;
}

function addSafeListener(el, eventName, handler) {
  if (el) el.addEventListener(eventName, handler);
}

async function main() {
  const [tools, datasets] = await Promise.all([
    loadJson("catalog.json"),
    loadJson("datasets.json")
  ]);

  const state = { mode: "tools" };

  const sourceFilter = document.getElementById("sourceFilter");
  const tagFilter = document.getElementById("tagFilter");
  const sortBy = document.getElementById("sortBy");
  const search = document.getElementById("search");
  const stats = document.getElementById("stats");
  const resetButton = document.getElementById("resetFilters");
  const heroVisibleCount = document.getElementById("heroVisibleCount");
  const heroCurrentTab = document.getElementById("heroCurrentTab");
  const tabTools = document.getElementById("tabTools");
  const tabDatasets = document.getElementById("tabDatasets");

  function getCurrentItems() {
    return state.mode === "datasets" ? datasets : tools;
  }

  function refreshFilters() {
    const items = getCurrentItems();
    const sources = uniqueSorted(items.map(item => getItemSource(item, state.mode)));
    const tags = uniqueSorted(items.flatMap(item => getItemTags(item, state.mode)));

    populateSelect(sourceFilter, sources, "All sources");
    populateSelect(tagFilter, tags, "All categories");
  }

  function update() {
    const items = getCurrentItems();

    const filters = {
      query: search?.value || "",
      source: sourceFilter?.value || "",
      tag: tagFilter?.value || ""
    };

    const filtered = items.filter(item => matchesFilters(item, filters, state.mode));
    const sorted = sortItems(filtered, sortBy?.value || "popularity", state.mode);

    if (heroVisibleCount) heroVisibleCount.textContent = String(sorted.length);
    if (heroCurrentTab) heroCurrentTab.textContent = state.mode === "datasets" ? "Data & Records" : "Tools";
    if (stats) stats.innerHTML = buildStats(sorted, state.mode);

    renderCards(sorted, state.mode);
  }

  function setMode(mode) {
    state.mode = mode;
    if (tabTools) tabTools.classList.toggle("active", mode === "tools");
    if (tabDatasets) tabDatasets.classList.toggle("active", mode === "datasets");
    if (sortBy) sortBy.value = "popularity";
    if (sourceFilter) sourceFilter.value = "";
    if (tagFilter) tagFilter.value = "";
    refreshFilters();
    update();
  }

  addSafeListener(search, "input", update);
  addSafeListener(sourceFilter, "change", update);
  addSafeListener(tagFilter, "change", update);
  addSafeListener(sortBy, "change", update);

  addSafeListener(resetButton, "click", () => {
    if (search) search.value = "";
    if (sourceFilter) sourceFilter.value = "";
    if (tagFilter) tagFilter.value = "";
    if (sortBy) sortBy.value = "popularity";
    update();
  });

  addSafeListener(tabTools, "click", () => setMode("tools"));
  addSafeListener(tabDatasets, "click", () => setMode("datasets"));

  refreshFilters();
  update();
}

function renderFatalError(error) {
  const results = document.getElementById("results");
  if (!results) return;

  results.innerHTML = `
    <div class="empty-state">
      <h2>Could not load catalog</h2>
      <p>${escapeHtml(error?.message || String(error))}</p>
    </div>
  `;
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    main().catch(renderFatalError);
  });
} else {
  main().catch(renderFatalError);
}
"""


STYLES_CSS = """* {
  box-sizing: border-box;
}

:root {
  --bg-0: #f3f9fd;
  --bg-1: #eaf4fb;
  --surface: rgba(255, 255, 255, 0.78);
  --surface-strong: rgba(255, 255, 255, 0.92);
  --border: rgba(80, 132, 180, 0.18);
  --text: #10324a;
  --muted: #56758c;
  --primary: #1976b8;
  --primary-2: #2f94d1;
  --shadow: 0 14px 40px rgba(19, 83, 126, 0.12);
  --shadow-strong: 0 22px 54px rgba(19, 83, 126, 0.18);
  --card-bg: linear-gradient(135deg, rgba(22, 118, 184, 0.10), rgba(121, 191, 232, 0.10));
}

html, body {
  margin: 0;
  padding: 0;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--text);
  background:
    radial-gradient(circle at top left, rgba(151, 211, 241, 0.35), transparent 34%),
    radial-gradient(circle at top right, rgba(92, 171, 219, 0.18), transparent 26%),
    linear-gradient(180deg, var(--bg-0), var(--bg-1) 48%, #f8fcff);
}

body {
  line-height: 1.5;
}

.page-shell {
  min-height: 100vh;
}

.hero {
  padding: 3.5rem 1.25rem 1.5rem;
}

.hero-inner {
  max-width: 1220px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: 1.7fr 0.9fr;
  gap: 1.2rem;
  align-items: stretch;
}

.hero-copy,
.hero-panel,
.controls,
.stat-pill,
.repo-card,
.empty-state,
.tabs {
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}

.hero-copy {
  background: linear-gradient(135deg, rgba(255,255,255,0.78), rgba(255,255,255,0.62));
  border: 1px solid var(--border);
  border-radius: 28px;
  box-shadow: var(--shadow);
  padding: 2rem 2rem 1.8rem;
}

.eyebrow {
  display: inline-block;
  margin-bottom: 0.65rem;
  padding: 0.32rem 0.7rem;
  border-radius: 999px;
  background: rgba(25, 118, 184, 0.10);
  color: var(--primary);
  font-size: 0.8rem;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.hero-copy h1 {
  margin: 0;
  font-size: clamp(2.2rem, 4vw, 4rem);
  line-height: 1.02;
  letter-spacing: -0.03em;
}

.hero-text {
  max-width: 62ch;
  margin: 0.85rem 0 0;
  color: var(--muted);
  font-size: 1.02rem;
}

.hero-panel {
  background: linear-gradient(160deg, rgba(25, 118, 184, 0.93), rgba(72, 160, 213, 0.88));
  border: 1px solid rgba(255,255,255,0.16);
  border-radius: 28px;
  box-shadow: var(--shadow-strong);
  padding: 1.4rem;
  color: white;
  display: grid;
  gap: 1rem;
  align-content: center;
}

.hero-stat {
  border-radius: 18px;
  background: rgba(255,255,255,0.10);
  padding: 1rem 1.1rem;
  border: 1px solid rgba(255,255,255,0.12);
}

.hero-stat-label {
  display: block;
  opacity: 0.85;
  font-size: 0.85rem;
}

.hero-stat-value {
  display: block;
  font-size: 2rem;
  font-weight: 800;
  margin-top: 0.18rem;
}

.main-content {
  max-width: 1220px;
  margin: 0 auto;
  padding: 0 1.25rem 3rem;
}

.tabs {
  display: inline-flex;
  gap: 0.5rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 18px;
  box-shadow: var(--shadow);
  padding: 0.5rem;
  margin-bottom: 1rem;
}

.tab-button {
  border: 1px solid transparent;
  background: transparent;
  color: var(--muted);
  border-radius: 14px;
  padding: 0.7rem 1rem;
  font-weight: 700;
  cursor: pointer;
}

.tab-button.active {
  background: rgba(25, 118, 184, 0.12);
  color: var(--primary);
  border-color: rgba(25, 118, 184, 0.16);
}

.controls {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 24px;
  box-shadow: var(--shadow);
  padding: 1rem;
}

.controls-grid {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1fr;
  gap: 0.9rem;
}

.control {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.control span {
  font-size: 0.85rem;
  color: var(--muted);
  font-weight: 700;
}

input[type="search"],
select,
button {
  appearance: none;
  border: 1px solid rgba(92, 151, 193, 0.22);
  background: rgba(255,255,255,0.92);
  color: var(--text);
  border-radius: 16px;
  padding: 0.85rem 0.95rem;
  font-size: 0.95rem;
}

.controls-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 0.9rem;
}

button {
  cursor: pointer;
  font-weight: 700;
  color: var(--primary);
}

.stats-bar {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.9rem;
  margin: 1rem 0 1.1rem;
}

.stat-pill {
  background: var(--surface-strong);
  border: 1px solid var(--border);
  border-radius: 18px;
  box-shadow: var(--shadow);
  padding: 0.95rem 1rem;
}

.stat-label {
  display: block;
  color: var(--muted);
  font-size: 0.82rem;
  font-weight: 700;
}

.stat-value {
  display: block;
  font-size: 1.35rem;
  font-weight: 800;
  margin-top: 0.1rem;
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
  gap: 1rem;
}

.repo-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
  min-height: 260px;
  text-decoration: none;
  color: inherit;
  padding: 1.1rem;
  border-radius: 24px;
  border: 1px solid var(--border);
  background: var(--surface-strong);
  box-shadow: var(--shadow);
  overflow: hidden;
  transition: transform 220ms ease, box-shadow 220ms ease, border-color 220ms ease;
}

.repo-card::before {
  content: "";
  position: absolute;
  inset: 0;
  background: var(--card-bg);
  z-index: 0;
}

.repo-card > * {
  position: relative;
  z-index: 1;
}

.repo-card:hover {
  transform: translateY(-6px);
  box-shadow: var(--shadow-strong);
  border-color: rgba(47, 148, 209, 0.32);
}

.repo-card-top {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
}

.repo-kicker {
  color: var(--primary);
  font-size: 0.76rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.repo-title {
  margin: 0.28rem 0 0.35rem;
  font-size: 1.15rem;
  line-height: 1.2;
  letter-spacing: -0.02em;
}

.repo-summary {
  margin: 0;
  color: var(--muted);
  font-size: 0.93rem;
}

.repo-meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.8rem;
  color: var(--muted);
  font-size: 0.87rem;
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
}

.chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 0.32rem 0.62rem;
  font-size: 0.79rem;
  font-weight: 700;
}

.chip-primary {
  background: rgba(25, 118, 184, 0.12);
  color: var(--primary);
}

.chip-subtle {
  background: rgba(255,255,255,0.7);
  color: #4f6a7d;
  border: 1px solid rgba(80, 132, 180, 0.12);
}

.hover-panel {
  margin-top: auto;
  border-top: 1px solid rgba(80, 132, 180, 0.12);
  padding-top: 0.9rem;
  opacity: 0.82;
  transform: translateY(8px);
  transition: opacity 220ms ease, transform 220ms ease;
}

.repo-card:hover .hover-panel {
  opacity: 1;
  transform: translateY(0);
}

.hover-block + .hover-block {
  margin-top: 0.7rem;
}

.hover-label {
  font-size: 0.75rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  margin-bottom: 0.35rem;
}

.hover-list {
  margin: 0;
  padding-left: 1.1rem;
  color: var(--muted);
  font-size: 0.88rem;
}

.warning-list {
  color: #946b21;
}

.hover-note {
  margin: 0;
  color: var(--muted);
  font-size: 0.9rem;
}

.empty-state {
  grid-column: 1 / -1;
  background: var(--surface-strong);
  border: 1px solid var(--border);
  border-radius: 24px;
  padding: 1.6rem;
  text-align: center;
  box-shadow: var(--shadow);
}

.empty-state h2 {
  margin-top: 0;
}

.empty-state p {
  margin-bottom: 0;
  color: var(--muted);
}

@media (max-width: 980px) {
  .hero-inner {
    grid-template-columns: 1fr;
  }

  .controls-grid {
    grid-template-columns: 1fr 1fr;
  }

  .stats-bar {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .hero {
    padding-top: 1.5rem;
  }

  .hero-copy,
  .hero-panel,
  .controls,
  .tabs {
    border-radius: 20px;
  }

  .controls-grid {
    grid-template-columns: 1fr;
  }

  .cards-grid {
    grid-template-columns: 1fr;
  }

  .repo-card-top {
    flex-direction: column;
  }
}
"""

def write_site(entries: list[dict[str, Any]]) -> None:
    site_dir = Path("site")
    site_dir.mkdir(parents=True, exist_ok=True)

    normalized_entries: list[dict[str, Any]] = []
    for item in entries:
        row = dict(item)
        row.setdefault("platform", row.get("source", ""))
        row.setdefault("full_name", "")
        row.setdefault("url", "")
        row.setdefault("description", "")
        row.setdefault("stars", 0)
        row.setdefault("language", None)
        row.setdefault("updated_at", None)
        row.setdefault("license", None)
        row.setdefault("topics", [])
        row.setdefault("manual_note", "")
        row.setdefault("manual_tags", [])
        row.setdefault("classification", {})
        row["classification"].setdefault("include", True)
        row["classification"].setdefault("summary", row.get("description", ""))
        row["classification"].setdefault("particle_therapy_relevance", "unknown")
        row["classification"].setdefault("ml_relevance", "unknown")
        row["classification"].setdefault("categories", [])
        row["classification"].setdefault("reasons", [])
        row["classification"].setdefault("warnings", [])
        row["classification"].setdefault("likely_tool_type", "unclear")
        normalized_entries.append(row)

    # tools
    (site_dir / "catalog.json").write_text(
        json.dumps(normalized_entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # datasets / records
    data_dir = Path("data")

    datasets_path = data_dir / "datasets.json"
    if datasets_path.exists():
        (site_dir / "datasets.json").write_text(
            datasets_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    else:
        (site_dir / "datasets.json").write_text("[]", encoding="utf-8")

    hf_model_tools_path = data_dir / "hf_model_tools.json"
    if hf_model_tools_path.exists():
        (site_dir / "hf_model_tools.json").write_text(
            hf_model_tools_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    else:
        (site_dir / "hf_model_tools.json").write_text("[]", encoding="utf-8")

    (site_dir / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (site_dir / "app.js").write_text(APP_JS, encoding="utf-8")
    (site_dir / "styles.css").write_text(STYLES_CSS, encoding="utf-8")
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")

