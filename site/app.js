async function loadCatalog() {
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
