document.addEventListener("DOMContentLoaded", async () => {
  const host = document.getElementById("statsCharts");
  if (!host) return;

  const url = host.dataset.statsUrl;
  if (!url) return;

  // sanity: Chart.js loaded?
  if (typeof Chart === "undefined") {
    console.error("Chart.js is not loaded (Chart is undefined). Check chart.umd.min.js include.");
    host.innerHTML = `<div class="col-12"><div class="alert alert-danger mb-0">
      Chart.js is not loaded (Chart is undefined).
    </div></div>`;
    return;
  }

  let payload;
  try {
    const resp = await fetch(url, { headers: { "Accept": "application/json" } });
    if (!resp.ok) throw new Error(`stats.json HTTP ${resp.status}`);
    payload = await resp.json();
  } catch (e) {
    console.error("Failed to load stats:", e);
    host.innerHTML = `<div class="col-12"><div class="alert alert-danger mb-0">
      Failed to load statistics: ${String(e)}
    </div></div>`;
    return;
  }

  const charts = (payload && payload.charts) ? payload.charts : [];
  if (!charts.length) {
    host.innerHTML = `<div class="col-12"><div class="alert alert-warning mb-0">
      No statistics available.
    </div></div>`;
    return;
  }

  // build cards + canvases
  host.innerHTML = "";
  charts.forEach((c, idx) => {
    const col = document.createElement("div");
    col.className = "col-12 col-md-6 col-lg-4 col-xl-3";

    col.innerHTML = `
      <div class="card h-100">
        <div class="card-body">
          <div class="d-flex align-items-start justify-content-between gap-2">
            <h6 class="mb-2">${c.title || ("Chart " + (idx + 1))}</h6>
          </div>
          <div style="height:200px">
            <canvas id="chart_${idx}"></canvas>
          </div>
        </div>
      </div>
    `;

    host.appendChild(col);

    const canvas = col.querySelector(`#chart_${idx}`);
    const labels = Array.isArray(c.labels) ? c.labels : [];
    const values = Array.isArray(c.values) ? c.values : [];

    // simple palette (deterministic)
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
