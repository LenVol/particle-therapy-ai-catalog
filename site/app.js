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
