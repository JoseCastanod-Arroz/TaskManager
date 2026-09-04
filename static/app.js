const complexityLabels = { 1: "Baja", 2: "Media", 3: "Alta" };

const taskListEl = document.getElementById("task-list");
const sortBySel = document.getElementById("sort-by");
const orderSel = document.getElementById("order");
const subjectFilterSel = document.getElementById("subject-filter");
const groupCheckbox = document.getElementById("group-by-subject");

const taskDialog = document.getElementById("task-dialog");
const taskForm = document.getElementById("task-form");
const taskDialogTitle = document.getElementById("task-dialog-title");
const taskIdInput = document.getElementById("task-id");
const taskTitleInput = document.getElementById("task-title");
const taskSubjectInput = document.getElementById("task-subject");
const taskDueDateInput = document.getElementById("task-due-date");
const taskComplexityInput = document.getElementById("task-complexity");
const taskDescriptionInput = document.getElementById("task-description");

const detailDialog = document.getElementById("detail-dialog");
const detailContent = document.getElementById("detail-content");

function buildQuery() {
  const params = new URLSearchParams();
  params.set("sort_by", sortBySel.value);
  params.set("order", orderSel.value);
  if (subjectFilterSel.value) params.set("subject", subjectFilterSel.value);
  if (groupCheckbox.checked) params.set("group_by", "subject");
  return params.toString();
}

async function loadSubjects() {
  const res = await fetch("/api/subjects");
  const subjects = await res.json();
  const current = subjectFilterSel.value;
  subjectFilterSel.innerHTML = '<option value="">Todas</option>';
  subjects.forEach((s) => {
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = s;
    subjectFilterSel.appendChild(opt);
  });
  subjectFilterSel.value = current;
}

async function loadTasks() {
  const res = await fetch(`/api/tasks?${buildQuery()}`);
  const data = await res.json();
  taskListEl.innerHTML = "";

  if (groupCheckbox.checked) {
    const subjects = Object.keys(data);
    if (subjects.length === 0) {
      taskListEl.innerHTML = '<p class="empty-msg">No hay tareas registradas.</p>';
      return;
    }
    subjects.forEach((subject) => {
      const heading = document.createElement("div");
      heading.className = "group-heading";
      heading.textContent = subject;
      taskListEl.appendChild(heading);
      data[subject].forEach((t) => taskListEl.appendChild(renderTaskCard(t)));
    });
  } else {
    if (data.length === 0) {
      taskListEl.innerHTML = '<p class="empty-msg">No hay tareas registradas.</p>';
      return;
    }
    data.forEach((t) => taskListEl.appendChild(renderTaskCard(t)));
  }
}

function urgencyBadge(t) {
  if (t.urgency_score === undefined) return "";
  if (!t.due_date) return '<span class="badge badge-urgency">Sin fecha</span>';
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(t.due_date + "T00:00:00");
  const daysLeft = Math.round((due - today) / 86400000);

  let label, cls;
  if (daysLeft < 0) {
    label = "Vencida";
    cls = "badge-urgency-critical";
  } else if (t.urgency_score >= 30) {
    label = "Muy urgente";
    cls = "badge-urgency-critical";
  } else if (t.urgency_score >= 10) {
    label = "Urgente";
    cls = "badge-urgency-high";
  } else {
    label = "Tranquila";
    cls = "badge-urgency-low";
  }
  return `<span class="badge badge-urgency ${cls}">${label}</span>`;
}

function renderTaskCard(t) {
  const card = document.createElement("div");
  card.className = "task-card";

  const main = document.createElement("div");
  main.className = "task-main";

  const title = document.createElement("div");
  title.className = "task-title";
  title.textContent = t.title;
  title.addEventListener("click", () => openDetail(t.id));

  const meta = document.createElement("div");
  meta.className = "task-meta";
  meta.innerHTML = `
    <span class="badge">${complexityLabels[t.complexity] || t.complexity}</span>
    <span>${t.due_date || "sin fecha"}</span>
    <span>${t.subtasks_done || 0}/${t.subtasks_total || 0} subtareas</span>
    ${urgencyBadge(t)}
  `;

  main.appendChild(title);
  main.appendChild(meta);

  const actions = document.createElement("div");
  actions.className = "task-actions";

  const editBtn = document.createElement("button");
  editBtn.textContent = "Editar";
  editBtn.addEventListener("click", () => openTaskDialog(t));

  const delBtn = document.createElement("button");
  delBtn.textContent = "Eliminar";
  delBtn.addEventListener("click", () => deleteTask(t.id));

  actions.appendChild(editBtn);
  actions.appendChild(delBtn);

  card.appendChild(main);
  card.appendChild(actions);
  return card;
}

// ---------- Diálogo tarea (crear / editar) ----------

