function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function loadCatalog() {
  const response = await fetch("catalog.json");
  if (!response.ok) {
    throw new Error(`Failed to load catalog.json: ${response.status}`);
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

function buildStats(items, totalItems) {
  const totalStars = items.reduce((sum, item) => sum + (item.stars || 0), 0);

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
  `;
}

function getSearchBlob(item) {
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

function sortItems(items, sortBy) {
  const sorted = [...items];

  sorted.sort((a, b) => {
    if (sortBy === "updated") {
      return (b.updated_at || "").localeCompare(a.updated_at || "");
    }
    if (sortBy === "name") {
      return (a.full_name || "").localeCompare(b.full_name || "");
    }
    return (b.stars || 0) - (a.stars || 0);
  });

  return sorted;
}

function matchesFilters(item, filters) {
  const cls = item.classification || {};
  const query = filters.query.trim().toLowerCase();

  if (query && !getSearchBlob(item).includes(query)) return false;
  if (filters.platform && (item.platform || "") !== filters.platform) return false;
  if (filters.category && !(cls.categories || []).includes(filters.category)) return false;

  return true;
}

function renderCards(items) {
  const results = document.getElementById("results");
  if (!results) return;

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
    const warnings = cls.warnings || [];
    const topics = item.topics || [];

    return `
      <a class="repo-card" href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer" aria-label="Open ${escapeHtml(item.full_name || "")}">
        <div class="repo-card-top">
          <div>
            <div class="repo-kicker">${escapeHtml(item.platform || "unknown")} · ${escapeHtml(cls.likely_tool_type || "unclear")}</div>
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
  }).join("");
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
  if (el) {
    el.addEventListener(eventName, handler);
  }
}

async function main() {
  const rawItems = await loadCatalog();

  const platformFilter = document.getElementById("platformFilter");
  const categoryFilter = document.getElementById("categoryFilter");
  const sortBy = document.getElementById("sortBy");
  const search = document.getElementById("search");
  const stats = document.getElementById("stats");
  const resetButton = document.getElementById("resetFilters");
  const heroRepoCount = document.getElementById("heroRepoCount");
  const heroVisibleCount = document.getElementById("heroVisibleCount");

  if (!stats) {
    throw new Error("Missing required page element: stats");
  }

  if (heroRepoCount) {
    heroRepoCount.textContent = String(rawItems.length);
  }

  const platforms = uniqueSorted(rawItems.map(item => item.platform));
  const categories = uniqueSorted(rawItems.flatMap(item => item.classification?.categories || []));

  populateSelect(platformFilter, platforms, "All platforms");
  populateSelect(categoryFilter, categories, "All categories");

  function update() {
    const filters = {
      query: search?.value || "",
      platform: platformFilter?.value || "",
      category: categoryFilter?.value || ""
    };

    const filtered = rawItems.filter(item => matchesFilters(item, filters));
    const sorted = sortItems(filtered, sortBy?.value || "stars");

    if (heroVisibleCount) {
      heroVisibleCount.textContent = String(sorted.length);
    }

    stats.innerHTML = buildStats(sorted, rawItems.length);
    renderCards(sorted);
  }

  [platformFilter, categoryFilter, sortBy, search].forEach(el => {
    addSafeListener(el, "input", update);
    addSafeListener(el, "change", update);
  });

  addSafeListener(resetButton, "click", () => {
    if (search) search.value = "";
    if (platformFilter) platformFilter.value = "";
    if (categoryFilter) categoryFilter.value = "";
    if (sortBy) sortBy.value = "stars";
    update();
  });

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
