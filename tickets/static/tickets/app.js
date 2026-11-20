const csrfField = document.querySelector("[name=csrfmiddlewaretoken]");
const csrfToken = csrfField ? csrfField.value : "";

const categorySelect = document.getElementById("category");
const form = document.getElementById("ticket-form");
const titleInput = document.getElementById("title");
const message = document.getElementById("message");
const list = document.getElementById("tickets-list");
const loading = document.getElementById("loading");
const filter = document.getElementById("status-filter");
const submitButton = form.querySelector('button[type="submit"]');

const STATUS_LABELS = {
    new: "Новая",
    progress: "В работе",
    done: "Выполнена"
};

const NEXT_STATUS_OPTIONS = {
    new: ["progress"],
    progress: ["done"],
    done: []
};

function showMessage(text, isError = false) {
    message.textContent = text;
    message.className = "alert " +
        (isError ? "alert-danger" : "alert-success") + " mb-3";
    message.hidden = false;
}

function getApiError(data) {
    if (data && typeof data === "object") {
        if (data.detail) {
            const detail = String(data.detail);
            if (detail.includes("Authentication credentials were not provided")) {
                return "Войдите в систему, чтобы выполнить это действие.";
            }
            if (detail.includes("Not found")) {
                return "Заявка не найдена или у вас нет к ней доступа.";
            }
            return detail;
        }

        const firstEntry = Object.entries(data)[0];
        if (firstEntry) {
            const [field, value] = firstEntry;
            const text = Array.isArray(value)
                ? value.map(String).join(" ")
                : String(value);
            const labels = {
                title: "Название заявки",
                category: "Категория",
                description: "Описание",
                status: "Статус",
                non_field_errors: ""
            };

            if (field === "category" && text.includes("Invalid pk")) {
                return "Выберите существующую категорию.";
            }
            if (field === "non_field_errors") {
                return text;
            }
            return `${labels[field] || "Ошибка"}: ${text}`;
        }
    }

    return typeof data === "string" && data
        ? data
        : "Ошибка выполнения запроса. Проверьте данные и попробуйте ещё раз.";
}

async function apiRequest(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken,
            ...(options.headers || {})
        },
        credentials: "same-origin"
    });

    let data = null;

    if (response.status !== 204) {
        const contentType = response.headers.get("content-type") || "";

        if (!contentType.includes("application/json")) {
            if (!response.ok) {
                throw new Error(
                    "Сервер отклонил запрос. Проверьте вход в систему и права доступа."
                );
            }

            throw new Error(
                "Сервер вернул не JSON. Возможно, нужно войти в систему или проверить адрес API."
            );
        }

        data = await response.json();
    }

    if (!response.ok) {
        throw new Error(getApiError(data));
    }

    return data;
}

async function loadCategories() {
    const categories = await apiRequest("/api/categories/");

    if (!Array.isArray(categories)) {
        throw new Error("Сервер вернул список категорий в неожиданном формате.");
    }

    categorySelect.replaceChildren();

    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = categories.length
        ? "Выберите категорию"
        : "Категории не найдены";
    placeholder.disabled = true;
    placeholder.selected = true;
    categorySelect.append(placeholder);

    for (const category of categories) {
        const option = document.createElement("option");
        option.value = category.id;
        option.textContent = category.name;
        categorySelect.append(option);
    }

    // Нельзя создать заявку без категории.
    submitButton.disabled = categories.length === 0;

    if (categories.length === 0) {
        showMessage(
            "Категории не найдены. Обратитесь к администратору, чтобы он добавил категории.",
            true
        );
    }
}