function openTaskDialog(task) {
  taskForm.reset();
  if (task) {
    taskDialogTitle.textContent = "Editar tarea";
    taskIdInput.value = task.id;
    taskTitleInput.value = task.title;
    taskSubjectInput.value = task.subject;
    taskDueDateInput.value = task.due_date || "";
    taskComplexityInput.value = task.complexity;
    taskDescriptionInput.value = task.description || "";
  } else {
    taskDialogTitle.textContent = "Nueva tarea";
    taskIdInput.value = "";
  }
  taskDialog.showModal();
}

document.getElementById("new-task-btn").addEventListener("click", () => openTaskDialog(null));
document.getElementById("task-cancel").addEventListener("click", () => taskDialog.close());

taskForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    title: taskTitleInput.value.trim(),
    subject: taskSubjectInput.value.trim(),
    due_date: taskDueDateInput.value || null,
    complexity: parseInt(taskComplexityInput.value, 10),
    description: taskDescriptionInput.value.trim(),
  };

  const id = taskIdInput.value;
  const url = id ? `/api/tasks/${id}` : "/api/tasks";
  const method = id ? "PUT" : "POST";

  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (res.ok) {
    taskDialog.close();
    await loadSubjects();
    await loadTasks();
  } else {
    const err = await res.json();
    alert(err.error || "Error al guardar la tarea");
  }
});

async function deleteTask(id) {
  if (!confirm("¿Eliminar esta tarea y sus subtareas?")) return;
  await fetch(`/api/tasks/${id}`, { method: "DELETE" });
  await loadSubjects();
  await loadTasks();
}

// ---------- Detalle / subtareas ----------

async function openDetail(taskId) {
  const res = await fetch(`/api/tasks/${taskId}`);
  const task = await res.json();
  renderDetail(task);
  detailDialog.showModal();
}

function renderDetail(task) {
  detailContent.innerHTML = "";

  const title = document.createElement("h2");
  title.textContent = task.title;
  detailContent.appendChild(title);

  const meta = document.createElement("div");
  meta.className = "task-meta";
  meta.style.marginBottom = "0.75rem";
  meta.innerHTML = `
    <span class="badge">${complexityLabels[task.complexity] || task.complexity}</span>
    <span>${task.subject}</span>
    <span>${task.due_date || "sin fecha"}</span>
  `;
  detailContent.appendChild(meta);

  if (task.description) {
    const desc = document.createElement("p");
    desc.style.fontSize = "0.9rem";
    desc.style.color = "var(--muted)";
    desc.textContent = task.description;
    detailContent.appendChild(desc);
  }

  const subtaskList = document.createElement("div");
  subtaskList.id = "subtask-list";
  task.subtasks.forEach((s) => subtaskList.appendChild(renderSubtaskRow(task.id, s)));
  detailContent.appendChild(subtaskList);

  const newRow = document.createElement("div");
  newRow.id = "new-subtask-row";
  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Nueva subtarea";
  const addBtn = document.createElement("button");
  addBtn.textContent = "Añadir";
  addBtn.addEventListener("click", async () => {
    const value = input.value.trim();
    if (!value) return;
    await fetch(`/api/tasks/${task.id}/subtasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: value }),
    });
    await openDetail(task.id);
    await loadTasks();
  });
  newRow.appendChild(input);
  newRow.appendChild(addBtn);
  detailContent.appendChild(newRow);
}

function renderSubtaskRow(taskId, s) {
  const row = document.createElement("div");
  row.className = "subtask-row" + (s.completed ? " done" : "");

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = !!s.completed;
  checkbox.addEventListener("change", async () => {
    await fetch(`/api/subtasks/${s.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ completed: checkbox.checked }),
    });
    await openDetail(taskId);
    await loadTasks();
  });

  const text = document.createElement("span");
  text.className = "subtask-text";
  text.textContent = s.title;

  const delBtn = document.createElement("button");
  delBtn.textContent = "×";
  delBtn.title = "Eliminar subtarea";
  delBtn.addEventListener("click", async () => {
    await fetch(`/api/subtasks/${s.id}`, { method: "DELETE" });
    await openDetail(taskId);
    await loadTasks();
  });

  row.appendChild(checkbox);
  row.appendChild(text);
  row.appendChild(delBtn);
  return row;
}

document.getElementById("detail-close").addEventListener("click", () => detailDialog.close());

// ---------- Eventos de filtros ----------

sortBySel.addEventListener("change", () => {
  // Al elegir "Urgencia" tiene más sentido ver primero lo más urgente.
  if (sortBySel.value === "urgency") {
    orderSel.value = "desc";
  }
  loadTasks();
});

[orderSel, subjectFilterSel, groupCheckbox].forEach((el) =>
  el.addEventListener("change", loadTasks)
);

// ---------- Inicio ----------

(async function init() {
  await loadSubjects();
  await loadTasks();
})();
