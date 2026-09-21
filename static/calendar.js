const monthLabel = document.getElementById("cal-month-label");
const gridEl = document.getElementById("cal-grid");
const prevBtn = document.getElementById("prev-month");
const nextBtn = document.getElementById("next-month");

const dayDialog = document.getElementById("day-dialog");
const dayDialogTitle = document.getElementById("day-dialog-title");
const dayEventsList = document.getElementById("day-events-list");
const eventForm = document.getElementById("event-form");
const eventIdInput = document.getElementById("event-id");
const eventDateInput = document.getElementById("event-date");
const eventTitleInput = document.getElementById("event-title");
const eventDescriptionInput = document.getElementById("event-description");
const eventModuleInput = document.getElementById("event-module");
const eventSubmitBtn = document.getElementById("event-submit");

const moduleLabels = {
  academic: "Académico",
  work: "Trabajo",
  personal: "Personal",
  general: "General",
};

const monthNames = [
  "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
];

const today = new Date();
let viewYear = today.getFullYear();
let viewMonth = today.getMonth(); // 0-indexado

let eventsByDate = {};

function pad(n) {
  return String(n).padStart(2, "0");
}

function monthKey(year, month) {
  return `${year}-${pad(month + 1)}`;
}

function dateKey(year, month, day) {
  return `${year}-${pad(month + 1)}-${pad(day)}`;
}

async function loadEvents() {
  const key = monthKey(viewYear, viewMonth);
  const res = await fetch(`/api/events?month=${key}`);
  const events = await res.json();
  eventsByDate = {};
  events.forEach((e) => {
    if (!eventsByDate[e.event_date]) eventsByDate[e.event_date] = [];
    eventsByDate[e.event_date].push(e);
  });
}

function renderGrid() {
  gridEl.innerHTML = "";
  monthLabel.textContent = `${monthNames[viewMonth]} ${viewYear}`;

  const firstDay = new Date(viewYear, viewMonth, 1);
  // La semana empieza en lunes: getDay() da 0=domingo..6=sábado.
  const firstWeekday = (firstDay.getDay() + 6) % 7;
  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();

  for (let i = 0; i < firstWeekday; i++) {
    const empty = document.createElement("div");
    empty.className = "cal-day cal-day-empty";
    gridEl.appendChild(empty);
  }

  for (let day = 1; day <= daysInMonth; day++) {
    const key = dateKey(viewYear, viewMonth, day);
    const cell = document.createElement("div");
    cell.className = "cal-day";

    const isToday =
      day === today.getDate() &&
      viewMonth === today.getMonth() &&
      viewYear === today.getFullYear();
    if (isToday) cell.classList.add("cal-day-today");

    const num = document.createElement("div");
    num.className = "cal-day-num";
    num.textContent = day;
    cell.appendChild(num);

    const dayEvents = eventsByDate[key] || [];
    if (dayEvents.length > 0) {
      const dot = document.createElement("div");
      dot.className = "cal-day-dot";
      if (dayEvents.length === 1) {
        dot.classList.add(`cal-day-dot-${dayEvents[0].module || "general"}`);
      }
      dot.textContent =
        dayEvents.length > 1 ? `${dayEvents.length} eventos` : dayEvents[0].title;
      cell.appendChild(dot);
    }

    cell.addEventListener("click", () => openDay(key, day));
    gridEl.appendChild(cell);
  }
}

async function refresh() {
  await loadEvents();
  renderGrid();
}

prevBtn.addEventListener("click", () => {
  viewMonth -= 1;
  if (viewMonth < 0) {
    viewMonth = 11;
    viewYear -= 1;
  }
  refresh();
});

nextBtn.addEventListener("click", () => {
  viewMonth += 1;
  if (viewMonth > 11) {
    viewMonth = 0;
    viewYear += 1;
  }
  refresh();
});

// ---------- Diálogo de día ----------

function resetEventForm(dateStr) {
  eventForm.reset();
  eventIdInput.value = "";
  eventDateInput.value = dateStr;
  eventModuleInput.value = "general";
  eventSubmitBtn.textContent = "Añadir evento";
}

function openDay(dateStr, day) {
  dayDialogTitle.textContent = `${day} de ${monthNames[viewMonth]}`;
  resetEventForm(dateStr);
  renderDayEvents(dateStr);
  dayDialog.showModal();
}

function renderDayEvents(dateStr) {
  dayEventsList.innerHTML = "";
  const dayEvents = eventsByDate[dateStr] || [];
  if (dayEvents.length === 0) {
    dayEventsList.innerHTML = '<p class="empty-msg-small">Sin eventos este día.</p>';
    return;
  }
  dayEvents.forEach((ev) => {
    const row = document.createElement("div");
    row.className = "event-row";

    const text = document.createElement("div");
    text.className = "event-row-text";
    const title = document.createElement("div");
    title.className = "event-row-title";
    title.textContent = ev.title;
    const badge = document.createElement("span");
    badge.className = `event-badge event-badge-${ev.module || "general"}`;
    badge.textContent = moduleLabels[ev.module] || "General";
    title.appendChild(badge);
    text.appendChild(title);
    if (ev.description) {
      const desc = document.createElement("div");
      desc.className = "event-row-desc";
      desc.textContent = ev.description;
      text.appendChild(desc);
    }

    const actions = document.createElement("div");
    actions.className = "event-row-actions";

    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.textContent = "Editar";
    editBtn.addEventListener("click", () => {
      eventIdInput.value = ev.id;
      eventDateInput.value = ev.event_date;
      eventTitleInput.value = ev.title;
      eventDescriptionInput.value = ev.description || "";
      eventModuleInput.value = ev.module || "general";
      eventSubmitBtn.textContent = "Guardar cambios";
    });

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.textContent = "Eliminar";
    delBtn.addEventListener("click", async () => {
      if (!confirm("¿Eliminar este evento?")) return;
      await fetch(`/api/events/${ev.id}`, { method: "DELETE" });
      await loadEvents();
      renderGrid();
      renderDayEvents(dateStr);
    });

    actions.appendChild(editBtn);
    actions.appendChild(delBtn);

    row.appendChild(text);
    row.appendChild(actions);
    dayEventsList.appendChild(row);
  });
}

eventForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    title: eventTitleInput.value.trim(),
    event_date: eventDateInput.value,
    description: eventDescriptionInput.value.trim(),
    module: eventModuleInput.value,
  };

  const id = eventIdInput.value;
  const url = id ? `/api/events/${id}` : "/api/events";
  const method = id ? "PUT" : "POST";

  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (res.ok) {
    const dateStr = eventDateInput.value;
    await loadEvents();
    renderGrid();
    resetEventForm(dateStr);
    renderDayEvents(dateStr);
  } else {
    const err = await res.json();
    alert(err.error || "Error al guardar el evento");
  }
});

document.getElementById("event-cancel").addEventListener("click", () => {
  resetEventForm(eventDateInput.value);
});

document.getElementById("day-dialog-close").addEventListener("click", () => dayDialog.close());

// ---------- Inicio ----------

refresh();
