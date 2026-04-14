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
  <meta name="description" content="A curated catalog of repositories at the intersection of particle therapy and AI/ML.">
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <div class="page-shell">
    <header class="hero">
      <div class="hero-inner">
        <div class="hero-copy">
          <span class="eyebrow">AI + PARTICLE THERAPY</span>
          <h1>Repository Atlas</h1>
          <p class="hero-text">
            A curated, searchable catalog of open repositories related to particle therapy,
            proton therapy, hadron therapy, and machine learning.
          </p>
        </div>

        <div class="hero-panel">
          <div class="hero-stat">
            <span class="hero-stat-label">Indexed repositories</span>
            <span class="hero-stat-value" id="heroRepoCount">0</span>
          </div>
          <div class="hero-stat">
            <span class="hero-stat-label">Visible after filters</span>
            <span class="hero-stat-value" id="heroVisibleCount">0</span>
          </div>
        </div>
      </div>
    </header>

    <main class="main-content">
      <section class="controls">
        <div class="controls-grid">
          <label class="control">
            <span>Search</span>
            <input id="search" type="search" placeholder="Search repositories, categories, tags...">
          </label>

          <label class="control">
            <span>Platform</span>
            <select id="platformFilter">
              <option value="">All platforms</option>
            </select>
          </label>

          <label class="control">
            <span>Category</span>
            <select id="categoryFilter">
              <option value="">All categories</option>
            </select>
          </label>

          <label class="control">
            <span>Min confidence</span>
            <select id="confidenceFilter">
              <option value="0">Any</option>
              <option value="0.25">0.25</option>
              <option value="0.50">0.50</option>
              <option value="0.75">0.75</option>
            </select>
          </label>

          <label class="control">
            <span>Sort by</span>
            <select id="sortBy">
              <option value="confidence">Confidence</option>
              <option value="stars">Stars</option>
              <option value="updated">Last updated</option>
              <option value="heuristic">Heuristic score</option>
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


