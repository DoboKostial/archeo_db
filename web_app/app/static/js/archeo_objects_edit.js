// app/static/js/archeo_objects_edit.js

(function () {
  const CFG = window.ArcheoObjectsConfig || {};
  const Shared = window.ArcheoObjectsShared || {};

  const csrfToken = () => (CFG.csrfToken || "");

  function buildSjInput(value) {
    const wrap = document.createElement("div");
    wrap.className = "input-group mb-2 edit-sj-input";
    wrap.innerHTML = `
      <input type="number" class="form-control edit-sj" value="${value ?? ""}" required>
      <button type="button" class="btn btn-outline-danger edit-remove-sj">×</button>
    `;
    return wrap;
  }

  document.addEventListener("DOMContentLoaded", function () {
    const editSjContainer = document.getElementById("edit_sj_container");
    const editError = document.getElementById("edit_error");

    // add SJ row
    const editAddSj = document.getElementById("edit_add_sj");
    if (editAddSj && editSjContainer) {
      editAddSj.addEventListener("click", () => {
        editSjContainer.appendChild(buildSjInput(""));
      });
    }

    // remove SJ row
    if (editSjContainer) {
      editSjContainer.addEventListener("click", (e) => {
        if (e.target.classList.contains("edit-remove-sj")) {
          e.target.closest(".edit-sj-input").remove();
        }
      });
    }

    const editModal = document.getElementById("editObjectModal");
    const saveEdit = document.getElementById("saveEdit");
    let loadVersion = 0;

    function showError(message) {
      if (!editError) return;
      editError.textContent = message;
      editError.classList.toggle("d-none", !message);
    }

    function setEditorEnabled(enabled) {
      editModal.querySelectorAll(".modal-body input, .modal-body select, .modal-body button, #btnEditInhumModal, #saveEdit")
        .forEach((control) => { control.disabled = !enabled; });
      document.getElementById("edit_id_object_display").disabled = true;
    }

    function populateObject(data) {
      // base fields
      document.getElementById("edit_id_object").value = data.id_object;
      document.getElementById("edit_id_object_display").value = data.id_object;
      document.getElementById("edit_object_typ").value = data.object_typ || "";
      document.getElementById("edit_superior_object").value = (data.superior_object ?? "");
      document.getElementById("edit_notes").value = data.notes || "";

      // SUs
      if (editSjContainer) {
        editSjContainer.innerHTML = "";
        const sj = data.sj_ids || [];
        if (sj.length) {
          sj.forEach((v) => editSjContainer.appendChild(buildSjInput(v)));
        } else {
          editSjContainer.appendChild(buildSjInput(""));
          editSjContainer.appendChild(buildSjInput(""));
        }
      }

      // inhum grave to hidden edit fields
      const g = data.inhum_grave || { present: false };
      document.getElementById("edit_is_inhum_grave").value = g.present ? "1" : "0";
      document.getElementById("edit_inhum_preservation").value = g.preservation ?? "";
      document.getElementById("edit_inhum_orientation_dir").value = g.orientation_dir ?? "";
      document.getElementById("edit_inhum_notes").value = g.notes_grave ?? "";
      document.getElementById("edit_inhum_anthropo_present").value = g.anthropo_present ? "1" : "0";
      document.getElementById("edit_inhum_burial_box_type").value = g.burial_box_type ?? "";

      let bm = g.bone_map;
      if (typeof bm === "string") {
        document.getElementById("edit_inhum_bone_map").value = bm;
      } else if (bm && typeof bm === "object") {
        document.getElementById("edit_inhum_bone_map").value = JSON.stringify(bm);
      } else {
        document.getElementById("edit_inhum_bone_map").value = "";
      }

      if (Shared.syncInhumBadge) Shared.syncInhumBadge("edit");
    }

    async function openObject(id) {
      if (!editModal) return;
      const version = ++loadVersion;
      showError("");
      populateObject({ id_object: "", sj_ids: [] });
      setEditorEnabled(false);
      editModal.setAttribute("aria-busy", "true");
      bootstrap.Modal.getOrCreateInstance(editModal).show();
      try {
        const url = CFG.urlApiGetObjectBase.replace("/0", `/${id}`);
        const response = await fetch(url, { headers: { Accept: "application/json" } });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Failed to load object.");
        if (version !== loadVersion) return;
        populateObject(data);
        setEditorEnabled(true);
      } catch (error) {
        if (version === loadVersion) showError(error.message || "Failed to load object.");
      } finally {
        if (version === loadVersion) editModal.removeAttribute("aria-busy");
      }
    }

    window.ArcheoObjectsEditor = { open: openObject };
    if (editModal) {
      editModal.addEventListener("hidden.bs.modal", () => {
        loadVersion++;
        editModal.removeAttribute("aria-busy");
      });
    }
    document.querySelectorAll(".btn-edit").forEach((btn) => {
      btn.addEventListener("click", () => openObject(btn.getAttribute("data-object-id")));
    });

    const requestedObject = new URLSearchParams(window.location.search).get("edit_object");
    if (requestedObject) {
      const btn = Array.from(document.querySelectorAll(".btn-edit"))
        .find((candidate) => candidate.getAttribute("data-object-id") === requestedObject);
      if (btn) btn.click();
    }

    // save edit
    if (saveEdit) {
      saveEdit.addEventListener("click", async () => {
        if (editError) { editError.classList.add("d-none"); editError.textContent = ""; }

        const id_object = document.getElementById("edit_id_object").value;
        const object_typ = document.getElementById("edit_object_typ").value;
        const superior_object = document.getElementById("edit_superior_object").value;
        const notes = document.getElementById("edit_notes").value;

        const sj_ids = Array.from(document.querySelectorAll(".edit-sj"))
          .map((i) => i.value.trim())
          .filter((v) => v.length > 0);

        const inhum_present = document.getElementById("edit_is_inhum_grave").value === "1";
        const boneMapVal = document.getElementById("edit_inhum_bone_map").value;
        const bone_map = (Shared.parseMaybeJson ? Shared.parseMaybeJson(boneMapVal) : null) || {};

        const inhum_grave = {
          present: inhum_present,
          preservation: document.getElementById("edit_inhum_preservation").value,
          orientation_dir: document.getElementById("edit_inhum_orientation_dir").value,
          notes_grave: document.getElementById("edit_inhum_notes").value,
          anthropo_present: document.getElementById("edit_inhum_anthropo_present").value === "1",
          burial_box_type: document.getElementById("edit_inhum_burial_box_type").value,
          bone_map: bone_map,
        };

        saveEdit.disabled = true;
        try {
          const response = await fetch(CFG.urlUpdateObject, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
            body: JSON.stringify({ id_object, object_typ, superior_object, notes, sj_ids, inhum_grave }),
          });
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || "Update failed.");
          window.location.reload();
        } catch (error) {
          showError(error.message || "Update failed.");
        } finally {
          saveEdit.disabled = false;
        }
      });
    }

    // delete modal -> set id
    document.querySelectorAll(".btn-delete").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-object-id");
        document.getElementById("delete_id_object").value = id;
        document.getElementById("delete_id_object_label").textContent = id;
      });
    });

    // confirm delete
    const confirmDelete = document.getElementById("confirmDelete");
    if (confirmDelete) {
      confirmDelete.addEventListener("click", async () => {
        const id_object = document.getElementById("delete_id_object").value;

        const r = await fetch(CFG.urlDeleteObject, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
          body: JSON.stringify({ id_object }),
        });

        const data = await r.json();
        if (!r.ok) {
          alert(data.error || "Delete failed.");
          return;
        }

        window.location.reload();
      });
    }
  });
})();