async function loadTickets() {
    loading.hidden = false;

    const params = new URLSearchParams();
    if (filter.value) {
        params.set("status", filter.value);
    }

    const query = params.toString();
    const url = "/api/tickets/" + (query ? "?" + query : "");

    try {
        const tickets = await apiRequest(url);

        if (!Array.isArray(tickets)) {
            throw new Error("Сервер вернул список заявок в неожиданном формате.");
        }

        list.replaceChildren();

        if (tickets.length === 0) {
            const empty = document.createElement("p");
            empty.className = "text-secondary mb-0";
            empty.textContent = "Заявки не найдены";
            list.append(empty);
            return;
        }

        for (const ticket of tickets) {
            const row = document.createElement("div");
            row.className =
                "d-flex flex-column flex-md-row justify-content-between align-items-md-center border-bottom py-3 gap-3";

            const ticketInfo = document.createElement("div");
            ticketInfo.className = "flex-fill";

            const title = document.createElement("div");
            title.className = "fw-semibold";
            title.textContent = ticket.title;

            const category = document.createElement("div");
            category.className = "text-secondary small";
            category.textContent = ticket.category_name || "Без категории";

            const status = document.createElement("span");
            const statusClasses = {
                new: "bg-azure-lt",
                progress: "bg-yellow-lt",
                done: "bg-green-lt"
            };
            status.className = "badge " + (statusClasses[ticket.status] || "bg-secondary-lt");
            status.textContent = STATUS_LABELS[ticket.status] || ticket.status;

            ticketInfo.append(title, category);

            // В списке выбора оставляем только разрешённый следующий статус.
            const allowedStatuses = NEXT_STATUS_OPTIONS[ticket.status] || [];
            const statusSelect = document.createElement("select");
            statusSelect.className = "form-select";
            statusSelect.setAttribute("aria-label", `Новый статус заявки «${ticket.title}»`);

            if (allowedStatuses.length === 0) {
                const currentOption = document.createElement("option");
                currentOption.value = ticket.status;
                currentOption.textContent = STATUS_LABELS[ticket.status] || ticket.status;
                currentOption.selected = true;
                statusSelect.append(currentOption);
                statusSelect.disabled = true;
            } else {
                for (const allowedStatus of allowedStatuses) {
                    const option = document.createElement("option");
                    option.value = allowedStatus;
                    option.textContent = STATUS_LABELS[allowedStatus] || allowedStatus;
                    statusSelect.append(option);
                }
            }

            const changeButton = document.createElement("button");
            changeButton.type = "button";
            changeButton.className = "btn btn-outline-primary";
            changeButton.textContent = "Изменить статус";
            changeButton.disabled = allowedStatuses.length === 0;
            changeButton.addEventListener("click", () => {
                changeStatus(ticket.id, statusSelect.value, ticket.status);
            });

            const deleteButton = document.createElement("button");
            deleteButton.type = "button";
            deleteButton.className = "btn btn-outline-danger";
            deleteButton.textContent = "Удалить";
            deleteButton.addEventListener("click", () => {
                deleteTicket(ticket.id, ticket.title);
            });

            const actions = document.createElement("div");
            actions.className = "d-flex align-items-center gap-2 flex-wrap";
            actions.append(statusSelect, changeButton, deleteButton);

            const statusArea = document.createElement("div");
            statusArea.className = "d-flex align-items-center gap-2";
            statusArea.append(status);

            row.append(ticketInfo, statusArea, actions);
            list.append(row);
        }
    } catch (error) {
        showMessage("Не удалось загрузить заявки: " + error.message, true);
    } finally {
        loading.hidden = true;
    }
}

async function changeStatus(ticketId, newStatus, currentStatus) {
    const allowedStatuses = NEXT_STATUS_OPTIONS[currentStatus] || [];

    if (!allowedStatuses.includes(newStatus)) {
        showMessage("Выбран недопустимый переход статуса.", true);
        return;
    }

    try {
        await apiRequest(`/api/tickets/${ticketId}/`, {
            method: "PATCH",
            body: JSON.stringify({ status: newStatus })
        });

        showMessage("Статус заявки изменён.");
        await loadTickets();
    } catch (error) {
        showMessage("Не удалось изменить статус: " + error.message, true);
    }
}

async function deleteTicket(ticketId, ticketTitle) {
    const confirmed = confirm(`Удалить заявку «${ticketTitle}»?`);
    if (!confirmed) {
        return;
    }

    try {
        await apiRequest(`/api/tickets/${ticketId}/`, {
            method: "DELETE"
        });

        showMessage("Заявка удалена.");
        await loadTickets();
    } catch (error) {
        showMessage("Не удалось удалить заявку: " + error.message, true);
    }
}

form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const title = titleInput.value.trim();
    const categoryId = categorySelect.value;

    if (!categoryId) {
        showMessage("Выберите категорию заявки.", true);
        return;
    }

    try {
        await apiRequest("/api/tickets/", {
            method: "POST",
            body: JSON.stringify({
                title: title,
                category: Number(categoryId)
            })
        });

        titleInput.value = "";
        showMessage("Заявка успешно создана.");
        await loadTickets();
    } catch (error) {
        showMessage("Не удалось создать заявку: " + error.message, true);
    }
});

filter.addEventListener("change", loadTickets);

async function initialize() {
    try {
        await loadCategories();
    } catch (error) {
        showMessage("Не удалось загрузить категории: " + error.message, true);
    }

    await loadTickets();
}

initialize();
