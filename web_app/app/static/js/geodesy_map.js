// static/js/geodesy_map.js

(() => {
  const EP = window.GEODESY?.endpoints;
  if (!EP || typeof L === "undefined") return;

  const codeColors = {
    SU: "#1f77b4",
    FX: "#ff7f0e",
    EP: "#2ca02c",
    FO: "#d62728",
    NI: "#9467bd",
    PF: "#8c564b",
    FI: "#e377c2",
    PR: "#17becf",
    SP: "#7f7f7f",
    "": "#111111",
    null: "#111111",
    undefined: "#111111"
  };

  let map = null;
  let layerPts = null;
  let layerPolys = null;
  let layerPhotos = null;
  let reloadTimer = null;
  let reloadGeneration = 0;
  let initialized = false;
  let modalPage = 1;
  let modalRows = new Map();

  const modalPageSize = 25;

  function byId(id) {
    return document.getElementById(id);
  }

  function fieldValue(id) {
    return byId(id)?.value || "";
  }

  function isChecked(id) {
    return Boolean(byId(id)?.checked);
  }

  function escapeHtml(value) {
    const text = String(value ?? "");
    const chars = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    };
    return text.replace(/[&<>"']/g, (ch) => chars[ch]);
  }

  function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
  }

  function showEditError(error, fallback) {
    const el = byId("editErr");
    if (!el) {
      alert(error?.message || fallback);
      return;
    }
    el.textContent = error?.message || fallback;
    el.classList.remove("d-none");
  }

  async function requestJson(url, options = {}) {
    const method = (options.method || "GET").toUpperCase();
    const headers = new Headers(options.headers || {});
    headers.set("Accept", "application/json");

    if (method !== "GET" && method !== "HEAD") {
      const token = csrfToken();
      if (token) headers.set("X-CSRFToken", token);
      headers.set("X-Requested-With", "XMLHttpRequest");
    }

    const res = await fetch(url, {
      ...options,
      method,
      headers,
      credentials: "same-origin"
    });

    const text = await res.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (_e) {
        data = null;
      }
    }

    if (!res.ok) {
      throw new Error(data?.error || data?.description || text || `Request failed (${res.status})`);
    }

    return data || {};
  }

  function getFilters() {
    return {
      code: fieldValue("filterCode"),
      q: fieldValue("filterQ"),
      id_from: fieldValue("filterIdFrom"),
      id_to: fieldValue("filterIdTo")
    };
  }

  function buildBboxParam() {
    const b = map.getBounds();
    const sw = b.getSouthWest();
    const ne = b.getNorthEast();
    return `${sw.lng},${sw.lat},${ne.lng},${ne.lat}`;
  }

  async function fetchGeoJSON(url, params) {
    const qs = new URLSearchParams(params);
    return requestJson(`${url}?${qs.toString()}`);
  }

  function removeLayer(layer) {
    if (layer && map?.hasLayer(layer)) {
      map.removeLayer(layer);
    }
  }

  function replaceLayer(oldLayer, newLayer) {
    removeLayer(oldLayer);
    newLayer.addTo(map);
    return newLayer;
  }

  function scheduleReload() {
    if (reloadTimer) clearTimeout(reloadTimer);
    reloadTimer = setTimeout(() => {
      reloadTimer = null;
      reloadAll();
    }, 200);
  }

  async function reloadPoints(generation) {
    const bbox = buildBboxParam();
    const f = getFilters();
    const gj = await fetchGeoJSON(EP.geopts, {
      bbox,
      code: f.code,
      q: f.q,
      id_from: f.id_from,
      id_to: f.id_to,
      limit: 5000
    });
    if (generation !== reloadGeneration) return;

    layerPts = replaceLayer(layerPts, L.geoJSON(gj, {
      pointToLayer: (feature, latlng) => {
        const code = feature?.properties?.code || "";
        const color = codeColors[code] || "#111111";
        return L.circleMarker(latlng, {
          radius: 5,
          weight: 1,
          fillOpacity: 0.85,
          color
        });
      },
      onEachFeature: (feature, layer) => {
        const p = feature.properties || {};
        layer.bindPopup(`
          <div>
            <strong>ID:</strong> ${escapeHtml(p.id_pts)}<br>
            <strong>Code:</strong> ${escapeHtml(p.code)}<br>
            <strong>Notes:</strong> ${escapeHtml(p.notes)}
          </div>
        `);
      }
    }));
  }

  async function reloadPolygons(generation) {
    if (generation !== reloadGeneration) return;
    if (!isChecked("chkPolys")) {
      removeLayer(layerPolys);
      layerPolys = null;
      return;
    }

    const bbox = buildBboxParam();
    const gj = await fetchGeoJSON(EP.polys, { bbox, limit: 2000 });
    if (generation !== reloadGeneration) return;

    layerPolys = replaceLayer(layerPolys, L.geoJSON(gj, {
      style: () => ({ weight: 2, fillOpacity: 0.05 }),
      onEachFeature: (feature, layer) => {
        const name = feature?.properties?.polygon_name || "";
        layer.bindPopup(`<strong>Polygon:</strong> ${escapeHtml(name)}`);
      }
    }));
  }

  async function reloadPhotos(generation) {
    if (generation !== reloadGeneration) return;
    if (!isChecked("chkPhotos")) {
      removeLayer(layerPhotos);
      layerPhotos = null;
      return;
    }

    const bbox = buildBboxParam();
    const gj = await fetchGeoJSON(EP.photos, { bbox, limit: 5000 });
    if (generation !== reloadGeneration) return;

    layerPhotos = replaceLayer(layerPhotos, L.geoJSON(gj, {
      pointToLayer: (_feature, latlng) => {
        return L.circleMarker(latlng, {
          radius: 4,
          weight: 1,
          fillOpacity: 0.8
        });
      },
      onEachFeature: (feature, layer) => {
        const p = feature?.properties || {};
        layer.bindPopup(`
          <strong>Photo:</strong> ${escapeHtml(p.id_foto)}<br>
          ${escapeHtml(p.file_name)}<br>
          alt: ${escapeHtml(p.gps_alt)}
        `);
      }
    }));
  }

  async function reloadAll() {
    if (!map) return;
    const generation = ++reloadGeneration;
    try {
      await Promise.all([
        reloadPoints(generation),
        reloadPolygons(generation),
        reloadPhotos(generation)
      ]);
    } catch (e) {
      console.error("reloadAll failed", e);
    }
  }

  function appendTextCell(row, value) {
    const cell = document.createElement("td");
    cell.textContent = value ?? "";
    row.appendChild(cell);
    return cell;
  }

  function actionButton(label, action, id, className) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.dataset.action = action;
    button.dataset.id = id;
    button.textContent = label;
    return button;
  }

  async function modalReload() {
    const qs = new URLSearchParams({
      q: fieldValue("modalQ"),
      id_from: fieldValue("modalFrom"),
      id_to: fieldValue("modalTo"),
      page: modalPage,
      limit: modalPageSize
    });
    const data = await requestJson(`${EP.list}?${qs.toString()}`);
    if (!data.ok) throw new Error(data.error || "list failed");

    const tb = byId("geoptsTbody");
    tb.textContent = "";
    modalPage = Number(data.page) || 1;
    modalRows = new Map();

    for (const r of data.rows || []) {
      modalRows.set(String(r.id_pts), r);
      const tr = document.createElement("tr");
      appendTextCell(tr, r.id_pts);
      appendTextCell(tr, r.x);
      appendTextCell(tr, r.y);
      appendTextCell(tr, r.h);
      appendTextCell(tr, r.code);
      appendTextCell(tr, r.notes);

      const actions = document.createElement("td");
      actions.appendChild(actionButton("Edit", "edit", r.id_pts, "btn btn-sm btn-outline-primary me-1"));
      actions.appendChild(actionButton("Delete", "del", r.id_pts, "btn btn-sm btn-outline-danger"));
      tr.appendChild(actions);
      tb.appendChild(tr);
    }

    const total = Number(data.total) || 0;
    const totalPages = Number(data.total_pages) || 1;
    const first = total ? ((modalPage - 1) * modalPageSize) + 1 : 0;
    const last = total ? first + (data.rows || []).length - 1 : 0;
    byId("geoptsPageSummary").textContent = total ? `Showing ${first}-${last} of ${total}` : "0 points";
    byId("geoptsPageLabel").textContent = `Page ${modalPage} of ${totalPages}`;
    byId("btnGeoptsPrev").disabled = modalPage <= 1;
    byId("btnGeoptsNext").disabled = modalPage >= totalPages;
  }

  async function openPointById(id) {
    const qs = new URLSearchParams({
      id_from: id,
      id_to: id,
      limit: 1
    });
    const data = await requestJson(`${EP.list}?${qs.toString()}`);
    const row = (data.rows || []).find((r) => String(r.id_pts) === String(id));
    if (row) openEdit(row);
  }

  async function doDelete(id) {
    if (!confirm(`Delete point ID ${id}?`)) return;
    const data = await requestJson(`${EP.delBase}/${id}`, { method: "POST" });
    if (!data.ok) throw new Error(data.error || "delete failed");
    await modalReload();
    await reloadAll();
  }

  function openEdit(row) {
    byId("editErr").classList.add("d-none");
    byId("editId").value = row.id_pts;
    byId("editX").value = row.x;
    byId("editY").value = row.y;
    byId("editH").value = row.h;
    byId("editCode").value = row.code || "";
    byId("editNotes").value = row.notes || "";

    const modal = new bootstrap.Modal(byId("editPointModal"));
    modal.show();
  }

  async function saveEdit() {
    const id = fieldValue("editId");
    const payload = {
      x: fieldValue("editX"),
      y: fieldValue("editY"),
      h: fieldValue("editH"),
      code: fieldValue("editCode"),
      notes: fieldValue("editNotes")
    };

    const data = await requestJson(`${EP.updBase}/${id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!data.ok) {
      showEditError(new Error(data.error || "update failed"), "Update failed.");
      return;
    }

    const modal = bootstrap.Modal.getInstance(byId("editPointModal"));
    if (modal) modal.hide();
    await modalReload();
    await reloadAll();
  }

  async function setInitialView() {
    try {
      const data = await requestJson(EP.extent);

      if (data.ok && data.bbox) {
        const [minx, miny, maxx, maxy] = data.bbox;
        const bounds = L.latLngBounds(
          [miny, minx],
          [maxy, maxx]
        );
        map.fitBounds(bounds, { padding: [20, 20] });
        return;
      }
    } catch (e) {
      console.error("extent fetch failed", e);
    }

    map.setView([49.0, 15.0], 6);
  }

  function bindMapEvents() {
    map.on("moveend", scheduleReload);

    byId("chkPolys")?.addEventListener("change", reloadAll);
    byId("chkPhotos")?.addEventListener("change", reloadAll);
    byId("btnReload")?.addEventListener("click", reloadAll);
    byId("filterCode")?.addEventListener("change", reloadAll);
    byId("filterQ")?.addEventListener("input", scheduleReload);
    byId("filterIdFrom")?.addEventListener("input", scheduleReload);
    byId("filterIdTo")?.addEventListener("input", scheduleReload);
  }

  function bindModalEvents() {
    byId("geoptsModal")?.addEventListener("shown.bs.modal", () => {
      modalPage = 1;
      modalReload().catch(console.error);
    });
    byId("btnModalReload")?.addEventListener("click", () => {
      modalPage = 1;
      modalReload().catch(console.error);
    });
    byId("btnGeoptsPrev")?.addEventListener("click", () => {
      if (modalPage <= 1) return;
      modalPage -= 1;
      modalReload().catch(console.error);
    });
    byId("btnGeoptsNext")?.addEventListener("click", () => {
      modalPage += 1;
      modalReload().catch(console.error);
    });
    byId("geoptsTbody")?.addEventListener("click", async (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;

      const id = btn.dataset.id;
      const action = btn.dataset.action;
      if (!id) return;

      if (action === "del") {
        await doDelete(id).catch((error) => {
          console.error(error);
          alert(error?.message || "Delete failed.");
        });
        return;
      }

      if (action === "edit") {
        const row = modalRows.get(String(id));
        if (row) {
          openEdit(row);
        } else {
          await openPointById(id);
        }
      }
    });
    byId("btnSaveEdit")?.addEventListener("click", () => {
      saveEdit().catch((error) => {
        console.error(error);
        showEditError(error, "Update failed.");
      });
    });
  }

  async function initMap() {
    if (initialized) return;
    initialized = true;

    const container = byId("geodesyMap");
    if (!container) return;

    map = L.map(container);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 20,
      referrerPolicy: "strict-origin-when-cross-origin",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);

    await setInitialView();
    bindMapEvents();
    bindModalEvents();
    await reloadAll();

    const requestedPoint = new URLSearchParams(window.location.search).get("edit_geopt");
    if (requestedPoint) {
      await openPointById(requestedPoint);
    }
  }

  window.addEventListener("load", () => {
    initMap().catch(console.error);
  });
})();
