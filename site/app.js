async function loadCatalog() {
  const response = await fetch("catalog.json");
  return await response.json();
}

function render(items) {
  const results = document.getElementById("results");
  const stats = document.getElementById("stats");
  stats.textContent = `${items.length} repositories`;

  results.innerHTML = items.map(item => {
    const cls = item.classification || {};
    const cats = (cls.categories || []).join(", ");
    const topics = (item.topics || []).join(", ");

    return `
      <article class="card">
        <h2><a href="${item.url}" target="_blank" rel="noopener noreferrer">${item.full_name}</a></h2>
        <p>${cls.summary || item.description || ""}</p>
        <p><strong>Platform:</strong> ${item.platform} | <strong>Stars:</strong> ${item.stars} | <strong>Type:</strong> ${cls.likely_tool_type || ""}</p>
        <p><strong>Categories:</strong> ${cats}</p>
        <p><strong>Topics:</strong> ${topics}</p>
      </article>
    `;
  }).join("");
}

loadCatalog().then(data => {
  let items = data;
  render(items);

  document.getElementById("search").addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase().trim();
    const filtered = items.filter(item => {
      const cls = item.classification || {};
      const blob = [
        item.full_name,
        item.description,
        (item.topics || []).join(" "),
        (cls.categories || []).join(" "),
        cls.summary || ""
      ].join(" ").toLowerCase();
      return blob.includes(q);
    });
    render(filtered);
  });
});