APP_JS = r"""async function loadCatalog() {
  const response = await fetch("catalog.json");
  if (!response.ok) {
    throw new Error(`Failed to load catalog.json: ${response.status}`);
  }
  return await response.json();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
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

function scoreTone(confidence) {
  if (confidence >= 0.75) return "high";
  if (confidence >= 0.50) return "mid";
  return "low";
}

function buildStats(items, totalItems) {
  const totalStars = items.reduce((sum, item) => sum + (item.stars || 0), 0);
  const avgConfidence = items.length
    ? (items.reduce((sum, item) => sum + (item.classification?.confidence || 0), 0) / items.length).toFixed(2)
    : "0.00";

  return `
    <div class="stat-pill">
      <span class="stat-label">Shown</span>
      <span class="stat-value">${items.length}</span>
    </div>
    <div class="stat-pill">
      <span class="stat-label">Total indexed</span>
      <span class="stat-value">${totalItems}</span>
    </div>
    <div class="stat-pill">
      <span class="stat-label">Stars shown</span>
      <span class="stat-value">${totalStars}</span>
    </div>
    <div class="stat-pill">
      <span class="stat-label">Avg confidence</span>
      <span class="stat-value">${avgConfidence}</span>
    </div>
  `;
}

function getSearchBlob(item) {
  const cls = item.classification || {};
  return [
    item.full_name,
    item.description,
    (item.topics || []).join(" "),
    (cls.categories || []).join(" "),
    (cls.reasons || []).join(" "),
    cls.summary || "",
    item.manual_note || "",
    (item.manual_tags || []).join(" "),
    cls.likely_tool_type || ""
  ].join(" ").toLowerCase();
}

function sortItems(items, sortBy) {
  const sorted = [...items];

  sorted.sort((a, b) => {
    const aCls = a.classification || {};
    const bCls = b.classification || {};

    if (sortBy === "stars") return (b.stars || 0) - (a.stars || 0);
    if (sortBy === "updated") return (b.updated_at || "").localeCompare(a.updated_at || "");
    if (sortBy === "heuristic") return (b.heuristic_total_score || 0) - (a.heuristic_total_score || 0);
    if (sortBy === "name") return (a.full_name || "").localeCompare(b.full_name || "");
    return (bCls.confidence || 0) - (aCls.confidence || 0);
  });

  return sorted;
}

function matchesFilters(item, filters) {
  const cls = item.classification || {};
  const query = filters.query.trim().toLowerCase();

  if (query && !getSearchBlob(item).includes(query)) return false;
  if (filters.platform && (item.platform || "") !== filters.platform) return false;
  if (filters.category && !(cls.categories || []).includes(filters.category)) return false;
  if ((cls.confidence || 0) < filters.minConfidence) return false;

  return true;
}

function renderCards(items) {
  const results = document.getElementById("results");

  if (!items.length) {
    results.innerHTML = `
      <div class="empty-state">
        <h2>No repositories match the current filters.</h2>
        <p>Try a broader search or reset the filters.</p>
      </div>
    `;
    return;
  }

  results.innerHTML = items.map(item => {
    const cls = item.classification || {};
    const categories = cls.categories || [];
    const reasons = cls.reasons || [];
    const warnings = cls.warnings || [];
    const topics = item.topics || [];
    const confidence = Number(cls.confidence || 0).toFixed(2);
    const tone = scoreTone(cls.confidence || 0);

    return `
      <a class="repo-card tone-${tone}" href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer" aria-label="Open ${escapeHtml(item.full_name || "")}">
        <div class="repo-card-top">
          <div>
            <div class="repo-kicker">${escapeHtml(item.platform || "unknown")} · ${escapeHtml(cls.likely_tool_type || "unclear")}</div>
            <h2 class="repo-title">${escapeHtml(item.full_name || "")}</h2>
            <p class="repo-summary">${escapeHtml(cls.summary || item.description || "No description available.")}</p>
          </div>
          <div class="confidence-badge">${confidence}</div>
        </div>

        <div class="repo-meta-row">
          <span>★ ${item.stars || 0}</span>
          <span>Updated ${escapeHtml(formatDate(item.updated_at))}</span>
          <span>Heuristic ${escapeHtml(item.heuristic_total_score ?? "")}</span>
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
            reasons.length
              ? `<div class="hover-block">
                  <div class="hover-label">Why included</div>
                  <ul class="hover-list">${reasons.slice(0, 3).map(x => `<li>${escapeHtml(x)}</li>`).join("")}</ul>
                </div>`
              : ""
          }

          ${
            warnings.length
              ? `<div class="hover-block">
                  <div class="hover-label">Warnings</div>
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
  }).join("");
}

function populateSelect(selectEl, values, placeholderLabel) {
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

async function main() {
  const rawItems = await loadCatalog();

  const platformFilter = document.getElementById("platformFilter");
  const categoryFilter = document.getElementById("categoryFilter");
  const confidenceFilter = document.getElementById("confidenceFilter");
  const sortBy = document.getElementById("sortBy");
  const search = document.getElementById("search");
  const stats = document.getElementById("stats");
  const resetButton = document.getElementById("resetFilters");

  document.getElementById("heroRepoCount").textContent = rawItems.length;

  const platforms = uniqueSorted(rawItems.map(item => item.platform));
  const categories = uniqueSorted(rawItems.flatMap(item => item.classification?.categories || []));

  populateSelect(platformFilter, platforms, "All platforms");
  populateSelect(categoryFilter, categories, "All categories");

  function update() {
    const filters = {
      query: search.value || "",
      platform: platformFilter.value || "",
      category: categoryFilter.value || "",
      minConfidence: Number(confidenceFilter.value || 0)
    };

    const filtered = rawItems.filter(item => matchesFilters(item, filters));
    const sorted = sortItems(filtered, sortBy.value || "confidence");

    document.getElementById("heroVisibleCount").textContent = sorted.length;
    stats.innerHTML = buildStats(sorted, rawItems.length);
    renderCards(sorted);
  }

  [platformFilter, categoryFilter, confidenceFilter, sortBy, search].forEach(el => {
    el.addEventListener("input", update);
    el.addEventListener("change", update);
  });

  resetButton.addEventListener("click", () => {
    search.value = "";
    platformFilter.value = "";
    categoryFilter.value = "";
    confidenceFilter.value = "0";
    sortBy.value = "confidence";
    update();
  });

  update();
}

main().catch(error => {
  const results = document.getElementById("results");
  results.innerHTML = `
    <div class="empty-state">
      <h2>Could not load catalog</h2>
      <p>${escapeHtml(error.message || String(error))}</p>
    </div>
  `;
});
"""


