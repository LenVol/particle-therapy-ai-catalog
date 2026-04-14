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
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <main class="container">
    <header class="hero">
      <h1>AI/ML in Particle Therapy Catalog</h1>
      <p class="subtitle">
        Automatically discovered repositories at the intersection of particle therapy and machine learning / AI.
      </p>
    </header>

    <section class="toolbar">
      <div class="toolbar-grid">
        <div class="field">
          <label for="search">Search</label>
          <input id="search" type="search" placeholder="Search name, description, topics, categories...">
        </div>

        <div class="field">
          <label for="platformFilter">Platform</label>
          <select id="platformFilter">
            <option value="">All platforms</option>
          </select>
        </div>

        <div class="field">
          <label for="categoryFilter">Category</label>
          <select id="categoryFilter">
            <option value="">All categories</option>
          </select>
        </div>

        <div class="field">
          <label for="confidenceFilter">Min confidence</label>
          <select id="confidenceFilter">
            <option value="0">Any</option>
            <option value="0.25">0.25</option>
            <option value="0.50">0.50</option>
            <option value="0.75">0.75</option>
          </select>
        </div>

        <div class="field">
          <label for="sortBy">Sort by</label>
          <select id="sortBy">
            <option value="confidence">Confidence</option>
            <option value="stars">Stars</option>
            <option value="updated">Last updated</option>
            <option value="heuristic">Heuristic score</option>
            <option value="name">Name</option>
          </select>
        </div>
      </div>

      <div class="toolbar-actions">
        <button id="resetFilters" type="button">Reset filters</button>
      </div>
    </section>

    <section class="stats" id="stats"></section>
    <section class="results" id="results"></section>
  </main>

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

function confidenceClass(confidence) {
  if (confidence >= 0.75) return "badge-good";
  if (confidence >= 0.50) return "badge-ok";
  return "badge-low";
}

function buildStats(items, totalItems) {
  const totalStars = items.reduce((sum, item) => sum + (item.stars || 0), 0);
  const platformCounts = items.reduce((acc, item) => {
    const key = item.platform || "unknown";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});

  const pieces = [
    `<div class="stat-card"><div class="stat-value">${items.length}</div><div class="stat-label">Shown</div></div>`,
    `<div class="stat-card"><div class="stat-value">${totalItems}</div><div class="stat-label">Total indexed</div></div>`,
    `<div class="stat-card"><div class="stat-value">${totalStars}</div><div class="stat-label">Stars shown</div></div>`,
  ];

  for (const [platform, count] of Object.entries(platformCounts).sort()) {
    pieces.push(
      `<div class="stat-card"><div class="stat-value">${count}</div><div class="stat-label">${escapeHtml(platform)}</div></div>`
    );
  }

  return pieces.join("");
}

function getSearchBlob(item) {
  const cls = item.classification || {};
  return [
    item.full_name,
    item.description,
    (item.topics || []).join(" "),
    (cls.categories || []).join(" "),
    (cls.reasons || []).join(" "),
    (cls.summary || ""),
    (item.manual_note || ""),
    (item.manual_tags || []).join(" "),
    cls.likely_tool_type || ""
  ]
    .join(" ")
    .toLowerCase();
}

function sortItems(items, sortBy) {
  const sorted = [...items];

  sorted.sort((a, b) => {
    const aCls = a.classification || {};
    const bCls = b.classification || {};

    if (sortBy === "stars") {
      return (b.stars || 0) - (a.stars || 0);
    }

    if (sortBy === "updated") {
      const aDate = a.updated_at || "";
      const bDate = b.updated_at || "";
      return bDate.localeCompare(aDate);
    }

    if (sortBy === "heuristic") {
      return (b.heuristic_total_score || 0) - (a.heuristic_total_score || 0);
    }

    if (sortBy === "name") {
      return (a.full_name || "").localeCompare(b.full_name || "");
    }

    return (bCls.confidence || 0) - (aCls.confidence || 0);
  });

  return sorted;
}

function matchesFilters(item, filters) {
  const cls = item.classification || {};
  const query = filters.query.trim().toLowerCase();

  if (query) {
    const blob = getSearchBlob(item);
    if (!blob.includes(query)) return false;
  }

  if (filters.platform && (item.platform || "") !== filters.platform) {
    return false;
  }

  if (filters.category) {
    const categories = cls.categories || [];
    if (!categories.includes(filters.category)) return false;
  }

  if ((cls.confidence || 0) < filters.minConfidence) {
    return false;
  }

  return true;
}

