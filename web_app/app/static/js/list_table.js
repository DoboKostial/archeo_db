window.ArcheoDBInitListItemsModal = function (id) {
  const modal = document.getElementById(id);
  if (!modal) return;
  modal.addEventListener('show.bs.modal', event => {
    const trigger = event.relatedTarget;
    const template = document.getElementById(trigger?.dataset.itemsTemplate);
    modal.querySelector('.modal-title').textContent = trigger?.dataset.itemsTitle || '';
    const body = modal.querySelector('.modal-body');
    body.replaceChildren();
    if (template) body.appendChild(template.content.cloneNode(true));
  });
  modal.addEventListener('hidden.bs.modal', () => modal.querySelector('.modal-body').replaceChildren());
};

window.ArcheoDBInitListTable = function (prefix) {
  const table = document.getElementById(`${prefix}Table`);
  const tbody = document.getElementById(`${prefix}TableBody`);
  const pager = document.getElementById(`${prefix}Pagination`);
  const pagerWrap = document.getElementById(`${prefix}PaginationWrap`);
  const summary = document.getElementById(`${prefix}PaginationSummary`);
  const noMatches = document.getElementById(`${prefix}NoMatches`);
  const reset = document.getElementById(`${prefix}ResetTable`);

  if (!table || !tbody || !pager || !pagerWrap || !summary || !noMatches || !reset) return;

  const rows = Array.from(tbody.querySelectorAll('tr[data-list-row]'));
  const pageSize = Number.parseInt(table.dataset.pageSize || '10', 10);
  const columns = Array.from(table.querySelectorAll('th[data-column]')).map(header => ({
    header,
    key: header.dataset.column,
    numeric: header.dataset.sortType === 'number',
    input: header.querySelector('[data-column-filter]'),
    searchButton: header.querySelector('[data-column-search]'),
    sortButton: header.querySelector('[data-column-sort]'),
    filter: header.querySelector('.polygon-column-filter'),
    label: header.querySelector('.polygon-column-title').textContent.trim()
  }));
  const normalize = value => value.toLocaleLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim();
  const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });
  const items = rows.map((row, index) => {
    const values = {};
    const search = {};
    columns.forEach(column => {
      const cell = row.cells[column.header.cellIndex];
      values[column.key] = (cell.dataset.searchValue ?? cell.textContent).trim();
      search[column.key] = normalize(values[column.key]);
    });
    return { row, index, values, search };
  });
  const filters = new Map();
  let sortColumn = null;
  let sortDirection = 0;
  let currentPage = 1;

  function renderPagination() {
    const matched = items.filter(item => Array.from(filters).every(([key, value]) => item.search[key].includes(value)));
    if (sortColumn) {
      matched.sort((a, b) => {
        const left = a.values[sortColumn.key];
        const right = b.values[sortColumn.key];
        // Keep empty cells last in either direction.
        if (!left && right) return 1;
        if (left && !right) return -1;
        const comparison = sortColumn.numeric ? Number(left) - Number(right) : collator.compare(left, right);
        return comparison * sortDirection || a.index - b.index;
      });
    }

    const pageCount = Math.ceil(matched.length / pageSize);
    currentPage = Math.max(1, Math.min(currentPage, pageCount));
    const start = (currentPage - 1) * pageSize;
    const end = Math.min(start + pageSize, matched.length);
    const visible = new Set(matched.slice(start, end).map(item => item.row));
    rows.forEach(row => row.hidden = !visible.has(row));
    const fragment = document.createDocumentFragment();
    matched.forEach(item => fragment.appendChild(item.row));
    tbody.insertBefore(fragment, noMatches);
    noMatches.hidden = matched.length > 0;
    summary.textContent = matched.length
      ? `Showing ${start + 1}-${end} of ${matched.length}${filters.size ? ` (${items.length} total)` : ''}`
      : `Showing 0 of ${items.length}`;
    reset.disabled = filters.size === 0 && !sortColumn;

    columns.forEach(column => {
      const active = sortColumn === column;
      column.header.setAttribute('aria-sort', active ? (sortDirection === 1 ? 'ascending' : 'descending') : 'none');
      column.searchButton.classList.toggle('is-active', filters.has(column.key));
      column.sortButton.classList.toggle('is-active', active);
      column.sortButton.setAttribute('aria-pressed', String(active));
      const direction = active ? (sortDirection === 1 ? 'sort-asc' : 'sort-desc') : 'sort';
      column.sortButton.querySelector('span').className = `polygon-list-icon polygon-icon-${direction}`;
      const title = active && sortDirection === -1
        ? `Clear sorting by ${column.label}`
        : `Sort ${column.label} ${active ? 'descending' : 'ascending'}`;
      column.sortButton.title = title;
      column.sortButton.setAttribute('aria-label', title);
    });

    pager.replaceChildren();
    pager.closest('nav').hidden = pageCount <= 1;
    if (pageCount <= 1) return;

    const addPageItem = (label, page, options = {}) => {
      const li = document.createElement('li');
      li.className = 'page-item';
      if (options.active) li.classList.add('active');
      if (options.disabled) li.classList.add('disabled');

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'page-link';
      btn.textContent = label;
      btn.disabled = Boolean(options.disabled);
      btn.addEventListener('click', () => {
        if (!options.disabled) {
          currentPage = page;
          renderPagination();
        }
      });

      li.appendChild(btn);
      pager.appendChild(li);
    };

    addPageItem('‹', Math.max(1, currentPage - 1), { disabled: currentPage === 1 });

    for (let page = 1; page <= pageCount; page += 1) {
      addPageItem(String(page), page, { active: page === currentPage });
    }

    addPageItem('›', Math.min(pageCount, currentPage + 1), { disabled: currentPage === pageCount });

  }

  columns.forEach(column => {
    column.searchButton.addEventListener('click', () => {
      column.filter.hidden = !column.filter.hidden;
      column.searchButton.setAttribute('aria-expanded', String(!column.filter.hidden));
      if (!column.filter.hidden) column.input.focus();
    });
    column.input.addEventListener('input', () => {
      const value = normalize(column.input.value);
      if (value) filters.set(column.key, value);
      else filters.delete(column.key);
      currentPage = 1;
      renderPagination();
    });
    column.input.addEventListener('keydown', event => {
      if (event.key !== 'Escape') return;
      column.input.value = '';
      filters.delete(column.key);
      column.filter.hidden = true;
      column.searchButton.setAttribute('aria-expanded', 'false');
      column.searchButton.focus();
      currentPage = 1;
      renderPagination();
    });
    column.sortButton.addEventListener('click', () => {
      if (sortColumn !== column) {
        sortColumn = column;
        sortDirection = 1;
      } else if (sortDirection === 1) {
        sortDirection = -1;
      } else {
        sortColumn = null;
        sortDirection = 0;
      }
      currentPage = 1;
      renderPagination();
    });
  });

  reset.addEventListener('click', () => {
    filters.clear();
    sortColumn = null;
    sortDirection = 0;
    currentPage = 1;
    columns.forEach(column => {
      column.input.value = '';
      column.filter.hidden = true;
      column.searchButton.setAttribute('aria-expanded', 'false');
    });
    renderPagination();
  });

  renderPagination();
};
