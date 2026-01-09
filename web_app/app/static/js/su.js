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

  document.addEventListener("DOMContentLoaded", function () {
    const sjTyp = qs("sj_typ");
    if (sjTyp) {
      sjTyp.addEventListener("change", toggleTypeFields);
      toggleTypeFields();
    }

    initPolygonsPicker();
    initAttachMedia();
    initDeleteModal();
  });
})();
