(function () {
  "use strict";

  function qs(sel, root = document) { return root.querySelector(sel); }
  function qsa(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }

  // ---------------------------
  // SearchSelect component (same idea as in photos.js)
  // data-mode="single|multi"
  // data-endpoint="..."
  // data-hidden-name="..."
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

  function initSearchSelect(container) {
    if (!container || container._searchSelect) return;

    const mode = container.dataset.mode || "multi";
    const endpoint = container.dataset.endpoint;
    const hiddenName = container.dataset.hiddenName;
    const placeholder = container.dataset.placeholder || "Search...";

    if (!endpoint || !hiddenName) return;

    container.classList.add("position-relative");

    // IMPORTANT: preserve any prefilled hidden inputs already inside container
    const prefilled = qsa(`input[type="hidden"][name="${hiddenName}"]`, container)
      .map((x) => x.value);

    // If component is re-init, don't duplicate old DOM
    container.innerHTML = "";

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

    const removeHiddenByValue = (val) => {
      qsa(`input[type="hidden"][name="${hiddenName}"]`, container)
        .filter((n) => n.value === String(val))
        .forEach((n) => n.remove());
    };

    const addHidden = (val) => {
      const hidden = el(`<input type="hidden" name="${hiddenName}" value="${String(val)}">`);
      container.appendChild(hidden);
      return hidden;
    };

    const addChip = (id, text) => {
      const sid = String(id);

      if (mode === "single") {
        chips.innerHTML = "";
        qsa(`input[type="hidden"][name="${hiddenName}"]`, container).forEach(n => n.remove());
      } else {
        // prevent duplicates
        const exists = qsa(`input[type="hidden"][name="${hiddenName}"]`, container)
          .some(n => n.value === sid);
        if (exists) return;
      }

      const chip = el(`
        <span class="badge text-bg-secondary d-inline-flex align-items-center gap-2">
          <span class="chip-text"></span>
          <button type="button" class="btn btn-sm btn-light py-0 px-1">x</button>
        </span>
      `);
      chip.querySelector(".chip-text").textContent = text || sid;

      const hidden = addHidden(sid);

      chip.querySelector("button").addEventListener("click", () => {
        hidden.remove();
        chip.remove();
      });

      chips.appendChild(chip);
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

    // close dropdown on outside click
    document.addEventListener("click", (ev) => {
      if (!container.contains(ev.target)) clearDropdown();
    });

    // expose API
    container._searchSelect = {
      setSingle(id, text) { addChip(id, text); },
      setMulti(values) { (values || []).forEach(v => addChip(v.id, v.text)); },
      clear() {
        chips.innerHTML = "";
        qsa(`input[type="hidden"][name="${hiddenName}"]`, container).forEach(n => n.remove());
      },
      // for prefilled-only values (no text) -> show value as chip text
      setFromHiddenExisting() {
        this.clear();
        const vals = prefilled.map(v => ({ id: v, text: v }));
        this.setMulti(vals);
        if (mode === "single" && vals.length) {
          this.clear();
          this.setSingle(vals[0].id, vals[0].text);
        }
      }
    };

    // render prefilled values (filters etc.)
    if (prefilled.length) {
      container._searchSelect.setFromHiddenExisting();
    }
  }

  function initAllSearchSelect(root = document) {
    qsa(".search-select", root).forEach(initSearchSelect);
  }

  // ---------------------------
  // Bootstrap modal helper
  // ---------------------------
  function safeGetBootstrapModal(el) {
    if (!el || typeof bootstrap === "undefined" || !bootstrap.Modal) return null;
    return bootstrap.Modal.getOrCreateInstance(el);
  }

  // ---------------------------
  // Ranges helpers
  // ---------------------------
  function makeRangeRow(fromVal = "", toVal = "", allowRemove = true) {
    const row = document.createElement("div");
    row.className = "row g-2 align-items-end range-row mt-2";

    row.innerHTML = `
      <div class="col-5">
        <label class="form-label">FROM</label>
        <input type="number" class="form-control" name="geopt_from[]" min="1" value="${fromVal}">
      </div>
      <div class="col-5">
        <label class="form-label">TO</label>
        <input type="number" class="form-control" name="geopt_to[]" min="1" value="${toVal}">
      </div>
      <div class="col-2 d-grid">
        ${allowRemove ? `<button type="button" class="btn btn-outline-danger btnRemoveRange">-</button>` : `<span></span>`}
      </div>
    `;
    return row;
  }

  // ---------------------------
  // Edit / Delete modals
  // ---------------------------
  async function openEdit(id) {
    const modalEl = qs("#modalEdit");
    const form = qs("#editForm");
    const editIdEl = qs("#editId");
    const typSel = qs("#editTyp");
    const notesInp = qs("#editNotes");
    const rangesWrap = qs("#editRanges");

    if (!modalEl || !form) return;

    const modal = safeGetBootstrapModal(modalEl);
    if (!modal) return;

    const apiTmpl = (window.PHOTOGRAMS && window.PHOTOGRAMS.apiDetailTmpl) || "";
    const editTmpl = (window.PHOTOGRAMS && window.PHOTOGRAMS.editActionTmpl) || "";
    if (!apiTmpl || !editTmpl) return;

    const apiUrl = apiTmpl.replace("__ID__", encodeURIComponent(id));
    const editAction = editTmpl.replace("__ID__", encodeURIComponent(id));

    // reset
    form.action = editAction;
    if (editIdEl) editIdEl.textContent = id;
    if (notesInp) notesInp.value = "";
    if (rangesWrap) rangesWrap.innerHTML = "";

    // IMPORTANT: SearchSelect inside modal must be initialized
    initAllSearchSelect(form);

    const resp = await fetch(apiUrl, { headers: { "Accept": "application/json" } });
    if (!resp.ok) {
      console.error("Failed to fetch photogram detail", resp.status);
      modal.show();
      return;
    }
    const data = await resp.json();

    if (typSel && data.photogram_typ) typSel.value = data.photogram_typ;
    if (notesInp) notesInp.value = data.notes || "";

    // --- Fill modal SearchSelect UI (NOT just hidden inputs) ---
    const setSingle = (hiddenName, value) => {
      const ss = qs(`.search-select[data-hidden-name="${hiddenName}"]`, form);
      if (!ss || !ss._searchSelect) return;
      ss._searchSelect.clear();
      if (value) ss._searchSelect.setSingle(value, value);
    };

    const setMulti = (hiddenName, arr, prefix = "") => {
      const ss = qs(`.search-select[data-hidden-name="${hiddenName}"]`, form);
      if (!ss || !ss._searchSelect) return;
      ss._searchSelect.clear();
      (arr || []).forEach(v => {
        const txt = prefix ? `${prefix} ${v}` : String(v);
        ss._searchSelect.setMulti([{ id: String(v), text: txt }]);
      });
    };

    setSingle("ref_sketch", data.ref_sketch || "");
    setSingle("ref_photo_from", data.ref_photo_from || "");
    setSingle("ref_photo_to", data.ref_photo_to || "");

    const links = data.links || {};
    setMulti("ref_sj", links.sj_ids || [], "SU");
    setMulti("ref_polygon", links.polygon_names || [], "");
    setMulti("ref_section", links.section_ids || [], "Section");

    // ranges
    const ranges = data.geopts_ranges || [];
    if (rangesWrap) {
      rangesWrap.innerHTML = "";
      if (!ranges.length) {
        rangesWrap.appendChild(makeRangeRow("", "", false));
      } else {
        ranges.forEach((r, idx) => {
          const row = makeRangeRow(r.from ?? "", r.to ?? "", idx !== 0);
          if (idx === 0) {
            const btn = qs(".btnRemoveRange", row);
            if (btn) btn.remove();
            const col2 = qs(".col-2", row);
            if (col2) col2.innerHTML = `<button type="button" class="btn btn-outline-secondary btnAddRangeInEdit">+</button>`;
          }
          rangesWrap.appendChild(row);
        });
      }
    }

    modal.show();
  }

  function openDelete(id) {
    const modalEl = qs("#modalDelete");
    const form = qs("#deleteForm");
    const idEl = qs("#deleteId");
    if (!modalEl || !form) return;

    const modal = safeGetBootstrapModal(modalEl);
    if (!modal) return;

    const delTmpl = (window.PHOTOGRAMS && window.PHOTOGRAMS.deleteActionTmpl) || "";
    if (!delTmpl) return;

    form.action = delTmpl.replace("__ID__", encodeURIComponent(id));
    if (idEl) idEl.textContent = id;

    modal.show();
  }

  // ---------------------------
  // Ranges wiring
  // ---------------------------
  function wireRanges() {
    // UPLOAD ranges
    const uploadWrap = qs("#geoptsRanges");
    if (uploadWrap) {
      uploadWrap.addEventListener("click", (e) => {
        const addBtn = e.target.closest(".btnAddRange");
        const remBtn = e.target.closest(".btnRemoveRange");
        if (addBtn) {
          uploadWrap.appendChild(makeRangeRow("", "", true));
        }
        if (remBtn) {
          const row = remBtn.closest(".range-row");
          if (row) row.remove();
        }
      });
    }

    // EDIT ranges
    const editWrap = qs("#editRanges");
    const btnEditAdd = qs("#btnEditAddRange");
    if (btnEditAdd && editWrap) {
      btnEditAdd.addEventListener("click", () => {
        editWrap.appendChild(makeRangeRow("", "", true));
      });
    }

    if (editWrap) {
      editWrap.addEventListener("click", (e) => {
        const remBtn = e.target.closest(".btnRemoveRange");
        const addBtn = e.target.closest(".btnAddRangeInEdit");
        if (remBtn) {
          const row = remBtn.closest(".range-row");
          if (row) row.remove();
        }
        if (addBtn) {
          editWrap.appendChild(makeRangeRow("", "", true));
        }
      });
    }
  }

  // ---------------------------
  // Gallery buttons
  // ---------------------------
  function wireGalleryButtons() {
    document.addEventListener("click", (e) => {
      const editBtn = e.target.closest(".btnEdit");
      const delBtn = e.target.closest(".btnDelete");

      if (editBtn) {
        const id = editBtn.getAttribute("data-id");
        if (id) openEdit(id).catch((err) => console.error(err));
      }

      if (delBtn) {
        const id = delBtn.getAttribute("data-id");
        if (id) openDelete(id);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    // THIS was missing -> without it SearchSelect never appears
    initAllSearchSelect(document);

    wireRanges();
    wireGalleryButtons();
  });
})();