function renderCards(items) {
  const results = document.getElementById("results");

  if (!items.length) {
    results.innerHTML = `
      <div class="empty-state">
        <h2>No repositories match the current filters.</h2>
        <p>Try broadening the search or resetting the filters.</p>
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
    const manualTags = item.manual_tags || [];
    const stars = item.stars ?? 0;
    const updatedAt = formatDate(item.updated_at);
    const confidence = Number(cls.confidence || 0).toFixed(2);

    return `
      <article class="card">
        <div class="card-header">
          <div>
            <h2 class="repo-name">
              <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">
                ${escapeHtml(item.full_name || "")}
              </a>
            </h2>
            <p class="repo-description">${escapeHtml(cls.summary || item.description || "No description available.")}</p>
          </div>
          <div class="badges">
            <span class="badge">${escapeHtml(item.platform || "unknown")}</span>
            <span class="badge">${escapeHtml(cls.likely_tool_type || "unclear")}</span>
            <span class="badge ${confidenceClass(cls.confidence || 0)}">confidence ${confidence}</span>
          </div>
        </div>

        <div class="meta">
          <span><strong>Stars:</strong> ${stars}</span>
          <span><strong>Updated:</strong> ${escapeHtml(updatedAt)}</span>
          <span><strong>Heuristic:</strong> ${escapeHtml(item.heuristic_total_score ?? "")}</span>
          <span><strong>Language:</strong> ${escapeHtml(item.language || "Unknown")}</span>
        </div>

        ${
          categories.length
            ? `<div class="section"><div class="section-title">Categories</div><div class="chips">${
                categories.map(x => `<span class="chip">${escapeHtml(x)}</span>`).join("")
              }</div></div>`
            : ""
        }

        ${
          topics.length
            ? `<div class="section"><div class="section-title">Topics</div><div class="chips">${
                topics.slice(0, 12).map(x => `<span class="chip subtle">${escapeHtml(x)}</span>`).join("")
              }</div></div>`
            : ""
        }

        ${
          manualTags.length
            ? `<div class="section"><div class="section-title">Manual tags</div><div class="chips">${
                manualTags.map(x => `<span class="chip highlight">${escapeHtml(x)}</span>`).join("")
              }</div></div>`
            : ""
        }

        ${
          reasons.length
            ? `<div class="section"><div class="section-title">Why included</div><ul class="clean-list">${
                reasons.slice(0, 4).map(x => `<li>${escapeHtml(x)}</li>`).join("")
              }</ul></div>`
            : ""
        }

        ${
          warnings.length
            ? `<div class="section"><div class="section-title">Warnings</div><ul class="clean-list warning-list">${
                warnings.slice(0, 4).map(x => `<li>${escapeHtml(x)}</li>`).join("")
              }</ul></div>`
            : ""
        }

        ${
          item.manual_note
            ? `<div class="section"><div class="section-title">Curator note</div><p>${escapeHtml(item.manual_note)}</p></div>`
            : ""
        }
      </article>
    `;
  }).join("");
}

function populateSelect(selectEl, values, placeholderLabel) {
  const existing = selectEl.value;
  selectEl.innerHTML = `<option value="">${placeholderLabel}</option>`;
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    selectEl.appendChild(option);
  }
  selectEl.value = existing;
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

  const platforms = uniqueSorted(rawItems.map(item => item.platform));
  const categories = uniqueSorted(
    rawItems.flatMap(item => (item.classification?.categories || []))
  );

  populateSelect(platformFilter, platforms, "All platforms");
  populateSelect(categoryFilter, categories, "All categories");

  function update() {
    const filters = {
      query: search.value || "",
      platform: platformFilter.value || "",
      category: categoryFilter.value || "",
      minConfidence: Number(confidenceFilter.value || 0),
    };

    const filtered = rawItems.filter(item => matchesFilters(item, filters));
    const sorted = sortItems(filtered, sortBy.value || "confidence");

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
  --bg: #f7f8fb;
  --card: #ffffff;
  --text: #1f2937;
  --muted: #6b7280;
  --border: #e5e7eb;
  --accent: #2563eb;
  --accent-soft: #dbeafe;
  --good: #166534;
  --good-bg: #dcfce7;
  --ok: #92400e;
  --ok-bg: #fef3c7;
  --low: #991b1b;
  --low-bg: #fee2e2;
  --shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
}

html, body {
  margin: 0;
  padding: 0;
  background: var(--bg);
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

body {
  line-height: 1.5;
}

.container {
  width: min(1120px, calc(100vw - 2rem));
  margin: 0 auto;
  padding: 2rem 0 4rem;
}

.hero {
  margin-bottom: 1.5rem;
}

.hero h1 {
  margin: 0 0 0.4rem;
  font-size: clamp(1.9rem, 3vw, 2.8rem);
  line-height: 1.1;
}

.subtitle {
  margin: 0;
  color: var(--muted);
  font-size: 1rem;
}

.toolbar {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 18px;
  box-shadow: var(--shadow);
  padding: 1rem;
  margin: 1.25rem 0 1.25rem;
}

.toolbar-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 0.9rem;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.field label {
  font-size: 0.9rem;
  color: var(--muted);
  font-weight: 600;
}

input[type="search"],
select,
button {
  border: 1px solid var(--border);
  border-radius: 12px;
  background: #fff;
  padding: 0.78rem 0.9rem;
  font-size: 0.95rem;
  color: var(--text);
}

input[type="search"]:focus,
select:focus,
button:focus {
  outline: 2px solid var(--accent-soft);
  border-color: var(--accent);
}

.toolbar-actions {
  margin-top: 0.9rem;
  display: flex;
  justify-content: flex-end;
}

button {
  cursor: pointer;
  font-weight: 600;
}

button:hover {
  border-color: var(--accent);
}

.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.8rem;
  margin: 0 0 1rem;
}

.stat-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 0.9rem 1rem;
  box-shadow: var(--shadow);
}

.stat-value {
  font-size: 1.35rem;
  font-weight: 800;
}

.stat-label {
  color: var(--muted);
  font-size: 0.88rem;
}

.results {
  display: grid;
  gap: 1rem;
}

.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 18px;
  box-shadow: var(--shadow);
  padding: 1.15rem 1.15rem 1rem;
}

.card-header {
  display: flex;
  gap: 1rem;
  justify-content: space-between;
  align-items: flex-start;
}

.repo-name {
  margin: 0 0 0.35rem;
  font-size: 1.2rem;
}

.repo-name a {
  color: var(--accent);
  text-decoration: none;
}

.repo-name a:hover {
  text-decoration: underline;
}

.repo-description {
  margin: 0;
  color: var(--muted);
}

.badges {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  justify-content: flex-end;
}

.badge {
  display: inline-flex;
  align-items: center;
  padding: 0.32rem 0.65rem;
  border-radius: 999px;
  background: #f3f4f6;
  color: #374151;
  font-size: 0.82rem;
  font-weight: 700;
  white-space: nowrap;
}

.badge-good {
  background: var(--good-bg);
  color: var(--good);
}

.badge-ok {
  background: var(--ok-bg);
  color: var(--ok);
}

.badge-low {
  background: var(--low-bg);
  color: var(--low);
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  margin: 0.95rem 0 0.5rem;
  color: var(--muted);
  font-size: 0.93rem;
}

.section {
  margin-top: 0.85rem;
}

.section-title {
  font-size: 0.84rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
  margin-bottom: 0.4rem;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
}

.chip {
  display: inline-flex;
  align-items: center;
  padding: 0.3rem 0.65rem;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 0.82rem;
  font-weight: 600;
}

.chip.subtle {
  background: #f3f4f6;
  color: #4b5563;
}

.chip.highlight {
  background: #ede9fe;
  color: #6d28d9;
}

.clean-list {
  margin: 0;
  padding-left: 1.2rem;
}

.warning-list {
  color: #92400e;
}

.empty-state {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 18px;
  box-shadow: var(--shadow);
  padding: 1.5rem;
  text-align: center;
}

@media (max-width: 960px) {
  .toolbar-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .card-header {
    flex-direction: column;
  }

  .badges {
    justify-content: flex-start;
  }
}

@media (max-width: 640px) {
  .container {
    width: min(100vw - 1rem, 1120px);
    padding-top: 1rem;
  }

  .toolbar-grid {
    grid-template-columns: 1fr;
  }

  .card {
    padding: 1rem;
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
