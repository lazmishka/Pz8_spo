(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const labels = {
    new: "Создано", confirmed: "Подтверждено", issued: "Выдано",
    completed: "Завершено", cancelled: "Отменено",
  };
  const states = { available: "Свободно", reserved: "Зарезервировано", issued: "Выдано" };
  const actions = {
    new: [["confirm", "Подтвердить резерв"], ["cancel", "Отменить бронь"]],
    confirmed: [["issue", "Выдать оборудование"], ["cancel", "Отменить бронь"]],
    issued: [["return", "Принять возврат"]], completed: [], cancelled: [],
  };
  const eventLabels = {
    created: "Создание", updated: "Редактирование", confirmed: "Подтверждение",
    issued: "Выдача", returned: "Возврат", cancelled: "Отмена", deleted: "Удаление",
  };
  const fieldLabels = {
    equipment: "Оборудование", purpose: "Назначение", status: "Статус", category: "Категория",
  };
  let devices = [];
  let rows = [];
  let selected = null;
  let busy = false;

  class ApiError extends Error {
    constructor(message, status = 0) { super(message); this.status = status; }
  }

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function formatErrors(data) {
    if (!data || typeof data !== "object") return "Сервер вернул некорректное описание ошибки.";
    return Object.entries(data).map(([field, value]) => {
      const content = Array.isArray(value) ? value.join(" ") : String(value);
      return ["detail", "non_field_errors"].includes(field)
        ? content : `${fieldLabels[field] || field}: ${content}`;
    }).join("\n");
  }

  async function api(url, options = {}) {
    let response;
    try {
      response = await fetch(url, {
        ...options, credentials: "same-origin",
        headers: {
          Accept: "application/json", "Content-Type": "application/json",
          "X-CSRFToken": document.querySelector("[name=csrfmiddlewaretoken]").value,
          ...(options.headers || {}),
        },
      });
    } catch {
      throw new ApiError("Нет связи с сервером. Результат изменения может быть неизвестен. Обновите данные перед повторным действием.");
    }
    if (response.status === 204) return null;
    if (response.status >= 500) {
      throw new ApiError("Сбой сервера. Обновите данные и проверьте состояние перед повторным действием.", response.status);
    }
    let data;
    try {
      if (!(response.headers.get("content-type") || "").includes("application/json")) throw new Error();
      data = await response.json();
    } catch {
      throw new ApiError("Ответ сервера не удалось прочитать. Проверьте вход в систему и обновите данные.", response.status);
    }
    if (!response.ok) {
      const prefix = response.status === 403 ? "Нет доступа: проверьте вход в систему и CSRF. " : "";
      throw new ApiError(prefix + formatErrors(data), response.status);
    }
    return data;
  }

  function message(text, kind = "success") {
    $("operation-message").className = `alert alert-${kind}`;
    $("operation-message").textContent = text;
    $("operation-message").hidden = false;
  }

  function loadError(text = "") {
    $("load-error").textContent = text;
    $("load-error").hidden = !text;
  }

  function date(value) { return value ? new Date(value).toLocaleString("ru-RU") : "—"; }

  function deviceOptions(select, value = "") {
    select.replaceChildren(element("option", devices.length ? "Выберите экземпляр" : "Оборудование не добавлено"));
    select.firstChild.value = "";
    for (const device of devices) {
      const option = element("option", `${device.name} · ${device.inventory_number} — ${states[device.state] || device.state}`);
      option.value = device.id;
      select.append(option);
    }
    select.value = String(value);
  }

  function lock(locked) {
    busy = locked;
    document.querySelectorAll("#reservation-form button, #reservation-form input, #reservation-form select, #reservation-form textarea, #reservation-detail button, #reservation-detail input, #reservation-detail select, #reservation-detail textarea, .reservation-row, #status-filter, #category-filter, #refresh-all")
      .forEach((node) => { node.disabled = locked; });
    $("equipment-input").disabled = locked || !devices.length;
    $("create-button").disabled = locked || !devices.length;
  }

  async function loadDevices() {
    const data = await api("/api/equipment/");
    if (!Array.isArray(data)) throw new ApiError("Неожиданный формат справочника оборудования.");
    devices = data;
    deviceOptions($("equipment-input"), $("equipment-input").value);
    const category = $("category-filter").value;
    $("category-filter").replaceChildren(element("option", "Все категории"));
    $("category-filter").firstChild.value = "";
    for (const name of [...new Set(devices.map((device) => device.category))].sort()) {
      const option = element("option", name);
      option.value = name;
      $("category-filter").append(option);
    }
    $("category-filter").value = category;
    lock(busy);
  }

  function badge(status) {
    const colors = { new: "azure", confirmed: "yellow", issued: "purple", completed: "green", cancelled: "secondary" };
    return element("span", labels[status] || status, `badge bg-${colors[status] || "secondary"}-lt`);
  }

  function renderList() {
    const list = $("reservation-list");
    list.replaceChildren();
    $("list-count").textContent = `Найдено: ${rows.length}`;
    if (!rows.length) list.append(element("p", "По выбранным фильтрам бронирований нет.", "text-secondary"));
    for (const row of rows) {
      const button = element("button", undefined, "reservation-row");
      button.type = "button";
      button.dataset.reservationId = row.id;
      button.setAttribute("aria-pressed", String(selected === row.id));
      const heading = element("span", undefined, "reservation-heading");
      heading.append(element("strong", `№${row.id} · ${row.equipment.name}`), badge(row.status));
      button.append(heading, element("span", `${row.equipment.inventory_number} · ${row.equipment.category}`, "d-block text-secondary small"),
        element("span", row.purpose, "d-block reservation-purpose mt-2"));
      button.addEventListener("click", () => { if (!busy) selectRow(row.id); });
      button.disabled = busy;
      list.append(button);
    }
  }

  function clearSelection() {
    selected = null;
    $("reservation-detail").replaceChildren(element("p", "Выберите запись в списке.", "text-secondary"));
    $("reservation-history").replaceChildren(element("p", "История выбранной записи появится здесь.", "text-secondary"));
  }

  async function loadList() {
    $("list-loading").hidden = false;
    const params = new URLSearchParams();
    if ($("status-filter").value) params.set("status", $("status-filter").value);
    if ($("category-filter").value) params.set("category", $("category-filter").value);
    try {
      const data = await api(`/api/reservations/?${params}`);
      if (!Array.isArray(data)) throw new ApiError("Неожиданный формат списка бронирований.");
      rows = data;
      if (selected !== null && !rows.some((row) => row.id === selected)) clearSelection();
      renderList();
    } finally {
      $("list-loading").hidden = true;
    }
  }

  function detailsField(list, label, value) {
    list.append(element("dt", label, "text-secondary small mt-2"), element("dd", value));
  }

  function renderDetails(row) {
    const panel = $("reservation-detail");
    panel.replaceChildren();
    panel.append(element("h3", `Бронирование №${row.id}`), badge(row.status));
    const list = element("dl", undefined, "mt-3");
    detailsField(list, "Оборудование", `${row.equipment.name} · ${row.equipment.inventory_number}`);
    detailsField(list, "Категория и доступность", `${row.equipment.category} · ${states[row.equipment.state] || row.equipment.state}`);
    detailsField(list, "Назначение", row.purpose);
    detailsField(list, "Владелец", row.owner.display_name);
    detailsField(list, "Создано / изменено", `${date(row.created_at)} / ${date(row.updated_at)}`);
    panel.append(list);

    if (row.status === "new") {
      const form = element("form", undefined, "border-top pt-3 mb-3");
      form.id = "edit-reservation-form";
      const device = element("select", undefined, "form-select mb-3");
      device.id = "edit-equipment";
      device.required = true;
      deviceOptions(device, row.equipment.id);
      const deviceLabel = element("label", "Экземпляр оборудования", "form-label");
      deviceLabel.htmlFor = device.id;
      const purpose = element("textarea", row.purpose, "form-control mb-3");
      purpose.id = "edit-purpose";
      purpose.maxLength = 500;
      purpose.required = true;
      const purposeLabel = element("label", "Назначение использования", "form-label");
      purposeLabel.htmlFor = purpose.id;
      const save = element("button", "Сохранить изменения", "btn btn-outline-primary");
      save.type = "submit";
      form.append(deviceLabel, device, purposeLabel, purpose, save);
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        mutate(`/api/reservations/${row.id}/`, "PATCH", {
          equipment: Number(device.value), purpose: purpose.value,
        }, "Изменения сохранены.");
      });
      panel.append(form);
    }

    const controls = element("div", undefined, "equipment-actions");
    for (const [operation, title] of actions[row.status] || []) {
      const button = element("button", title, "btn btn-primary");
      button.type = "button";
      button.dataset.action = operation;
      button.addEventListener("click", () => mutate(`/api/reservations/${row.id}/${operation}/`, "POST", {}, `${title}: выполнено.`));
      controls.append(button);
    }
    if (["new", "completed", "cancelled"].includes(row.status)) {
      const button = element("button", "Удалить бронирование", "btn btn-outline-danger");
      button.type = "button";
      button.dataset.action = "delete";
      button.addEventListener("click", () => {
        if (!busy && window.confirm(`Удалить бронирование №${row.id}? История останется в базе данных.`)) {
          mutate(`/api/reservations/${row.id}/`, "DELETE", undefined, "Бронирование удалено. История сохранена в базе данных.");
        }
      });
      controls.append(button);
    }
    panel.append(controls);
    lock(busy);
  }

  function renderHistory(events) {
    const panel = $("reservation-history");
    panel.replaceChildren();
    if (!events.length) panel.append(element("p", "История пока пуста.", "text-secondary"));
    for (const event of events) {
      const item = element("article", undefined, "event-item");
      item.append(element("strong", eventLabels[event.action] || event.action),
        element("div", `${date(event.created_at)} · ${event.actor?.display_name || "Пользователь удалён"}`, "text-secondary small"));
      if (event.from_status !== event.to_status) {
        item.append(element("div", `${labels[event.from_status] || "—"} → ${labels[event.to_status] || event.to_status}`, "small mt-1"));
      }
      for (const [field, change] of Object.entries(event.details || {})) {
        item.append(element("div", `${fieldLabels[field] || field}: ${change.old} → ${change.new}`, "event-details small mt-1"));
      }
      panel.append(item);
    }
  }

  async function loadSelected() {
    if (selected === null) return;
    const id = selected;
    $("reservation-detail").replaceChildren(element("p", "Загрузка карточки…", "text-secondary"));
    $("reservation-history").replaceChildren(element("p", "Загрузка истории…", "text-secondary"));
    try {
      const row = await api(`/api/reservations/${id}/`);
      const events = await api(`/api/reservations/${id}/history/`);
      if (!Array.isArray(events)) throw new ApiError("Неожиданный формат истории.");
      renderDetails(row);
      renderHistory(events);
    } catch (error) {
      if (error.status === 404) { clearSelection(); renderList(); }
      else {
        $("reservation-detail").replaceChildren(element("p", error.message, "text-danger"));
        $("reservation-history").replaceChildren(element("p", "Историю загрузить не удалось. Нажмите «Обновить данные».", "text-secondary"));
      }
      throw error;
    }
  }

  async function selectRow(id) {
    if (busy) return;
    lock(true);
    selected = id;
    renderList();
    loadError();
    try { await loadSelected(); } catch (error) { loadError(error.message); }
    finally { lock(false); }
  }

  async function refresh() {
    loadError();
    // Справочник обновляется первым: опции редактирования должны видеть новую доступность.
    await loadDevices();
    await loadList();
    await loadSelected();
  }

  async function mutate(url, method, body, success) {
    if (busy) return;
    lock(true);
    loadError();
    const creating = method === "POST" && url === "/api/reservations/";
    let confirmed = false;
    try {
      const result = await api(url, { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
      confirmed = true;
      if (creating) $("purpose-input").value = "";
      selected = result ? result.id : null;
      if (selected === null) clearSelection();
      message(success);
      await refresh();
      if (creating && selected === null) {
        message(`${success} Текущие фильтры скрывают новую запись.`);
      }
    } catch (error) {
      if (confirmed) loadError(`Действие сохранено, но обновить отображение не удалось. ${error.message}`);
      else {
        message(error.message, "danger");
        // Не повторяем изменение автоматически; сначала сверяемся с сервером.
        try { await refresh(); } catch (refreshError) { loadError(refreshError.message); }
      }
    } finally { lock(false); }
  }

  $("reservation-form").addEventListener("submit", (event) => {
    event.preventDefault();
    mutate("/api/reservations/", "POST", {
      equipment: Number($("equipment-input").value), purpose: $("purpose-input").value,
    }, "Бронирование создано.");
  });
  async function reload() {
    if (busy) return;
    lock(true);
    try { await refresh(); } catch (error) { loadError(error.message); }
    finally { lock(false); }
  }
  $("refresh-all").addEventListener("click", reload);
  for (const id of ["status-filter", "category-filter"]) {
    $(id).addEventListener("change", async () => {
      if (busy) return;
      lock(true);
      loadError();
      // При изменении выборки убираем прежнюю карточку до ответа сервера.
      clearSelection();
      try { await loadList(); } catch (error) { loadError(error.message); }
      finally { lock(false); }
    });
  }
  reload();
})();
