/* app/static/js/su.js */

(function () {
  "use strict";

  function qs(id) {
    return document.getElementById(id);
  }

  function normalize(s) {
    return (s || "").toString().toLowerCase().trim();
  }

  // Expose for inline onclick in modals
  window.addFileInput = function (containerId) {
    const c = document.getElementById(containerId);
    if (!c) return;

    const input = document.createElement("input");
    input.type = "file";
    input.name = "files";
    input.className = "form-control mb-2";
    input.setAttribute("accept", ".jpeg,jpg,png,tiff,svg,pdf");
    c.appendChild(input);
  };

  // ------------------------------------------------------------
  // 1) Type-specific toggle
  // ------------------------------------------------------------
  function toggleTypeFields() {
    const typ = normalize(qs("sj_typ")?.value);
    const dep = qs("deposit_fields");
    const neg = qs("negativ_fields");
    const str = qs("structure_fields");

    if (dep) dep.style.display = (typ === "deposit") ? "block" : "none";
    if (neg) neg.style.display = (typ === "negativ") ? "block" : "none";
    if (str) str.style.display = (typ === "structure") ? "block" : "none";
  }

  function initSuTypeShortcuts() {
    const select = qs("sj_typ");
    const buttons = Array.from(document.querySelectorAll(".su-type-btn[data-sj-type]"));
    if (!select || !buttons.length) return;

    function syncActiveButton() {
      const typ = normalize(select.value);
      buttons.forEach((button) => {
        button.classList.toggle("active", normalize(button.dataset.sjType) === typ);
      });
    }

    buttons.forEach((button) => {
      button.addEventListener("click", () => {
        select.value = button.dataset.sjType || "";
        select.dispatchEvent(new Event("change", { bubbles: true }));
        syncActiveButton();
      });
    });

    select.addEventListener("change", syncActiveButton);
    syncActiveButton();
  }

  function initChoiceGroups() {
    document.querySelectorAll("[data-choice-group]").forEach((group) => {
      const targetId = group.getAttribute("data-choice-target");
      const input = targetId ? qs(targetId) : null;
      const buttons = Array.from(group.querySelectorAll("[data-choice-value]"));
      if (!input || !buttons.length) return;

      function syncActiveButton() {
        const selectedValue = normalize(input.value);
        buttons.forEach((button) => {
          const isActive = normalize(button.getAttribute("data-choice-value")) === selectedValue;
          button.classList.toggle("active", isActive);
          button.setAttribute("aria-pressed", isActive ? "true" : "false");
        });
      }

      buttons.forEach((button) => {
        button.addEventListener("click", () => {
          input.value = button.getAttribute("data-choice-value") || "";
          input.dispatchEvent(new Event("change", { bubbles: true }));
          syncActiveButton();
        });
      });

      input.addEventListener("change", syncActiveButton);
      syncActiveButton();
    });
  }

  function initColorPickers() {
    document.querySelectorAll(".deposit-color-picker").forEach((picker) => {
      const inputId = picker.getAttribute("data-choice-target");
      const input = inputId ? qs(inputId) : null;
      const toggle = picker.querySelector("[data-color-toggle]");
      const menu = picker.querySelector("[data-color-menu]");
      const current = picker.querySelector(".deposit-color-current");
      const buttons = Array.from(picker.querySelectorAll(".deposit-color-btn[data-choice-value]"));
      if (!input || !toggle || !menu || !current || !buttons.length) return;

      function selectedButton() {
        const value = normalize(input.value);
        return buttons.find((button) => normalize(button.getAttribute("data-choice-value")) === value);
      }

      function setOpen(open) {
        menu.classList.toggle("open", open);
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
      }

      function syncCurrentSwatch() {
        const active = selectedButton();
        const swatch = active?.style.getPropertyValue("--swatch") || "#efe9dc";
        current.style.setProperty("--selected-swatch", swatch);
        toggle.title = active ? `Color: ${active.getAttribute("data-choice-value")}` : "Choose color";
      }

      toggle.addEventListener("click", (event) => {
        event.stopPropagation();
        setOpen(!menu.classList.contains("open"));
      });

      buttons.forEach((button) => {
        button.addEventListener("click", () => {
          setOpen(false);
          syncCurrentSwatch();
        });
      });

      input.addEventListener("change", syncCurrentSwatch);

      document.addEventListener("click", (event) => {
        if (!picker.contains(event.target)) setOpen(false);
      });

      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") setOpen(false);
      });

      syncCurrentSwatch();
    });
  }

  // ------------------------------------------------------------
  // Generic suggestions dropdown (Bootstrap list-group)
  // ------------------------------------------------------------
  function makeSuggestions(inputEl, suggestionsEl, items, renderTextFn, onPick) {
    if (!inputEl || !suggestionsEl) return;

    function hide() {
      suggestionsEl.classList.add("d-none");
      suggestionsEl.innerHTML = "";
    }

    function show(matches) {
      suggestionsEl.innerHTML = "";
      if (!matches.length) {
        hide();
        return;
      }

      matches.slice(0, 8).forEach((item) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "list-group-item list-group-item-action";
        btn.textContent = renderTextFn(item);
        btn.addEventListener("mousedown", (e) => {
          // mousedown so it fires before blur
          e.preventDefault();
          onPick(item);
          hide();
        });
        suggestionsEl.appendChild(btn);
      });

      suggestionsEl.classList.remove("d-none");
    }

    inputEl.addEventListener("input", () => {
      const q = normalize(inputEl.value);
      if (!q) return hide();

      const matches = items.filter((it) => normalize(renderTextFn(it)).includes(q));
      show(matches);
    });

    inputEl.addEventListener("blur", () => {
      // allow click on suggestion
      setTimeout(hide, 150);
    });

    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Escape") hide();
    });

    hide();
  }

  // ------------------------------------------------------------
  // 2) Polygons picker: single input + suggestions + add/remove + hidden inputs
  // ------------------------------------------------------------
  function initPolygonsPicker() {
    const inputEl = qs("polygonInput");
    const suggEl = qs("polygonSuggestions");
    const datalist = qs("polygonDatalist");
    const addBtn = qs("addPolygonBtn");
    const clearBtn = qs("clearPolygonsBtn");
    const selectedWrap = qs("selectedPolygons");
    const hiddenWrap = qs("polygonHiddenInputs");
    const countEl = qs("selectedPolygonsCount");

    if (!inputEl || !suggEl || !datalist || !addBtn || !selectedWrap || !hiddenWrap || !countEl) return;

    const allPolys = Array.from(datalist.querySelectorAll("option")).map(o => (o.value || "").trim()).filter(Boolean);

    // map for case-insensitive matching -> canonical polygon name
    const polyMap = new Map();
    allPolys.forEach(p => polyMap.set(normalize(p), p));

    const selected = new Map(); // canonicalName -> {badgeEl, inputEl}

    function updateCount() {
      countEl.textContent = String(selected.size);
    }

    function addPolygonFromInput() {
      const raw = (inputEl.value || "").trim();
      if (!raw) return;

      const canonical = polyMap.get(normalize(raw));
      if (!canonical) {
        alert("Please select an existing polygon from suggestions.");
        return;
      }
      if (selected.has(canonical)) {
        inputEl.value = "";
        return;
      }

      // Badge
      const badge = document.createElement("span");
      badge.className = "badge text-bg-primary d-inline-flex align-items-center gap-2";
      badge.style.fontSize = "0.95rem";
      badge.textContent = canonical;

      const rm = document.createElement("button");
      rm.type = "button";
      rm.className = "btn btn-sm btn-light";
      rm.style.lineHeight = "1";
      rm.textContent = "×";
      rm.setAttribute("aria-label", "Remove");

      badge.appendChild(rm);
      selectedWrap.appendChild(badge);

      // Hidden input
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = "polygon_names";
      input.value = canonical;
      hiddenWrap.appendChild(input);

      selected.set(canonical, { badgeEl: badge, inputEl: input });
      updateCount();

      rm.addEventListener("click", () => {
        const rec = selected.get(canonical);
        if (!rec) return;
        rec.badgeEl.remove();
        rec.inputEl.remove();
        selected.delete(canonical);
        updateCount();
      });

      inputEl.value = "";
    }

    addBtn.addEventListener("click", addPolygonFromInput);

    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addPolygonFromInput();
      }
    });

    clearBtn?.addEventListener("click", () => {
      selected.forEach((rec) => {
        rec.badgeEl.remove();
        rec.inputEl.remove();
      });
      selected.clear();
      updateCount();
      inputEl.value = "";
    });

    makeSuggestions(
      inputEl,
      suggEl,
      allPolys,
      (p) => p,
      (picked) => { inputEl.value = picked; }
    );

    updateCount();
  }

  // ------------------------------------------------------------
  // 3) Attach media: single input + suggestions + disable buttons until valid SU
  // ------------------------------------------------------------
  function initAttachMedia() {
    const inputEl = qs("suMediaInput");
    const suggEl = qs("suSuggestions");
    const datalist = qs("suDatalist");
    const labelEl = qs("suMediaSelectedLabel");
    const buttons = Array.from(document.querySelectorAll(".suDocBtn"));

    if (!inputEl || !suggEl || !datalist || !labelEl) return;

    // Build SU map: id -> label
    const suMap = new Map();       // idStr -> label
    const allItems = [];           // [{id, label}]
    Array.from(datalist.querySelectorAll("option")).forEach((o) => {
      const id = (o.value || "").trim();
      if (!id) return;
      const label = (o.getAttribute("label") || o.value || "").trim();
      suMap.set(id, label);
      allItems.push({ id, label });
    });

    function setButtonsEnabled(enabled) {
      buttons.forEach((b) => {
        b.disabled = !enabled;
        b.classList.toggle("disabled", !enabled);
      });
    }

    function currentSelectedSuId() {
      const v = (inputEl.value || "").trim();
      return v && suMap.has(v) ? v : "";
    }

    function updateSelectedLabel() {
      const id = currentSelectedSuId();
      if (!id) {
        labelEl.textContent = "—";
        setButtonsEnabled(false);
        return;
      }
      labelEl.textContent = suMap.get(id) || id;
      setButtonsEnabled(true);
    }

    function hookUploadForm(formId, mediaType, previewSpanId) {
      const form = document.getElementById(formId);
      if (!form) return;

      const modal = form.closest(".modal");
      const preview = document.getElementById(previewSpanId);

      if (modal) {
        modal.addEventListener("show.bs.modal", function (ev) {
          const sj = currentSelectedSuId();
          if (!sj) {
            ev.preventDefault();
            alert("Please select an existing SU first.");
            return;
          }
          if (preview) preview.textContent = sj;
        });
      }

      form.addEventListener("submit", function (ev) {
        const sj = currentSelectedSuId();
        if (!sj) {
          ev.preventDefault();
          alert("Please select an existing SU first.");
          return false;
        }
        form.action = `/su/${encodeURIComponent(sj)}/upload/${encodeURIComponent(mediaType)}`;
      });
    }

    hookUploadForm("formPhotos", "photos", "suIdPreviewPhotos");
    hookUploadForm("formSketches", "sketches", "suIdPreviewSketches");
    hookUploadForm("formDrawings", "drawings", "suIdPreviewDrawings");
    hookUploadForm("formPhotograms", "photograms", "suIdPreviewPhotograms");

    // Suggestions: match by "id + label"
    makeSuggestions(
      inputEl,
      suggEl,
      allItems,
      (it) => `${it.id} - ${it.label}`,
      (picked) => { inputEl.value = picked.id; updateSelectedLabel(); }
    );

    inputEl.addEventListener("input", updateSelectedLabel);
    inputEl.addEventListener("change", updateSelectedLabel);

    setButtonsEnabled(false);
    updateSelectedLabel();
  }

  // ------------------------------------------------------------
  // 4) Delete SU modal wiring
  // ------------------------------------------------------------
  function initDeleteModal() {
    const modal = qs("deleteSuModal");
    const hidden = qs("deleteSuIdHidden");
    const preview = qs("deleteSuIdPreview");
    if (!modal || !hidden || !preview) return;

    modal.addEventListener("show.bs.modal", function (event) {
      const btn = event.relatedTarget;
      const sjId = btn?.getAttribute("data-sj-id") || "";
      hidden.value = sjId;
      preview.textContent = sjId || "—";
    });
  }

  // ------------------------------------------------------------
  // 5) SUs table pagination
  // ------------------------------------------------------------
  function initSuPagination() {
    const table = qs("suTable");
    const tbody = qs("suTableBody");
    const pager = qs("suPagination");
    const pagerWrap = qs("suPaginationWrap");
    const summary = qs("suPaginationSummary");

    if (!table || !tbody || !pager || !pagerWrap || !summary) return;

    const rows = Array.from(tbody.querySelectorAll("tr"));
    const pageSize = Number.parseInt(table.dataset.pageSize || "10", 10);
    const pageCount = Math.ceil(rows.length / pageSize);
    let currentPage = 1;

    function addPageItem(label, page, options = {}) {
      const li = document.createElement("li");
      li.className = "page-item";
      if (options.active) li.classList.add("active");
      if (options.disabled) li.classList.add("disabled");

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "page-link";
      btn.textContent = label;
      btn.disabled = Boolean(options.disabled);
      btn.addEventListener("click", () => {
        if (options.disabled) return;
        currentPage = page;
        renderPage();
      });

      li.appendChild(btn);
      pager.appendChild(li);
    }

    function renderPage() {
      pager.innerHTML = "";

      if (pageCount <= 1) {
        pagerWrap.style.display = "none";
        rows.forEach((row) => { row.hidden = false; });
        return;
      }

      pagerWrap.style.display = "";

      addPageItem("‹", Math.max(1, currentPage - 1), { disabled: currentPage === 1 });
      for (let page = 1; page <= pageCount; page += 1) {
        addPageItem(String(page), page, { active: page === currentPage });
      }
      addPageItem("›", Math.min(pageCount, currentPage + 1), { disabled: currentPage === pageCount });

      const start = (currentPage - 1) * pageSize;
      const end = Math.min(start + pageSize, rows.length);

      rows.forEach((row, index) => {
        row.hidden = index < start || index >= end;
      });

      summary.textContent = `Showing ${start + 1}-${end} of ${rows.length}`;
    }

    renderPage();
  }

  // ------------------------------------------------------------
  // 6) Edit SU modal wiring
  // ------------------------------------------------------------
  function toggleEditTypeFields() {
    const typ = normalize(qs("edit_sj_typ")?.value);
    const dep = qs("edit_deposit_fields");
    const neg = qs("edit_negativ_fields");
    const str = qs("edit_structure_fields");

    if (dep) dep.style.display = (typ === "deposit") ? "block" : "none";
    if (neg) neg.style.display = (typ === "negativ") ? "block" : "none";
    if (str) str.style.display = (typ === "structure") ? "block" : "none";
  }

  function initEditModal() {
    const modal = qs("editSuModal");
    const typ = qs("edit_sj_typ");
    if (!modal || !typ) return;

    function setValue(id, value) {
      const el = qs(id);
      if (el) el.value = value ?? "";
    }

    function setChecked(id, value) {
      const el = qs(id);
      if (el) el.checked = Boolean(value);
    }

    function setMultiSelect(id, values) {
      const el = qs(id);
      if (!el) return;
      const selected = new Set((values || []).map((value) => String(value)));
      Array.from(el.options).forEach((option) => {
        option.selected = selected.has(option.value);
      });
    }

    function joinIds(values) {
      return (values || []).join(", ");
    }

    modal.addEventListener("show.bs.modal", function (event) {
      const btn = event.relatedTarget;
      const raw = btn?.getAttribute("data-su") || "{}";
      let su = {};
      try {
        su = JSON.parse(raw);
      } catch (_error) {
        su = {};
      }

      setValue("edit_id_sj", su.id);
      const title = qs("editSuTitle");
      if (title) title.textContent = su.id ? `#${su.id}` : "—";

      setValue("edit_sj_typ", su.typ || "deposit");
      setValue("edit_recorded", su.recorded || "");
      setValue("edit_author", su.author || "");
      setValue("edit_description", su.desc || "");
      setValue("edit_interpretation", su.interpretation || "");
      setChecked("edit_docu_plan", su.docu_plan);
      setChecked("edit_docu_vertical", su.docu_vertical);

      setValue("edit_deposit_typ", su.deposit_typ);
      setValue("edit_color", su.color);
      setValue("edit_boundary_visibility", su.boundary_visibility);
      setValue("edit_structure", su.structure);
      setValue("edit_compactness", su.compactness);
      setValue("edit_deposit_removed", su.deposit_removed);

      setValue("edit_negativ_typ", su.negativ_typ);
      setValue("edit_excav_extent", su.excav_extent);
      setChecked("edit_ident_niveau_cut", su.ident_niveau_cut);
      setValue("edit_shape_plan", su.shape_plan);
      setValue("edit_shape_sides", su.shape_sides);
      setValue("edit_shape_bottom", su.shape_bottom);

      setValue("edit_structure_typ", su.structure_typ);
      setValue("edit_construction_typ", su.construction_typ);
      setValue("edit_binder", su.binder);
      setValue("edit_basic_material", su.basic_material);
      setValue("edit_length_m", su.length_m);
      setValue("edit_width_m", su.width_m);
      setValue("edit_height_m", su.height_m);

      setMultiSelect("edit_polygon_names", su.polygon_names);
      setValue("edit_below_ids", joinIds(su.below_ids));
      setValue("edit_equal_ids", joinIds(su.equal_ids));
      setValue("edit_above_ids", joinIds(su.above_ids));

      toggleEditTypeFields();
    });

    typ.addEventListener("change", toggleEditTypeFields);
    toggleEditTypeFields();
  }

  document.addEventListener("DOMContentLoaded", function () {
    const sjTyp = qs("sj_typ");
    if (sjTyp) {
      sjTyp.addEventListener("change", toggleTypeFields);
      toggleTypeFields();
    }

    initPolygonsPicker();
    initSuTypeShortcuts();
    initChoiceGroups();
    initColorPickers();
    initAttachMedia();
    initDeleteModal();
    initSuPagination();
    initEditModal();
  });
})();
