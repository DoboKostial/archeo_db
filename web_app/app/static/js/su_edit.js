/* Shared SU editor used by listings, galleries and the Harris Matrix. */
(function () {
  "use strict";

  const qs = id => document.getElementById(id);
  const normalize = value => (value || "").toString().toLowerCase().trim();

  function initChoiceGroups() {
    document.querySelectorAll("[data-choice-group]").forEach((group) => {
      const targetId = group.getAttribute("data-choice-target");
      const input = targetId ? qs(targetId) : null;
      const buttons = Array.from(group.querySelectorAll("[data-choice-value]"));
      if (!input || !buttons.length) return;

      function syncActiveButton() {
        const selectedValue = normalize(input.value);
        buttons.forEach((button) => {
          const acceptedValues = [button.getAttribute("data-choice-value")]
            .concat((button.getAttribute("data-choice-aliases") || "").split(","))
            .map(normalize)
            .filter(Boolean);
          const isActive = acceptedValues.includes(selectedValue);
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
    const errorElement = qs("suEditError");
    const loading = qs("suEditLoading");
    let loadVersion = 0;
    let openVersion = 0;

    function ready(enabled) {
      modal.querySelectorAll("fieldset, button[type='submit']").forEach(control => {
        control.disabled = !enabled;
      });
    }

    function showError(message) {
      errorElement.textContent = message;
      errorElement.classList.toggle("d-none", !message);
    }

    function setOptions(id, values) {
      if (!Array.isArray(values)) return;
      const select = qs(id);
      select.replaceChildren();
      if (id === "edit_author") select.add(new Option("-- choose --", ""));
      values.forEach(value => select.add(new Option(value, value)));
    }

    function setValue(id, value) {
      const el = qs(id);
      if (!el) return;
      el.value = value ?? "";
      el.dispatchEvent(new Event("change", { bubbles: true }));
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

    function populate(su, options = {}) {
      setOptions("edit_author", options.authors);
      setOptions("edit_polygon_names", options.polygons);
      setValue("edit_id_sj", su.id);
      const title = qs("editSuTitle");
      if (title) title.textContent = su.id ? `#${su.id}` : "\u2014";

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
    }

    modal.addEventListener("show.bs.modal", event => {
      const raw = event.relatedTarget?.getAttribute("data-su");
      if (!raw) return;
      openVersion++;
      loadVersion++;
      loading.classList.add("d-none");
      showError("");
      try {
        populate(JSON.parse(raw));
        ready(true);
      } catch (_error) {
        ready(false);
        showError("Failed to load SU editor data.");
      }
    });

    modal.addEventListener("hidden.bs.modal", () => {
      loadVersion++;
      loading.classList.add("d-none");
      modal.removeAttribute("aria-busy");
    });

    const once = (element, event) => new Promise(resolve => {
      element.addEventListener(event, resolve, { once: true });
    });

    async function open(id) {
      const opening = ++openVersion;
      const active = document.querySelector(".modal.show");
      if (active && active !== modal) {
        const instance = bootstrap.Modal.getOrCreateInstance(active);
        if (instance._isTransitioning) await once(active, "shown.bs.modal");
        const hidden = once(active, "hidden.bs.modal");
        instance.hide();
        await hidden;
      }
      const instance = bootstrap.Modal.getOrCreateInstance(modal);
      if (instance._isTransitioning) {
        await once(modal, instance._isShown ? "shown.bs.modal" : "hidden.bs.modal");
      }
      if (opening !== openVersion) return;
      const version = ++loadVersion;
      showError("");
      populate({ id, typ: "deposit" });
      ready(false);
      loading.classList.remove("d-none");
      modal.setAttribute("aria-busy", "true");
      instance.show();
      try {
        const config = window.ArcheoSuEditorConfig || {};
        const response = await fetch(config.detailUrl.replace("/0", `/${id}`), {
          headers: { Accept: "application/json" }, credentials: "same-origin"
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Failed to load SU.");
        if (!data.editor || String(data.editor.id) !== String(id)) {
          throw new Error("Failed to load SU editor data.");
        }
        if (version !== loadVersion) return;
        populate(data.editor, data);
        ready(true);
      } catch (error) {
        if (version === loadVersion) showError(error.message || "Failed to load SU.");
      } finally {
        if (version === loadVersion) {
          loading.classList.add("d-none");
          modal.removeAttribute("aria-busy");
        }
      }
    }

    window.ArcheoDBSuEditor = { open };
    document.addEventListener("click", event => {
      const link = event.target.closest("a[data-su-id]");
      if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      open(link.dataset.suId);
    });

    typ.addEventListener("change", toggleEditTypeFields);
    toggleEditTypeFields();

    const requestedId = window.ArcheoDBOpenEditSuId;
    if (requestedId) {
      const targetId = String(requestedId);
      const buttons = Array.from(document.querySelectorAll("[data-su]"));
      const btn = buttons.find((candidate) => {
        try {
          const su = JSON.parse(candidate.getAttribute("data-su") || "{}");
          return String(su.id) === targetId;
        } catch (_error) {
          return false;
        }
      });
      if (btn && window.bootstrap) {
        const instance = bootstrap.Modal.getInstance(modal) || new bootstrap.Modal(modal);
        instance.show(btn);
      }
    }
  }


  document.addEventListener("DOMContentLoaded", () => {
    initChoiceGroups();
    initEditModal();
  });
})();
