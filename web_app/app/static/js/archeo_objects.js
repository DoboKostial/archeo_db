// app/static/js/archeo_objects.js

(function () {
  const CFG = window.ArcheoObjectsConfig || {};
  const csrfToken = () => (CFG.csrfToken || "");

  function parseMaybeJson(value) {
    if (value === null || value === undefined) return null;
    if (typeof value === "object") return value;
    const s = String(value).trim();
    if (!s) return null;
    try { return JSON.parse(s); } catch (e) { return null; }
  }

  function collectBoneMap() {
    const map = {};
    document.querySelectorAll(".bonechk").forEach(chk => {
      map[chk.dataset.key] = chk.checked;
    });
    return map;
  }

  function applyBoneMap(map) {
    if (!map) return;
    document.querySelectorAll(".bonechk").forEach(chk => {
      chk.checked = !!map[chk.dataset.key];
    });
  }

  function setAllBoneMap(value) {
    document.querySelectorAll(".bonechk").forEach(chk => chk.checked = value);
  }

  function syncInhumBadge(ctx) {
    if (ctx === "create") {
      const isOn = document.getElementById("is_inhum_grave")?.value === "1";
      document.getElementById("createInhumBadge")?.classList.toggle("d-none", !isOn);
    } else {
      const isOn = document.getElementById("edit_is_inhum_grave")?.value === "1";
      document.getElementById("editInhumBadge")?.classList.toggle("d-none", !isOn);
    }
  }

  function loadInhumFromHidden(ctx) {
    const present = (ctx === "create")
      ? (document.getElementById("is_inhum_grave")?.value === "1")
      : (document.getElementById("edit_is_inhum_grave")?.value === "1");

    document.getElementById("inhum_present").checked = present;

    const preservation = (ctx === "create")
      ? document.getElementById("inhum_preservation").value
      : document.getElementById("edit_inhum_preservation").value;

    const orientation = (ctx === "create")
      ? document.getElementById("inhum_orientation_dir").value
      : document.getElementById("edit_inhum_orientation_dir").value;

    const notes = (ctx === "create")
      ? document.getElementById("inhum_notes").value
      : document.getElementById("edit_inhum_notes").value;

    const anthropo = (ctx === "create")
      ? document.getElementById("inhum_anthropo_present").value === "1"
      : document.getElementById("edit_inhum_anthropo_present").value === "1";

    const boxType = (ctx === "create")
      ? document.getElementById("inhum_burial_box_type").value
      : document.getElementById("edit_inhum_burial_box_type").value;

    const boneMapRaw = (ctx === "create")
      ? document.getElementById("inhum_bone_map").value
      : document.getElementById("edit_inhum_bone_map").value;

    document.getElementById("inhum_preservation_ui").value = preservation || "";
    document.getElementById("inhum_orientation_dir_ui").value = orientation || "";
    document.getElementById("inhum_notes_ui").value = notes || "";
    document.getElementById("inhum_anthropo_present_ui").checked = anthropo;
    document.getElementById("inhum_burial_box_type_ui").value = boxType || "";

    // bone map
    setAllBoneMap(false);
    const bm = parseMaybeJson(boneMapRaw);
    if (bm) applyBoneMap(bm);

    // enable/disable fields based on present
    document.getElementById("inhum_fields").classList.toggle("opacity-50", !present);
    document.querySelectorAll("#inhum_fields input, #inhum_fields select, #inhum_fields textarea, #inhum_fields button")
      .forEach(el => el.disabled = !present);

    document.getElementById("inhum_present").disabled = false;
  }

  function saveInhumToHidden(ctx) {
    const present = document.getElementById("inhum_present").checked;

    if (ctx === "create") {
      document.getElementById("is_inhum_grave").value = present ? "1" : "0";
    } else {
      document.getElementById("edit_is_inhum_grave").value = present ? "1" : "0";
    }

    if (!present) {
      // clear values
      const fields = ["preservation", "orientation_dir", "bone_map", "notes", "anthropo_present", "burial_box_type"];
      for (const f of fields) {
        const id = (ctx === "create") ? `inhum_${f}` : `edit_inhum_${f}`;
        const el = document.getElementById(id);
        if (el) el.value = (f === "anthropo_present") ? "0" : "";
      }
      syncInhumBadge(ctx);
      return true;
    }

    const preservation = document.getElementById("inhum_preservation_ui").value.trim();
    const orientation = document.getElementById("inhum_orientation_dir_ui").value.trim();
    const notes = document.getElementById("inhum_notes_ui").value.trim();
    const anthropo = document.getElementById("inhum_anthropo_present_ui").checked;
    const boxType = document.getElementById("inhum_burial_box_type_ui").value.trim();
    const boneMapJson = JSON.stringify(collectBoneMap());

    if (ctx === "create") {
      document.getElementById("inhum_preservation").value = preservation;
      document.getElementById("inhum_orientation_dir").value = orientation;
      document.getElementById("inhum_notes").value = notes;
      document.getElementById("inhum_anthropo_present").value = anthropo ? "1" : "0";
      document.getElementById("inhum_burial_box_type").value = boxType;
      document.getElementById("inhum_bone_map").value = boneMapJson;
      document.getElementById("is_inhum_grave").value = "1";
    } else {
      document.getElementById("edit_inhum_preservation").value = preservation;
      document.getElementById("edit_inhum_orientation_dir").value = orientation;
      document.getElementById("edit_inhum_notes").value = notes;
      document.getElementById("edit_inhum_anthropo_present").value = anthropo ? "1" : "0";
      document.getElementById("edit_inhum_burial_box_type").value = boxType;
      document.getElementById("edit_inhum_bone_map").value = boneMapJson;
      document.getElementById("edit_is_inhum_grave").value = "1";
    }

    syncInhumBadge(ctx);
    return true;
  }

  document.addEventListener("DOMContentLoaded", function () {
    // --- Create: SU add/remove
    const sjContainer = document.getElementById("sj-container");
    const addBtn = document.getElementById("add-sj");
    if (sjContainer && addBtn) {
      addBtn.addEventListener("click", function () {
        const wrap = document.createElement("div");
        wrap.className = "input-group mb-2 sj-input";
        wrap.innerHTML = `
          <input type="number" name="sj_ids[]" class="form-control" placeholder="Zadej ID SJ" required>
          <button type="button" class="btn btn-outline-danger remove-sj">×</button>
        `;
        sjContainer.appendChild(wrap);
      });

      sjContainer.addEventListener("click", function (e) {
        if (e.target.classList.contains("remove-sj")) {
          e.target.closest(".sj-input").remove();
        }
      });
    }

    // --- Define type modal
    const submitNewType = document.getElementById("submitNewType");
    if (submitNewType) {
      submitNewType.addEventListener("click", function () {
        const newType = document.getElementById("newObjectType").value.trim();
        const description = document.getElementById("newDescription").value.trim();
        if (!newType) {
          alert("Zadejte název typu objektu.");
          return;
        }

        fetch(CFG.urlDefineType, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken(),
          },
          body: JSON.stringify({ object_typ: newType, description_typ: description }),
        })
          .then((r) => (r.ok ? r.json() : r.json().then((d) => { throw new Error(d.error || "Chyba"); })))
          .then(() => {
            const select = document.getElementById("object_typ");
            const opt = document.createElement("option");
            opt.value = newType;
            opt.text = newType;
            opt.selected = true;
            select.appendChild(opt);

            bootstrap.Modal.getInstance(document.getElementById("defineObjectTypeModal")).hide();
            document.getElementById("newObjectType").value = "";
            document.getElementById("newDescription").value = "";
          })
          .catch((err) => alert("Chyba: " + err.message));
      });
    }

    // --- Inhumation modal open buttons
    const btnCreateInhumModal = document.getElementById("btnCreateInhumModal");
    const btnEditInhumModal = document.getElementById("btnEditInhumModal");

    if (btnCreateInhumModal) {
      btnCreateInhumModal.addEventListener("click", () => {
        window.__inhumContext = "create";
        loadInhumFromHidden("create");
        bootstrap.Modal.getOrCreateInstance(document.getElementById("inhumGraveModal")).show();
      });
    }

    if (btnEditInhumModal) {
      btnEditInhumModal.addEventListener("click", () => {
        window.__inhumContext = "edit";
        loadInhumFromHidden("edit");
        bootstrap.Modal.getOrCreateInstance(document.getElementById("inhumGraveModal")).show();
      });
    }

    // present checkbox toggle
    const inhumPresent = document.getElementById("inhum_present");
    if (inhumPresent) {
      inhumPresent.addEventListener("change", () => {
        const present = inhumPresent.checked;
        document.getElementById("inhum_fields").classList.toggle("opacity-50", !present);
        document.querySelectorAll("#inhum_fields input, #inhum_fields select, #inhum_fields textarea, #inhum_fields button")
          .forEach(el => el.disabled = !present);
        inhumPresent.disabled = false;
      });
    }

    // bone map helper buttons
    const boneMapAll = document.getElementById("boneMapAll");
    const boneMapNone = document.getElementById("boneMapNone");
    if (boneMapAll) boneMapAll.addEventListener("click", () => setAllBoneMap(true));
    if (boneMapNone) boneMapNone.addEventListener("click", () => setAllBoneMap(false));

    // inhum save
    const inhumSave = document.getElementById("inhumSave");
    if (inhumSave) {
      inhumSave.addEventListener("click", () => {
        const ctx = window.__inhumContext || "create";
        const ok = saveInhumToHidden(ctx);
        if (ok) {
          bootstrap.Modal.getInstance(document.getElementById("inhumGraveModal")).hide();
        }
      });
    }

    // badges init
    syncInhumBadge("create");
    syncInhumBadge("edit");
  });

  // expose few helpers for edit file
  window.ArcheoObjectsShared = {
    parseMaybeJson,
    syncInhumBadge,
  };
})();
