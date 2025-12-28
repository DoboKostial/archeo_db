// static/js/geodesy_map.js

(() => {
  const EP = window.GEODESY?.endpoints;
  if (!EP) return;

  const codeColors = {
    SU: "#1f77b4",
    FX: "#ff7f0e",
    EP: "#2ca02c",
    FP: "#d62728",
    NI: "#9467bd",
    PF: "#8c564b",
    SP: "#7f7f7f",
    "":  "#111111",
    null: "#111111",
    undefined: "#111111"
  };

  let map = null;
  let layerPts = L.geoJSON(null);
  let layerPolys = L.geoJSON(null);
  let layerPhotos = L.geoJSON(null);

  let _timer = null;

  function getFilters() {
    const code = document.getElementById("filterCode").value || "";
    const q = document.getElementById("filterQ").value || "";
    const id_from = document.getElementById("filterIdFrom").value || "";
    const id_to = document.getElementById("filterIdTo").value || "";
    return { code, q, id_from, id_to };
  }

  function buildBboxParam() {
    const b = map.getBounds();
    const sw = b.getSouthWest();
    const ne = b.getNorthEast();
    return `${sw.lng},${sw.lat},${ne.lng},${ne.lat}`;
  }

  async function fetchGeoJSON(url, params) {
    const qs = new URLSearchParams(params);
    const res = await fetch(`${url}?${qs.toString()}`);
    if (!res.ok) throw new Error(await res.text());
    return await res.json();
  }

  function scheduleReload() {
    if (_timer) clearTimeout(_timer);
    _timer = setTimeout(reloadAll, 200);
  }

  async function reloadPoints() {
    const bbox = buildBboxParam();
    const f = getFilters();

    const params = {
      bbox,
      code: f.code || "",
      q: f.q || "",
      id_from: f.id_from || "",
      id_to: f.id_to || "",
      limit: 5000
    };

    const gj = await fetchGeoJSON(EP.geopts, params);
    layerPts.clearLayers();

    layerPts = L.geoJSON(gj, {
      pointToLayer: (feature, latlng) => {
        const code = feature?.properties?.code || "";
        const color = codeColors[code] || "#111111";
        return L.circleMarker(latlng, {
          radius: 5,
          weight: 1,
          fillOpacity: 0.85,
          color: color
        });
      },
      onEachFeature: (feature, layer) => {
        const p = feature.properties || {};
        const html = `
          <div>
            <strong>ID:</strong> ${p.id_pts ?? ""}<br>
            <strong>Code:</strong> ${p.code ?? ""}<br>
            <strong>Notes:</strong> ${(p.notes ?? "")}
          </div>
        `;
        layer.bindPopup(html);
      }
    });

    layerPts.addTo(map);
  }

  async function reloadPolygons() {
    const chk = document.getElementById("chkPolys").checked;
    if (!chk) {
      layerPolys.clearLayers();
      return;
    }

    const bbox = buildBboxParam();
    const gj = await fetchGeoJSON(EP.polys, { bbox, limit: 2000 });

    layerPolys.clearLayers();
    layerPolys = L.geoJSON(gj, {
      style: () => ({ weight: 2, fillOpacity: 0.05 }),
      onEachFeature: (feature, layer) => {
        const name = feature?.properties?.polygon_name || "";
        layer.bindPopup(`<strong>Polygon:</strong> ${name}`);
      }
    });

    layerPolys.addTo(map);
  }

  async function reloadPhotos() {
    const chk = document.getElementById("chkPhotos").checked;
    if (!chk) {
      layerPhotos.clearLayers();
      return;
    }

    const bbox = buildBboxParam();
    const gj = await fetchGeoJSON(EP.photos, { bbox, limit: 5000 });

    layerPhotos.clearLayers();
    layerPhotos = L.geoJSON(gj, {
      pointToLayer: (feature, latlng) => {
        return L.circleMarker(latlng, {
          radius: 4,
          weight: 1,
          fillOpacity: 0.8
        });
      },
      onEachFeature: (feature, layer) => {
        const p = feature?.properties || {};
        layer.bindPopup(`<strong>Photo:</strong> ${p.id_foto ?? ""}<br>${p.file_name ?? ""}<br>alt: ${p.gps_alt ?? ""}`);
      }
    });

    layerPhotos.addTo(map);
  }

  async function reloadAll() {
    try {
      await reloadPoints();
      await reloadPolygons();
      await reloadPhotos();
    } catch (e) {
      console.error("reloadAll failed", e);
    }
  }

  // ----- Modal listing (CRUD) -----

  async function modalReload() {
    const q = document.getElementById("modalQ").value || "";
    const id_from = document.getElementById("modalFrom").value || "";
    const id_to = document.getElementById("modalTo").value || "";

    const qs = new URLSearchParams({ q, id_from, id_to, limit: 1000 });
    const res = await fetch(`${EP.list}?${qs.toString()}`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "list failed");

    const tb = document.getElementById("geoptsTbody");
    tb.innerHTML = "";

    for (const r of data.rows) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${r.id_pts}</td>
        <td>${r.x}</td>
        <td>${r.y}</td>
        <td>${r.h}</td>
        <td>${r.code ?? ""}</td>
        <td>${r.notes ?? ""}</td>
        <td>
          <button class="btn btn-sm btn-outline-primary me-1" data-action="edit" data-id="${r.id_pts}">Edit</button>
          <button class="btn btn-sm btn-outline-danger" data-action="del" data-id="${r.id_pts}">Delete</button>
        </td>
      `;
      tb.appendChild(tr);
    }
  }

  async function doDelete(id) {
    if (!confirm(`Smazat bod ID ${id}?`)) return;
    const res = await fetch(`${EP.delBase}/${id}`, { method: "POST" });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "delete failed");
    await modalReload();
    await reloadAll();
  }

  function openEdit(row) {
    document.getElementById("editErr").classList.add("d-none");
    document.getElementById("editId").value = row.id_pts;
    document.getElementById("editX").value = row.x;
    document.getElementById("editY").value = row.y;
    document.getElementById("editH").value = row.h;
    document.getElementById("editCode").value = row.code || "";
    document.getElementById("editNotes").value = row.notes || "";

    const m = new bootstrap.Modal(document.getElementById("editPointModal"));
    m.show();
  }

  async function saveEdit() {
    const id = document.getElementById("editId").value;
    const payload = {
      x: document.getElementById("editX").value,
      y: document.getElementById("editY").value,
      h: document.getElementById("editH").value,
      code: document.getElementById("editCode").value,
      notes: document.getElementById("editNotes").value
    };

    const res = await fetch(`${EP.updBase}/${id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    if (!data.ok) {
      const el = document.getElementById("editErr");
      el.textContent = data.error || "update failed";
      el.classList.remove("d-none");
      return;
    }

    bootstrap.Modal.getInstance(document.getElementById("editPointModal")).hide();
    await modalReload();
    await reloadAll();
  }


// This has to be ABOVE initMap (same level as other functions)
async function setInitialView() {
  try {
    const res = await fetch(EP.extent);
    const data = await res.json();

    if (data.ok && data.bbox) {
      const [minx, miny, maxx, maxy] = data.bbox;

      const bounds = L.latLngBounds(
        [miny, minx],   // SW (lat, lon)
        [maxy, maxx]    // NE (lat, lon)
      );

      map.fitBounds(bounds, { padding: [20, 20] });
      return;
    }
  } catch (e) {
    console.error("extent fetch failed", e);
  }

  // fallback when no points exist or request fails
  map.setView([49.0, 15.0], 6);
}


// ----- init -----
async function initMap() {
  map = L.map("geodesyMap");
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 20,
    attribution: "&copy; OpenStreetMap contributors"
  }).addTo(map);

  // center map to points extent (or fallback)
  await setInitialView();

  map.on("moveend", scheduleReload);

  document.getElementById("chkPolys").addEventListener("change", reloadAll);
  document.getElementById("chkPhotos").addEventListener("change", reloadAll);
  document.getElementById("btnReload").addEventListener("click", reloadAll);

  document.getElementById("filterCode").addEventListener("change", reloadAll);
  document.getElementById("filterQ").addEventListener("input", scheduleReload);
  document.getElementById("filterIdFrom").addEventListener("input", scheduleReload);
  document.getElementById("filterIdTo").addEventListener("input", scheduleReload);

  reloadAll();
}

window.addEventListener("load", () => {
  initMap().catch(console.error);
});


  // Modal events
  document.getElementById("geoptsModal").addEventListener("shown.bs.modal", () => {
    modalReload().catch(console.error);
  });
  document.getElementById("btnModalReload").addEventListener("click", () => {
    modalReload().catch(console.error);
  });

  document.getElementById("geoptsTbody").addEventListener("click", async (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    const id = btn.getAttribute("data-id");
    const action = btn.getAttribute("data-action");
    if (!id) return;

    if (action === "del") {
      await doDelete(id).catch(console.error);
    } else if (action === "edit") {
      // load rows again quickly and pick one (simple approach)
      const q = document.getElementById("modalQ").value || "";
      const id_from = document.getElementById("modalFrom").value || "";
      const id_to = document.getElementById("modalTo").value || "";
      const qs = new URLSearchParams({ q, id_from, id_to, limit: 1000 });
      const res = await fetch(`${EP.list}?${qs.toString()}`);
      const data = await res.json();
      const row = (data.rows || []).find(r => String(r.id_pts) === String(id));
      if (row) openEdit(row);
    }
  });

  document.getElementById("btnSaveEdit").addEventListener("click", () => {
    saveEdit().catch(console.error);
  });

  window.addEventListener("load", initMap);
})();
