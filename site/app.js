function escapeHtml(value) {
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

  const state = {
    mode: "tools",
    selectedDatasetChip: "",
  };

  const sourceFilter = document.getElementById("sourceFilter");
  const tagFilter = document.getElementById("tagFilter");
  const tagFilterControl = document.getElementById("tagFilterControl");
  const datasetChipFilterBlock = document.getElementById("datasetChipFilterBlock");
  const datasetCategoryChips = document.getElementById("datasetCategoryChips");
  const clearDatasetChipFilter = document.getElementById("clearDatasetChipFilter");
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

  function refreshDatasetChips() {
    if (!datasetCategoryChips) return;
    datasetCategoryChips.innerHTML = "";

    const items = getCurrentItems();
    const tags = uniqueSorted(items.flatMap(item => item.tags || []));

    for (const tag of tags) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "filter-chip";
      button.textContent = tag;
      button.title = tag;

      if (state.selectedDatasetChip === tag) {
        button.classList.add("active");
      }

      button.addEventListener("click", () => {
        state.selectedDatasetChip = state.selectedDatasetChip === tag ? "" : tag;
        refreshDatasetChips();
        update();
      });

      datasetCategoryChips.appendChild(button);
    }

    if (clearDatasetChipFilter) {
      clearDatasetChipFilter.classList.toggle("hidden", !state.selectedDatasetChip);
    }
  }

  function refreshFilters() {
    const items = getCurrentItems();
    const sources = uniqueSorted(items.map(item => getItemSource(item, state.mode)));

    populateSelect(sourceFilter, sources, "All sources");

    if (state.mode === "datasets") {
      if (tagFilterControl) tagFilterControl.classList.add("hidden");
      if (datasetChipFilterBlock) datasetChipFilterBlock.classList.remove("hidden");
      refreshDatasetChips();
    } else {
      const tags = uniqueSorted(items.flatMap(item => getItemTags(item, state.mode)));
      populateSelect(tagFilter, tags, "All categories");
      if (tagFilterControl) tagFilterControl.classList.remove("hidden");
      if (datasetChipFilterBlock) datasetChipFilterBlock.classList.add("hidden");
    }
  }

  function matchesFilters(item, filters, mode) {
    const query = filters.query.trim().toLowerCase();
    const blob = mode === "datasets" ? getDatasetSearchBlob(item) : getToolSearchBlob(item);

    if (query && !blob.includes(query)) return false;
    if (filters.source && getItemSource(item, mode) !== filters.source) return false;

    if (mode === "datasets") {
      if (state.selectedDatasetChip) {
        const tags = item.tags || [];
        if (!tags.includes(state.selectedDatasetChip)) return false;
      }
    } else {
      if (filters.tag) {
        const tags = getItemTags(item, mode);
        if (!tags.includes(filters.tag)) return false;
      }
    }

    return true;
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
    state.selectedDatasetChip = "";

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
    state.selectedDatasetChip = "";
    if (search) search.value = "";
    if (sourceFilter) sourceFilter.value = "";
    if (tagFilter) tagFilter.value = "";
    if (sortBy) sortBy.value = "popularity";
    refreshFilters();
    update();
  });

  addSafeListener(clearDatasetChipFilter, "click", () => {
    state.selectedDatasetChip = "";
    refreshDatasetChips();
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
