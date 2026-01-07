(function () {
  // ---------------------------
  // helpers
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

  // ---------------------------
  // SearchSelect (same as photos.js)
  // ---------------------------
  function initSearchSelect(container) {
    const mode = container.dataset.mode || "multi";
    const endpoint = container.dataset.endpoint;
    const hiddenName = container.dataset.hiddenName;
    const placeholder = container.dataset.placeholder || "Search...";

    container.classList.add("position-relative");

    const input = el(`<input type="text" class="form-control" placeholder="${placeholder}">`);
    const dropdown = el(`<div class="list-group position-absolute w-100 shadow-sm" style="z-index: 50; display:none; max-height:220px; overflow:auto;"></div>`);
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

  initAllSearchSelect(document);


  // ---------------------------
  // Prefill search-select chips from hidden .prefill inputs
  // ---------------------------
  function prefillSearchSelects(root = document) {
    const inputs = [...root.querySelectorAll("input.prefill[data-target]")];
    if (!inputs.length) return;

    const grouped = new Map(); // hiddenName -> [{id,text}]
    inputs.forEach(inp => {
      const name = inp.dataset.target;
      const id = inp.value;
      if (!grouped.has(name)) grouped.set(name, []);
      // simple labels; you can refine if you want
      const text = (name === "ref_sj") ? `SU ${id}` :
                   (name === "ref_section") ? `Section ${id}` :
                   String(id);
      grouped.get(name).push({ id: String(id), text });
    });

    grouped.forEach((vals, hiddenName) => {
      const ss = root.querySelector(`.search-select[data-hidden-name="${hiddenName}"]`);
      if (!ss || !ss._searchSelect) return;
      ss._searchSelect.clear();
      ss._searchSelect.setMulti(vals);
    });
  }

  prefillSearchSelects(document);



  // ---------------------------
  // Upload: add more files inputs
  // ---------------------------
  const btnAddFile = document.getElementById("btnAddFile");
  const extraFiles = document.getElementById("extraFiles");

  if (btnAddFile && extraFiles) {
    btnAddFile.addEventListener("click", () => {
      const row = el(`
        <div class="d-flex gap-2 mt-2">
          <input type="file" class="form-control" name="files" accept=".jpeg,.jpg,.png,.tiff,.svg,.pdf" required>
          <button type="button" class="btn btn-outline-danger">Remove</button>
        </div>
      `);
      row.querySelector("button").addEventListener("click", () => row.remove());
      extraFiles.appendChild(row);
    });
  }

  // ---------------------------
  // Bulk selection wiring
  // ---------------------------
  const bulkForm = document.getElementById("bulkForm");
  const bulkSelectedContainer = document.getElementById("bulkSelectedContainer");

  function renderBulkSelected() {
    if (!bulkSelectedContainer) return;
    bulkSelectedContainer.innerHTML = "";
    document.querySelectorAll(".photo-check:checked").forEach(chk => {
      bulkSelectedContainer.appendChild(el(`<input type="hidden" name="drawing_ids" value="${chk.value}">`));
    });
  }

  document.querySelectorAll(".photo-check").forEach(chk => {
    chk.addEventListener("change", renderBulkSelected);
  });

  const btnSelectAll = document.getElementById("btnSelectAll");
  const btnClear = document.getElementById("btnClearSelection");
  if (btnSelectAll) btnSelectAll.addEventListener("click", () => {
    document.querySelectorAll(".photo-check").forEach(chk => chk.checked = true);
    renderBulkSelected();
  });
  if (btnClear) btnClear.addEventListener("click", () => {
    document.querySelectorAll(".photo-check").forEach(chk => chk.checked = false);
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
  const editIdDrawing = document.getElementById("editIdDrawing");
  const deleteIdDrawing = document.getElementById("deleteIdDrawing");

  const bsEdit = modalEditEl ? new bootstrap.Modal(modalEditEl) : null;
  const bsDelete = modalDeleteEl ? new bootstrap.Modal(modalDeleteEl) : null;

  async function openEdit(idDrawing) {
    const url = `/drawings/api/detail/${encodeURIComponent(idDrawing)}`;
    const resp = await fetch(url, { credentials: "same-origin" });
    if (!resp.ok) return;
    const data = await resp.json();

    editIdDrawing.textContent = data.id_drawing;
    editForm.action = `/drawings/edit/${encodeURIComponent(data.id_drawing)}`;

    editForm.querySelector('input[name="datum"]').value = data.datum;
    editForm.querySelector('input[name="notes"]').value = data.notes || "";

    const authorSS = editForm.querySelector('.search-select[data-hidden-name="author"]');
    authorSS._searchSelect.clear();
    authorSS._searchSelect.setSingle(data.author, data.author);

    const setMulti = (selector, values, labelPrefix = "") => {
      const ss = editForm.querySelector(selector);
      ss._searchSelect.clear();
      ss._searchSelect.setMulti((values || []).map(v => ({
        id: String(v),
        text: labelPrefix ? `${labelPrefix} ${v}` : String(v)
      })));
    };

    setMulti('.search-select[data-hidden-name="ref_sj"]', data.links.sj_ids, "SU");
    setMulti('.search-select[data-hidden-name="ref_section"]', data.links.section_ids, "Section");

    bsEdit.show();
  }

  function openDelete(idDrawing) {
    deleteIdDrawing.textContent = idDrawing;
    deleteForm.action = `/drawings/delete/${encodeURIComponent(idDrawing)}`;
    bsDelete.show();
  }

  document.querySelectorAll(".btnEdit").forEach(btn => {
    btn.addEventListener("click", () => openEdit(btn.dataset.id));
  });

  document.querySelectorAll(".btnDelete").forEach(btn => {
    btn.addEventListener("click", () => openDelete(btn.dataset.id));
  });
})();
