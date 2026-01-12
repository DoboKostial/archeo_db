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

    // open edit modal -> fetch object
    document.querySelectorAll(".btn-edit").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (editError) { editError.classList.add("d-none"); editError.textContent = ""; }

        const id = btn.getAttribute("data-object-id");
        const url = CFG.urlApiGetObjectBase.replace("/0", `/${id}`);

        const r = await fetch(url);
        const data = await r.json();

        if (!r.ok) {
          if (editError) {
            editError.textContent = data.error || "Failed to load object.";
            editError.classList.remove("d-none");
          }
          return;
        }

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
      });
    });

    // save edit
    const saveEdit = document.getElementById("saveEdit");
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

        const r = await fetch(CFG.urlUpdateObject, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
          body: JSON.stringify({ id_object, object_typ, superior_object, notes, sj_ids, inhum_grave }),
        });

        const data = await r.json();
        if (!r.ok) {
          if (editError) {
            editError.textContent = data.error || "Update failed.";
            editError.classList.remove("d-none");
          }
          return;
        }

        window.location.reload();
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
