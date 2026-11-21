/* Sections: searchable, additive SU selection for create and edit forms. */
(function () {
  "use strict";

  function initPicker(picker) {
    // Keep the named select as the source of truth and a no-JavaScript fallback.
    const select = picker.querySelector("select");
    const options = Array.from(select.options);
    const input = picker.querySelector("[data-su-search]");
    const suggestions = picker.querySelector("[data-su-suggestions]");
    const chips = picker.querySelector("[data-su-selected]");
    const status = picker.querySelector("[data-su-search-status]");
    const matchesStatus = picker.querySelector("[data-su-matches]");
    let matches = [];
    let active = -1;

    function closeSuggestions() {
      suggestions.hidden = true;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      matchesStatus.textContent = "";
      matches = [];
      active = -1;
    }

    function renderSelected() {
      chips.replaceChildren();
      options.filter(option => option.selected).forEach(option => {
        const chip = document.createElement("li");
        chip.className = "badge text-bg-secondary d-inline-flex align-items-center gap-2 p-2";
        const label = document.createElement("span");
        label.textContent = `SU ${option.textContent.trim()}`;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "btn-close btn-close-white p-2";
        remove.setAttribute("aria-label", `Remove SU ${option.value}`);
        remove.title = `Remove SU ${option.value}`;
        remove.addEventListener("click", () => {
          option.selected = false;
          select.dispatchEvent(new Event("change", { bubbles: true }));
          input.focus();
        });
        chip.append(label, remove);
        chips.appendChild(chip);
      });
      status.textContent = options.length
        ? `Selected: ${select.selectedOptions.length}` : "No SUs available.";
    }

    function add(option) {
      if (!option || option.selected) return;
      option.selected = true;
      input.value = "";
      select.dispatchEvent(new Event("change", { bubbles: true }));
      closeSuggestions();
      input.focus();
    }

    function renderSuggestions() {
      closeSuggestions();
      suggestions.replaceChildren();
      const query = input.value.trim().toLocaleLowerCase();
      if (!query) return;
      const rank = option => option.value === query ? 0 : option.value.startsWith(query) ? 1 : 2;
      const available = options.filter(option => !option.selected && option.textContent.toLocaleLowerCase().includes(query))
        .sort((left, right) => rank(left) - rank(right));
      matches = available.slice(0, 20);
      matches.forEach((option, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "list-group-item list-group-item-action";
        button.id = `${select.id}Suggestion${index}`;
        button.tabIndex = -1;
        button.setAttribute("role", "option");
        button.setAttribute("aria-selected", "false");
        button.textContent = `SU ${option.textContent.trim()}`;
        button.addEventListener("pointerdown", event => event.preventDefault());
        button.addEventListener("click", () => add(option));
        suggestions.appendChild(button);
      });
      suggestions.hidden = !matches.length;
      input.setAttribute("aria-expanded", matches.length ? "true" : "false");
      matchesStatus.textContent = !available.length ? "No matching unselected SUs."
        : available.length > matches.length ? `Showing ${matches.length} of ${available.length} matches.` : "";
    }

    function reset() {
      input.value = "";
      closeSuggestions();
      renderSelected();
    }

    input.addEventListener("input", renderSuggestions);
    input.addEventListener("focus", renderSuggestions);
    input.addEventListener("blur", closeSuggestions);
    document.addEventListener("click", event => {
      if (!picker.contains(event.target)) closeSuggestions();
    });
    input.addEventListener("keydown", event => {
      if (event.isComposing) return;
      if (event.key === "Enter") {
        event.preventDefault();
        if (!suggestions.hidden) add(matches[active < 0 ? 0 : active]);
      } else if (event.key === "Escape" && input.value) {
        event.preventDefault();
        event.stopPropagation();
        input.value = "";
        closeSuggestions();
      } else if ((event.key === "ArrowDown" || event.key === "ArrowUp") && matches.length) {
        event.preventDefault();
        active = event.key === "ArrowDown" ? (active + 1) % matches.length
          : (active <= 0 ? matches.length : active) - 1;
        Array.from(suggestions.children).forEach((button, index) => {
          button.classList.toggle("active", index === active);
          button.setAttribute("aria-selected", index === active ? "true" : "false");
        });
        const button = suggestions.children[active];
        input.setAttribute("aria-activedescendant", button.id);
        button.scrollIntoView({ block: "nearest" });
      }
    });
    select.addEventListener("change", () => {
      renderSelected();
      renderSuggestions();
    });
    select.addEventListener("cut-su-reset", reset);
    select.form.addEventListener("reset", () => setTimeout(reset, 0));
    picker.closest(".modal")?.addEventListener("hidden.bs.modal", () => {
      input.value = "";
      closeSuggestions();
    });
    reset();
    select.hidden = true;
    picker.querySelector("[data-su-picker-label]").htmlFor = input.id;
    picker.querySelector("[data-su-enhanced]").hidden = false;
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-cut-su-picker]").forEach(initPicker);
  });
})();
