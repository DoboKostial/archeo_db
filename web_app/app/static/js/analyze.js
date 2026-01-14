// app/static/js/analyze.js

document.addEventListener("DOMContentLoaded", async () => {
  const host = document.getElementById("statsCharts");
  if (!host) return;

  const url = host.dataset.statsUrl;
  if (!url) return;

  // sanity: Chart.js loaded?
  if (typeof Chart === "undefined") {
    console.error("Chart.js is not loaded (Chart is undefined). Check chart.umd.min.js include.");
    host.innerHTML = `
      <div class="col-12">
        <div class="alert alert-danger mb-0">
          Chart.js is not loaded (Chart is undefined).
        </div>
      </div>`;
    return;
  }

  let payload;
  try {
    const resp = await fetch(url, { headers: { "Accept": "application/json" } });
    if (!resp.ok) throw new Error(`stats.json HTTP ${resp.status}`);
    payload = await resp.json();
  } catch (e) {
    console.error("Failed to load stats:", e);
    host.innerHTML = `
      <div class="col-12">
        <div class="alert alert-danger mb-0">
          Failed to load statistics: ${String(e)}
        </div>
      </div>`;
    return;
  }

  const charts = (payload && payload.charts) ? payload.charts : [];
  if (!charts.length) {
    host.innerHTML = `
      <div class="col-12">
        <div class="alert alert-warning mb-0">
          No statistics available (no charts returned).
        </div>
      </div>`;
    return;
  }

  // helpers
  const isFiniteNumber = (v) => Number.isFinite(v) && !Number.isNaN(v);

  const hasAnyData = (labels, values) => {
    if (!Array.isArray(labels) || !Array.isArray(values)) return false;
    if (labels.length === 0 || values.length === 0) return false;
    // require same length (otherwise chart is nonsense)
    if (labels.length !== values.length) return false;
    // require at least one positive value
    const sum = values.reduce((acc, x) => acc + (isFiniteNumber(x) ? x : 0), 0);
    return sum > 0;
  };

  // build cards + canvases / "no data" blocks
  host.innerHTML = "";

  charts.forEach((c, idx) => {
    const title = c && c.title ? c.title : ("Chart " + (idx + 1));
    const labels = Array.isArray(c?.labels) ? c.labels : [];
    const valuesRaw = Array.isArray(c?.values) ? c.values : [];

    // normalize values -> numbers (Chart.js likes numbers)
    const values = valuesRaw.map(v => {
      const n = Number(v);
      return Number.isFinite(n) ? n : 0;
    });

    const col = document.createElement("div");
    // 4 charts per row on xl
    col.className = "col-12 col-md-6 col-xl-3";

    // If chart has no usable data -> show "No data" card, no Chart.js call
    if (!hasAnyData(labels, values)) {
      col.innerHTML = `
        <div class="card h-100">
          <div class="card-body">
            <h6 class="mb-2">${title}</h6>
            <div class="alert alert-secondary mb-0">
              No data.
            </div>
          </div>
        </div>
      `;
      host.appendChild(col);
      return;
    }

    // normal chart card
    col.innerHTML = `
      <div class="card h-100">
        <div class="card-body">
          <h6 class="mb-2">${title}</h6>
          <div style="height:220px">
            <canvas id="chart_${idx}"></canvas>
          </div>
        </div>
      </div>
    `;
    host.appendChild(col);

    const canvas = col.querySelector(`#chart_${idx}`);

    // deterministic palette
    const colors = labels.map((_, i) => `hsl(${(i * 360 / Math.max(labels.length, 1)) % 360}, 70%, 60%)`);

    new Chart(canvas.getContext("2d"), {
      type: "pie",
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: colors,
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom" }
        }
      }
    });
  });
});
