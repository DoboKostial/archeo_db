(function () {
  document.addEventListener("DOMContentLoaded", () => {
    const config = window.ArcheoHarrisConfig || {};
    const hotspots = Array.from(document.querySelectorAll(".hmatrix-hotspot"));
    const errorElement = document.getElementById("hmatrixEditorError");
    const pickerElement = document.getElementById("hmatrixSuPickerModal");
    const pickerItems = document.getElementById("hmatrixSuPickerItems");

    async function openSu(id) {
      errorElement.classList.add("d-none");
      hotspots.forEach((button) => { button.disabled = true; });
      try {
        const response = await fetch(config.suDetailBase.replace("/0", `/${id}`), {
          headers: { Accept: "application/json" },
          credentials: "same-origin"
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Failed to load SU.");
        if (!data.editor) throw new Error("Failed to load SU editor data.");
        const trigger = document.createElement("button");
        trigger.setAttribute("data-su", JSON.stringify(data.editor));
        bootstrap.Modal.getOrCreateInstance(document.getElementById("editSuModal")).show(trigger);
      } catch (error) {
        errorElement.textContent = error.message || "Failed to load SU.";
        errorElement.classList.remove("d-none");
      } finally {
        hotspots.forEach((button) => { button.disabled = false; });
      }
    }

    function selectSu(ids) {
      if (ids.length === 1) {
        openSu(ids[0]);
        return;
      }
      pickerItems.replaceChildren();
      ids.forEach((id) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "list-group-item list-group-item-action";
        button.textContent = `SU #${id}`;
        button.addEventListener("click", () => {
          pickerItems.querySelectorAll("button").forEach((item) => { item.disabled = true; });
          pickerElement.addEventListener("hidden.bs.modal", () => openSu(id), { once: true });
          bootstrap.Modal.getOrCreateInstance(pickerElement).hide();
        });
        pickerItems.appendChild(button);
      });
      bootstrap.Modal.getOrCreateInstance(pickerElement).show();
    }

    hotspots.forEach((button) => {
      button.addEventListener("click", () => {
        errorElement.classList.add("d-none");
        if (button.dataset.hmatrixKind === "object") {
          window.ArcheoObjectsEditor.open(button.dataset.hmatrixId);
        } else {
          const ids = (button.dataset.hmatrixIds || button.dataset.hmatrixId || "")
            .split(",").map((value) => value.trim()).filter(Boolean);
          selectSu(ids);
        }
      });
    });
  });
})();