STYLES_CSS = """* {
  box-sizing: border-box;
}

:root {
  --bg-0: #f3f9fd;
  --bg-1: #eaf4fb;
  --bg-2: #dcecf8;
  --surface: rgba(255, 255, 255, 0.78);
  --surface-strong: rgba(255, 255, 255, 0.92);
  --border: rgba(80, 132, 180, 0.18);
  --text: #10324a;
  --muted: #56758c;
  --primary: #1976b8;
  --primary-2: #2f94d1;
  --primary-3: #79bfe8;
  --shadow: 0 14px 40px rgba(19, 83, 126, 0.12);
  --shadow-strong: 0 22px 54px rgba(19, 83, 126, 0.18);
  --high-bg: linear-gradient(135deg, rgba(22, 118, 184, 0.16), rgba(121, 191, 232, 0.14));
  --mid-bg: linear-gradient(135deg, rgba(30, 116, 170, 0.11), rgba(123, 187, 220, 0.10));
  --low-bg: linear-gradient(135deg, rgba(111, 164, 197, 0.12), rgba(221, 241, 252, 0.18));
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
  padding: 3.5rem 1.25rem 2rem;
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
.empty-state {
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

.controls {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 24px;
  box-shadow: var(--shadow);
  padding: 1rem;
}

.controls-grid {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1fr 1fr;
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
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

input[type="search"]:focus,
select:focus,
button:focus {
  outline: none;
  border-color: var(--primary-2);
  box-shadow: 0 0 0 4px rgba(47, 148, 209, 0.12);
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

button:hover {
  transform: translateY(-1px);
}

.stats-bar {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
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
  min-height: 300px;
  text-decoration: none;
  color: inherit;
  padding: 1.1rem;
  border-radius: 24px;
  border: 1px solid var(--border);
  background: var(--surface-strong);
  box-shadow: var(--shadow);
  overflow: hidden;
  transition:
    transform 220ms ease,
    box-shadow 220ms ease,
    border-color 220ms ease;
}

.repo-card::before {
  content: "";
  position: absolute;
  inset: 0;
  opacity: 1;
  z-index: 0;
}

.repo-card > * {
  position: relative;
  z-index: 1;
}

.repo-card.tone-high::before {
  background: var(--high-bg);
}

.repo-card.tone-mid::before {
  background: var(--mid-bg);
}

.repo-card.tone-low::before {
  background: var(--low-bg);
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

.confidence-badge {
  min-width: 56px;
  text-align: center;
  padding: 0.45rem 0.65rem;
  border-radius: 14px;
  background: rgba(255,255,255,0.72);
  border: 1px solid rgba(47, 148, 209, 0.18);
  font-weight: 800;
  color: var(--primary);
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
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 640px) {
  .hero {
    padding-top: 1.5rem;
  }

  .hero-copy,
  .hero-panel,
  .controls {
    border-radius: 20px;
  }

  .controls-grid {
    grid-template-columns: 1fr;
  }

  .stats-bar {
    grid-template-columns: 1fr;
  }

  .cards-grid {
    grid-template-columns: 1fr;
  }

  .repo-card {
    min-height: 280px;
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
        row.setdefault("platform", "")
        row.setdefault("full_name", "")
        row.setdefault("url", "")
        row.setdefault("description", "")
        row.setdefault("stars", 0)
        row.setdefault("language", None)
        row.setdefault("updated_at", None)
        row.setdefault("license", None)
        row.setdefault("topics", [])
        row.setdefault("heuristic_total_score", 0)
        row.setdefault("manual_note", "")
        row.setdefault("manual_tags", [])
        row.setdefault("classification", {})
        row["classification"].setdefault("include", True)
        row["classification"].setdefault("confidence", 0.0)
        row["classification"].setdefault("summary", row.get("description", ""))
        row["classification"].setdefault("particle_therapy_relevance", "unknown")
        row["classification"].setdefault("ml_relevance", "unknown")
        row["classification"].setdefault("categories", [])
        row["classification"].setdefault("reasons", [])
        row["classification"].setdefault("warnings", [])
        row["classification"].setdefault("likely_tool_type", "unclear")
        normalized_entries.append(row)

    (site_dir / "catalog.json").write_text(
        json.dumps(normalized_entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (site_dir / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (site_dir / "app.js").write_text(APP_JS, encoding="utf-8")
    (site_dir / "styles.css").write_text(STYLES_CSS, encoding="utf-8")
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")
