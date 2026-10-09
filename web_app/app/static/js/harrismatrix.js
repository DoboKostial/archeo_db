(function () {
  document.addEventListener("DOMContentLoaded", () => {
    const hotspots = Array.from(document.querySelectorAll(".hmatrix-hotspot"));
    const pickerElement = document.getElementById("hmatrixSuPickerModal");
    const pickerItems = document.getElementById("hmatrixSuPickerItems");

    function selectSu(ids) {
      if (ids.length === 1) {
        window.ArcheoDBSuEditor.open(ids[0]);
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
          pickerElement.addEventListener("hidden.bs.modal", () => window.ArcheoDBSuEditor.open(id), { once: true });
          bootstrap.Modal.getOrCreateInstance(pickerElement).hide();
        });
        pickerItems.appendChild(button);
      });
      bootstrap.Modal.getOrCreateInstance(pickerElement).show();
    }

    hotspots.forEach((button) => {
      button.addEventListener("click", () => {
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
