// static/js/photograms.js
(function () {
  const debounce = (fn, ms) => {
    let t = null;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  };

  const el = (html) => {
    const t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstChild;
  };

  // ---------------------------
  // SearchSelect (same as photos.js) – idempotent init
  // ---------------------------
  function initSearchSelect(container) {
    if (container.dataset.ssInit === "1") return;
    container.dataset.ssInit = "1";

    const mode = container.dataset.mode || "multi";
    const endpoint = container.dataset.endpoint;
    const hiddenName = container.dataset.hiddenName;
    const placeholder = container.dataset.placeholder || "Search...";

    container.classList.add("position-relative");

    const input = el(`<input type="text" class="form-control" placeholder="${placeholder}">`);
    const dropdown = el(
      `<div class="list-group position-absolute w-100 shadow-sm"
            style="z-index: 50; display:none; max-height:220px; overflow:auto;"></div>`
    );
    const chips = el(`<div class="mt-2 d-flex flex-wrap gap-1"></div>`);

    container.appendChild(input);
    container.appendChild(dropdown);
    container.appendChild(chips);

    const clearDropdown = () => {
      dropdown.style.display = "none";
      dropdown.innerHTML = "";
    };

    const addChip = (id, text) => {
      if (mode === "single") {
        chips.innerHTML = "";
        [...container.querySelectorAll(`input[type="hidden"][name="${hiddenName}"]`)].forEach((n) => n.remove());
      } else {
        const exists = [...container.querySelectorAll(`input[type="hidden"][name="${hiddenName}"]`)]
          .some((n) => n.value === String(id));
        if (exists) return;
      }

      const chip = el(`
        <span class="badge text-bg-secondary d-inline-flex align-items-center gap-2">
          <span class="chip-text"></span>
          <button type="button" class="btn btn-sm btn-light py-0 px-1">x</button>
        </span>
      `);
      chip.querySelector(".chip-text").textContent = text;

      const hidden = el(`<input type="hidden" name="${hiddenName}" value="${id}">`);

      chip.querySelector("button").addEventListener("click", () => {
        hidden.remove();
        chip.remove();
      });

      chips.appendChild(chip);
      container.appendChild(hidden);
    };

    const fetchItems = debounce(async () => {
      const q = input.value.trim();
      if (!q) {
        clearDropdown();
        return;
      }
      try {
        const url = new URL(endpoint, window.location.origin);
        url.searchParams.set("q", q);
        url.searchParams.set("limit", "20");
        url.searchParams.set("page", "1");

        const resp = await fetch(url.toString(), { credentials: "same-origin" });
        if (!resp.ok) throw new Error("search failed");
        const data = await resp.json();
        const results = data.results || [];

        dropdown.innerHTML = "";
        results.forEach((item) => {
          const a = el(`<button type="button" class="list-group-item list-group-item-action"></button>`);
          a.textContent = item.text;
          a.addEventListener("click", () => {
            addChip(item.id, item.text);
            input.value = "";
            clearDropdown();
          });
          dropdown.appendChild(a);
        });

        dropdown.style.display = results.length ? "block" : "none";
      } catch (e) {
        clearDropdown();
      }
    }, 250);

    input.addEventListener("input", fetchItems);
    document.addEventListener("click", (ev) => {
      if (!container.contains(ev.target)) clearDropdown();
    });

    container._searchSelect = {
      setSingle(id, text) { addChip(id, text); },
      setMulti(values) { values.forEach((v) => addChip(v.id, v.text)); },
      clear() {
        chips.innerHTML = "";
        [...container.querySelectorAll(`input[type="hidden"][name="${hiddenName}"]`)].forEach((n) => n.remove());
      },
    };
  }

  function initAllSearchSelect(root = document) {
    root.querySelectorAll(".search-select").forEach(initSearchSelect);
  }

  // ---------------------------
  // Upload blocks
  // ---------------------------
  const blocksWrap = document.getElementById("photogramBlocks");
  const tpl = document.getElementById("photogramBlockTemplate");
  const btnAdd = document.getElementById("btnAddBlock");
  const btnReset = document.getElementById("btnResetBlocks");
  let nextIdx = 0;

  function addRangeRow(rangesHost, idx) {
    const row = el(`
      <div class="row g-2 align-items-end range-row mt-2">
        <div class="col-5">
          <input type="number" class="form-control" name="geopt_from_${idx}[]" min="1" placeholder="FROM">
        </div>
        <div class="col-5">
          <input type="number" class="form-control" name="geopt_to_${idx}[]" min="1" placeholder="TO">
        </div>
        <div class="col-2 d-grid">
          <button type="button" class="btn btn-outline-danger btnRemoveRange">x</button>
        </div>
      </div>
    `);
    row.querySelector(".btnRemoveRange").addEventListener("click", () => row.remove());
    rangesHost.appendChild(row);
  }

  function addBlock() {
    const html = tpl.innerHTML.replaceAll("__IDX__", String(nextIdx));
    const node = el(html);

    // Replace name attributes
    node.querySelectorAll("[name]").forEach((n) => {
      n.name = n.name.replaceAll("___IDX__", "_" + nextIdx);
    });

    // Replace search-select hidden-name suffixes
    node.querySelectorAll(".search-select").forEach((ss) => {
      ss.dataset.hiddenName = ss.dataset.hiddenName.replaceAll("___IDX__", "_" + nextIdx);
    });

    node.querySelector(".btnRemoveBlock").addEventListener("click", () => node.remove());

    // ranges add button
    const rangesHost = node.querySelector(".geoptsRanges");
    const addBtn = node.querySelector(".btnAddRange");
    if (addBtn && rangesHost) {
      addBtn.addEventListener("click", () => addRangeRow(rangesHost, nextIdx));
    }

    blocksWrap.appendChild(node);
    initAllSearchSelect(node);

    nextIdx += 1;
  }

  if (btnAdd) btnAdd.addEventListener("click", addBlock);
  if (btnReset) btnReset.addEventListener("click", () => {
    blocksWrap.innerHTML = "";
    nextIdx = 0;
    addBlock();
  });

  if (blocksWrap && tpl) addBlock();
  initAllSearchSelect(document);

  // ---------------------------
  // Bulk selection
  // ---------------------------
  const bulkForm = document.getElementById("bulkForm");
  const bulkSelectedContainer = document.getElementById("bulkSelectedContainer");

  function renderBulkSelected() {
    bulkSelectedContainer.innerHTML = "";
    document.querySelectorAll(".photogram-check:checked").forEach((chk) => {
      bulkSelectedContainer.appendChild(el(`<input type="hidden" name="photogram_ids" value="${chk.value}">`));
    });
  }

  document.querySelectorAll(".photogram-check").forEach((chk) => chk.addEventListener("change", renderBulkSelected));

  const btnSelectAll = document.getElementById("btnSelectAll");
  const btnClear = document.getElementById("btnClearSelection");
  if (btnSelectAll) btnSelectAll.addEventListener("click", () => {
    document.querySelectorAll(".photogram-check").forEach((chk) => chk.checked = true);
    renderBulkSelected();
  });
  if (btnClear) btnClear.addEventListener("click", () => {
    document.querySelectorAll(".photogram-check").forEach((chk) => chk.checked = false);
    renderBulkSelected();
  });
  if (bulkForm) bulkForm.addEventListener("submit", () => renderBulkSelected());

  // ---------------------------
  // Edit / Delete modals
  // ---------------------------
  const modalEditEl = document.getElementById("modalEdit");
  const modalDeleteEl = document.getElementById("modalDelete");
  const editForm = document.getElementById("editForm");
  const deleteForm = document.getElementById("deleteForm");
  const editId = document.getElementById("editId");
  const deleteId = document.getElementById("deleteId");
  const editRanges = document.getElementById("editRanges");
  const btnEditAddRange = document.getElementById("btnEditAddRange");

  const bsEdit = modalEditEl ? new bootstrap.Modal(modalEditEl) : null;
  const bsDelete = modalDeleteEl ? new bootstrap.Modal(modalDeleteEl) : null;

  function addEditRangeRow(a = "", b = "") {
    const row = el(`
      <div class="row g-2 align-items-end mb-2 edit-range-row">
        <div class="col-5">
          <input type="number" class="form-control" name="geopt_from[]" min="1" placeholder="FROM" value="${a}">
        </div>
        <div class="col-5">
          <input type="number" class="form-control" name="geopt_to[]" min="1" placeholder="TO" value="${b}">
        </div>
        <div class="col-2 d-grid">
          <button type="button" class="btn btn-outline-danger btnRemoveRange">x</button>
        </div>
      </div>
    `);
    row.querySelector(".btnRemoveRange").addEventListener("click", () => row.remove());
    editRanges.appendChild(row);
  }

  if (btnEditAddRange) btnEditAddRange.addEventListener("click", () => addEditRangeRow());

  async function openEdit(idPhotogram) {
    const url = `/photograms/api/detail/${encodeURIComponent(idPhotogram)}`;
    const resp = await fetch(url, { credentials: "same-origin" });
    if (!resp.ok) return;
    const data = await resp.json();

    editId.textContent = data.id_photogram;
    editForm.action = `/photograms/edit/${encodeURIComponent(data.id_photogram)}`;

    editForm.querySelector('select[name="photogram_typ"]').value = data.photogram_typ;
    editForm.querySelector('input[name="notes"]').value = data.notes || "";

    // ref_sketch (single)
    const ssSketch = editForm.querySelector('.search-select[data-hidden-name="ref_sketch"]');
    ssSketch._searchSelect.clear();
    if (data.ref_sketch) ssSketch._searchSelect.setSingle(data.ref_sketch, data.ref_sketch);

    // photos from/to (single)
    const ssPF = editForm.querySelector('.search-select[data-hidden-name="ref_photo_from"]');
    ssPF._searchSelect.clear();
    if (data.ref_photo_from) ssPF._searchSelect.setSingle(data.ref_photo_from, data.ref_photo_from);

    const ssPT = editForm.querySelector('.search-select[data-hidden-name="ref_photo_to"]');
    ssPT._searchSelect.clear();
    if (data.ref_photo_to) ssPT._searchSelect.setSingle(data.ref_photo_to, data.ref_photo_to);

    // links
    const setMulti = (selector, values, prefix = "") => {
      const ss = editForm.querySelector(selector);
      ss._searchSelect.clear();
      ss._searchSelect.setMulti(values.map(v => ({ id: String(v), text: prefix ? `${prefix} ${v}` : String(v) })));
    };
    setMulti('.search-select[data-hidden-name="ref_sj"]', data.links.sj_ids, "SU");
    setMulti('.search-select[data-hidden-name="ref_polygon"]', data.links.polygon_names, "");
    setMulti('.search-select[data-hidden-name="ref_section"]', data.links.section_ids, "Section");

    // ranges
    editRanges.innerHTML = "";
    (data.geopts_ranges || []).forEach(r => addEditRangeRow(String(r.from), String(r.to)));

    bsEdit.show();
  }

  function openDelete(idPhotogram) {
    deleteId.textContent = idPhotogram;
    deleteForm.action = `/photograms/delete/${encodeURIComponent(idPhotogram)}`;
    bsDelete.show();
  }

  document.querySelectorAll(".btnEdit").forEach(btn => btn.addEventListener("click", () => openEdit(btn.dataset.id)));
  document.querySelectorAll(".btnDelete").forEach(btn => btn.addEventListener("click", () => openDelete(btn.dataset.id)));
})();
