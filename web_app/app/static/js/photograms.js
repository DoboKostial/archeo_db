// static/js/photograms.js
(function () {
  // ---------------------------
  // small helpers
  // ---------------------------
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

  const q = (root, sel) => (root ? root.querySelector(sel) : null);

  // safe set value
  const setVal = (root, sel, value) => {
    const n = q(root, sel);
    if (n) n.value = value ?? "";
  };

  // ---------------------------
  // SearchSelect component
  // data-mode="single|multi"
  // data-endpoint="..."
  // data-hidden-name="..."
  // ---------------------------
  function initSearchSelect(container) {
    const mode = container.dataset.mode || "multi";
    const endpoint = container.dataset.endpoint;
    const hiddenName = container.dataset.hiddenName;
    const placeholder = container.dataset.placeholder || "Search...";

    container.classList.add("position-relative");

    const input = el(`<input type="text" class="form-control" placeholder="${placeholder}">`);
    const dropdown = el(
      `<div class="list-group position-absolute w-100 shadow-sm" style="z-index: 50; display:none; max-height:220px; overflow:auto;"></div>`
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
        [...container.querySelectorAll(`input[type="hidden"][name="${hiddenName}"]`)].forEach(n => n.remove());
      } else {
        const exists = [...container.querySelectorAll(`input[type="hidden"][name="${hiddenName}"]`)]
          .some(n => n.value === String(id));
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
      const qq = input.value.trim();
      if (!qq) {
        clearDropdown();
        return;
      }
      try {
        const url = new URL(endpoint, window.location.origin);
        url.searchParams.set("q", qq);
        url.searchParams.set("limit", "20");
        url.searchParams.set("page", "1");

        const resp = await fetch(url.toString(), { credentials: "same-origin" });
        if (!resp.ok) throw new Error("search failed");
        const data = await resp.json();
        const results = data.results || [];

        dropdown.innerHTML = "";
        results.forEach(item => {
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
      setMulti(values) { values.forEach(v => addChip(v.id, v.text)); },
      clear() {
        chips.innerHTML = "";
        [...container.querySelectorAll(`input[type="hidden"][name="${hiddenName}"]`)].forEach(n => n.remove());
      }
    };
  }

  function initAllSearchSelect(root = document) {
    root.querySelectorAll(".search-select").forEach(initSearchSelect);
  }

  // init search-select everywhere (upload + bulk/filter + edit)
  initAllSearchSelect(document);

  // ---------------------------
  // Upload: add more file inputs
  // ---------------------------
  const btnAddFile = document.getElementById("btnAddFile");
  const extraFiles = document.getElementById("extraFiles");

  const makeFileRow = () => {
    const row = document.createElement("div");
    row.className = "input-group mb-2";
    row.innerHTML = `
      <input type="file"
             name="files"
             class="form-control"
             accept=".jpeg,.jpg,.png,.tiff,.svg,.pdf"
             required>
      <button type="button" class="btn btn-outline-danger">Remove</button>
    `;
    row.querySelector("button").addEventListener("click", () => row.remove());
    return row;
  };

  if (btnAddFile && extraFiles) {
    btnAddFile.addEventListener("click", () => {
      extraFiles.appendChild(makeFileRow());
    });
  }

  // ---------------------------
  // Bulk selection wiring
  // ---------------------------
  const bulkForm = document.getElementById("bulkForm");
  const bulkSelectedContainer = document.getElementById("bulkSelectedContainer");

  // allow different checkbox class names (robust)
  const checkboxSelector = ".photogram-check, .photo-check, .item-check";
  const hiddenInputName = "photogram_ids"; // adjust in template/backend if needed

  function renderBulkSelected() {
    if (!bulkSelectedContainer) return;
    bulkSelectedContainer.innerHTML = "";
    document.querySelectorAll(`${checkboxSelector}:checked`).forEach(chk => {
      bulkSelectedContainer.appendChild(el(`<input type="hidden" name="${hiddenInputName}" value="${chk.value}">`));
    });
  }

  document.querySelectorAll(checkboxSelector).forEach(chk => {
    chk.addEventListener("change", renderBulkSelected);
  });

  const btnSelectAll = document.getElementById("btnSelectAll");
  const btnClear = document.getElementById("btnClearSelection");

  if (btnSelectAll) btnSelectAll.addEventListener("click", () => {
    document.querySelectorAll(checkboxSelector).forEach(chk => chk.checked = true);
    renderBulkSelected();
  });
  if (btnClear) btnClear.addEventListener("click", () => {
    document.querySelectorAll(checkboxSelector).forEach(chk => chk.checked = false);
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
  const editId = document.getElementById("editIdPhotogram") || document.getElementById("editId");
  const deleteId = document.getElementById("deleteIdPhotogram") || document.getElementById("deleteId");

  const bsEdit = modalEditEl ? new bootstrap.Modal(modalEditEl) : null;
  const bsDelete = modalDeleteEl ? new bootstrap.Modal(modalDeleteEl) : null;

  const ssGet = (root, hiddenName) =>
    root ? root.querySelector(`.search-select[data-hidden-name="${hiddenName}"]`) : null;

  const ssSetSingle = (root, hiddenName, id, text) => {
    const ss = ssGet(root, hiddenName);
    if (!ss || !ss._searchSelect) return;
    ss._searchSelect.clear();
    if (id !== null && id !== undefined && String(id) !== "") {
      ss._searchSelect.setSingle(String(id), text ?? String(id));
    }
  };

  const ssSetMulti = (root, hiddenName, values, labelPrefix = "") => {
    const ss = ssGet(root, hiddenName);
    if (!ss || !ss._searchSelect) return;
    ss._searchSelect.clear();
    const vv = Array.isArray(values) ? values : [];
    ss._searchSelect.setMulti(
      vv.map(v => ({
        id: String(v),
        text: labelPrefix ? `${labelPrefix} ${v}` : String(v),
      }))
    );
  };

  async function openEdit(idPhotogram) {
    const url = `/photograms/api/detail/${encodeURIComponent(idPhotogram)}`;
    const resp = await fetch(url, { credentials: "same-origin" });
    if (!resp.ok) return;
    const data = await resp.json();

    if (editId) editId.textContent = data.id_photogram;
    if (editForm) editForm.action = `/photograms/edit/${encodeURIComponent(data.id_photogram)}`;

    // basic fields
    setVal(editForm, 'select[name="photogram_typ"]', data.photogram_typ);
    setVal(editForm, 'input[name="notes"]', data.notes || "");

    // optional FK fields (if you use search-selects for them)
    ssSetSingle(editForm, "ref_sketch", data.ref_sketch, data.ref_sketch);
    ssSetSingle(editForm, "ref_photo_from", data.ref_photo_from, data.ref_photo_from);
    ssSetSingle(editForm, "ref_photo_to", data.ref_photo_to, data.ref_photo_to);

    // links
    const links = data.links || {};
    ssSetMulti(editForm, "ref_sj", links.sj_ids || [], "SU");
    ssSetMulti(editForm, "ref_polygon", links.polygon_names || [], "");
    ssSetMulti(editForm, "ref_section", links.section_ids || [], "Section");

    // geopts ranges are often edited by special UI (not SearchSelect),
    // so we intentionally do not auto-fill them here unless modal has a dedicated field.

    if (bsEdit) bsEdit.show();
  }
  

  

  // ---- Geopts ranges: add/remove rows (Photograms upload) ----
(function () {
  const wrap = document.getElementById("geoptsRanges");
  if (!wrap) return;

  const makeRow = () => {
    const row = document.createElement("div");
    row.className = "row g-2 align-items-end range-row mt-2";
    row.innerHTML = `
      <div class="col-5">
        <label class="form-label">FROM</label>
        <input type="number" class="form-control" name="geopt_from[]" min="1">
      </div>
      <div class="col-5">
        <label class="form-label">TO</label>
        <input type="number" class="form-control" name="geopt_to[]" min="1">
      </div>
      <div class="col-2 d-grid gap-1">
        <button type="button" class="btn btn-outline-secondary btnAddRange">+</button>
        <button type="button" class="btn btn-outline-danger btnRemoveRange">-</button>
      </div>
    `;
    return row;
  };

  // event delegation: works for existing + future rows
  wrap.addEventListener("click", (ev) => {
    const addBtn = ev.target.closest(".btnAddRange");
    if (addBtn) {
      ev.preventDefault();
      wrap.appendChild(makeRow());
      return;
    }

    const rmBtn = ev.target.closest(".btnRemoveRange");
    if (rmBtn) {
      ev.preventDefault();
      const row = rmBtn.closest(".range-row");
      if (!row) return;

      // keep at least one row
      const rows = wrap.querySelectorAll(".range-row");
      if (rows.length <= 1) {
        // just clear values
        row.querySelectorAll('input[type="number"]').forEach(i => (i.value = ""));
        return;
      }
      row.remove();
    }
  });
})();




  function openDelete(idPhotogram) {
    if (deleteId) deleteId.textContent = idPhotogram;
    if (deleteForm) deleteForm.action = `/photograms/delete/${encodeURIComponent(idPhotogram)}`;
    if (bsDelete) bsDelete.show();
  }

  document.querySelectorAll(".btnEdit").forEach(btn => {
    btn.addEventListener("click", () => openEdit(btn.dataset.id));
  });

  document.querySelectorAll(".btnDelete").forEach(btn => {
    btn.addEventListener("click", () => openDelete(btn.dataset.id));
  });
})();
