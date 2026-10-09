// Línea del día: renderiza la línea de tiempo (ordenada) y el selector de
// tareas disponibles agrupadas por naturaleza. La base de la API se inyecta
// desde la plantilla vía window.APP_CONFIG (ver line.html).
const apiBase = (window.APP_CONFIG && window.APP_CONFIG.apiBase) || "/api/line";

// Etiquetas de módulo para los encabezados de grupo del selector. La
// línea de tiempo usa el campo `nature` que ya devuelve la API.
const moduleLabels = {
  academic: "Académico",
  work: "Trabajo",
  personal: "Personal",
};

// La línea reutiliza los endpoints de subtareas de cada módulo de tareas
// (tasks_module) para marcar completada o eliminar una subtarea sin salir de
// la línea del día. Cada módulo expone su propio prefijo.
const subtaskApiPrefixes = {
  academic: "/api/subtasks",
  work: "/api/work-subtasks",
  personal: "/api/personal-subtasks",
};

// Prefijos de la API de tareas por módulo, para eliminar la tarea completa
// (la tarea subyacente) desde la línea del día.
const taskApiPrefixes = {
  academic: "/api/tasks",
  work: "/api/work-tasks",
  personal: "/api/personal-tasks",
};

const timelineEl = document.getElementById("line-timeline");
const pickerEl = document.getElementById("line-picker");

// ---------- Línea de tiempo ----------

async function loadLine() {
  try {
    const res = await fetch(`${apiBase}`);
    if (!res.ok) {
      renderLineError();
      return;
    }
    const items = await res.json();
    renderLine(items);
  } catch (err) {
    renderLineError();
  }
}

function renderLineError() {
  if (!timelineEl) return;
  timelineEl.innerHTML =
    '<p class="empty-msg-small">No se pudo cargar la línea.</p>';
}

function renderLine(items) {
  if (!timelineEl) return;
  timelineEl.innerHTML = "";

  if (!items || items.length === 0) {
    timelineEl.innerHTML =
      '<p class="empty-msg-small">La línea está vacía. Añade tareas desde el selector.</p>';
    return;
  }

  // La API ya devuelve los items ordenados por `position`. Conservamos la
  // lista actual de item_ids para calcular los reordenamientos (FR-07).
  const ul = document.createElement("ul");
  ul.className = "line-timeline";

  const itemIds = items.map((item) => item.item_id);
  items.forEach((item, index) => {
    ul.appendChild(renderLineItem(item, index, items.length, itemIds));
  });

  timelineEl.appendChild(ul);
}

function renderLineItem(item, index, total, itemIds) {
  const task = item.task || {};

  // Contenedor por item. Clases alineadas con line.css: .line-item,
  // .line-point, .line-item-body, .line-item-head/-main, .line-controls.
  const wrapper = document.createElement("li");
  wrapper.className = "line-item";
  wrapper.dataset.itemId = item.item_id;
  wrapper.dataset.module = item.module;

  const point = document.createElement("div");
  point.className = "line-point";
  wrapper.appendChild(point);

  const body = document.createElement("div");
  body.className = "line-item-body";

  // Fila de cabecera: título + naturaleza a la izquierda, controles a la
  // derecha (reordenar/eliminar).
  const head = document.createElement("div");
  head.className = "line-item-head";

  const main = document.createElement("div");
  main.className = "line-item-main";

  const title = document.createElement("div");
  title.className = "line-item-title";
  title.textContent = task.title || "";

  const nature = document.createElement("span");
  nature.className = "line-nature";
  if (item.module) nature.classList.add(`line-nature-${item.module}`);
  nature.textContent = item.nature || moduleLabels[item.module] || "";
  title.appendChild(nature);

  main.appendChild(title);
  head.appendChild(main);

  // Controles de reordenar/eliminar (FR-06, FR-07).
  const controls = document.createElement("div");
  controls.className = "line-controls";

  const upBtn = document.createElement("button");
  upBtn.type = "button";
  upBtn.className = "line-control-up";
  upBtn.textContent = "↑";
  upBtn.setAttribute("aria-label", "Subir");
  upBtn.disabled = index === 0;
  upBtn.addEventListener("click", () => moveItem(itemIds, index, -1));
  controls.appendChild(upBtn);

  const downBtn = document.createElement("button");
  downBtn.type = "button";
  downBtn.className = "line-control-down";
  downBtn.textContent = "↓";
  downBtn.setAttribute("aria-label", "Bajar");
  downBtn.disabled = index === total - 1;
  downBtn.addEventListener("click", () => moveItem(itemIds, index, 1));
  controls.appendChild(downBtn);

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "line-control-remove";
  removeBtn.textContent = "Quitar";
  removeBtn.setAttribute("aria-label", "Quitar de la línea");
  removeBtn.title = "Quitar de la línea (la tarea se conserva)";
  removeBtn.addEventListener("click", () => removeItem(item.item_id, removeBtn));
  controls.appendChild(removeBtn);

  // Eliminar la tarea completa (la tarea subyacente). Es destructivo: borra la
  // tarea original de su módulo; su ítem de línea queda colgante y lo barre
  // `sweep_dangling` en la siguiente lectura.
  const deleteTaskBtn = document.createElement("button");
  deleteTaskBtn.type = "button";
  deleteTaskBtn.className = "line-control-delete-task";
  deleteTaskBtn.textContent = "Terminar tarea";
  deleteTaskBtn.setAttribute("aria-label", "Terminar la tarea");
  deleteTaskBtn.title = "Terminar la tarea (se elimina por completo)";
  deleteTaskBtn.addEventListener("click", () =>
    deleteTask(item.module, task.id, task.title || "", deleteTaskBtn)
  );
  controls.appendChild(deleteTaskBtn);

  head.appendChild(controls);
  body.appendChild(head);

  // Divulgación de subtareas (FR-09/FR-10): colapsadas por defecto; un
  // botón las revela/oculta. Sin subtareas no se renderiza el control.
  const subtasks = task.subtasks || [];
  if (subtasks.length > 0) {
    const subList = document.createElement("ul");
    subList.className = "line-subtasks collapsed";
    subList.hidden = true;
    subtasks.forEach((st) => {
      const li = document.createElement("li");
      li.className = "line-subtask";
      if (st.completed) li.classList.add("done");
      li.dataset.subtaskId = st.id;

      // Checkbox para marcar/desmarcar la subtarea como completada, sin salir
      // de la línea del día. Delega en el endpoint del módulo correspondiente.
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "line-subtask-check";
      checkbox.checked = !!st.completed;
      checkbox.setAttribute("aria-label", "Marcar subtarea como completada");
      checkbox.addEventListener("change", () =>
        toggleSubtask(item.module, st.id, checkbox.checked, checkbox)
      );
      li.appendChild(checkbox);

      const text = document.createElement("span");
      text.className = "line-subtask-text";
      text.textContent = st.title || "";
      li.appendChild(text);

      // Botón para eliminar la subtarea cuando ya está terminada.
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "line-subtask-remove";
      delBtn.textContent = "✕";
      delBtn.setAttribute("aria-label", "Eliminar subtarea");
      delBtn.addEventListener("click", () =>
        removeSubtask(item.module, st.id, delBtn)
      );
      li.appendChild(delBtn);

      subList.appendChild(li);
    });

    const disclosure = document.createElement("button");
    disclosure.type = "button";
    disclosure.className = "line-disclosure";
    disclosure.setAttribute("aria-expanded", "false");
    setDisclosureLabel(disclosure, subtasks.length, false);
    disclosure.addEventListener("click", () =>
      toggleSubtasks(disclosure, subList, subtasks.length)
    );

    body.appendChild(disclosure);
    body.appendChild(subList);
  }

  wrapper.appendChild(body);
  return wrapper;
}

// Actualiza el texto/indicador del control de divulgación según el estado.
function setDisclosureLabel(disclosure, count, expanded) {
  const indicator = expanded ? "▾" : "▸";
  disclosure.textContent = `${indicator} Subtareas (${count})`;
}

// Alterna la visibilidad del subárbol de subtareas (revelar/ocultar).
function toggleSubtasks(disclosure, subList, count) {
  const willExpand = subList.classList.contains("collapsed") || subList.hidden;
  if (willExpand) {
    subList.classList.remove("collapsed");
    subList.hidden = false;
  } else {
    subList.classList.add("collapsed");
    subList.hidden = true;
  }
  disclosure.setAttribute("aria-expanded", willExpand ? "true" : "false");
  setDisclosureLabel(disclosure, count, willExpand);
}

// ---------- Reordenar (FR-07) ----------

// Mueve el item en `index` por `delta` (−1 arriba, +1 abajo) y envía el
// nuevo orden completo de item_ids a la API.
async function moveItem(itemIds, index, delta) {
  const target = index + delta;
  if (target < 0 || target >= itemIds.length) return;

  const reordered = itemIds.slice();
  const [moved] = reordered.splice(index, 1);
  reordered.splice(target, 0, moved);

  await reorderLine(reordered);
}

async function reorderLine(itemIds) {
  try {
    const res = await fetch(`${apiBase}/order`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_ids: itemIds }),
    });

    if (res.ok) {
      await loadLine();
      return;
    }

    const err = await res.json().catch(() => ({}));
    alert(err.error || "No se pudo reordenar la línea");
  } catch (err) {
    alert("No se pudo reordenar la línea");
  }
}

// ---------- Eliminar de la línea (FR-06) ----------

async function removeItem(itemId, btn) {
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`${apiBase}/items/${itemId}`, {
      method: "DELETE",
    });

    if (res.ok) {
      // La tarea vuelve a estar disponible: refrescar línea y selector.
      await loadLine();
      await loadPicker();
      return;
    }

    const err = await res.json().catch(() => ({}));
    alert(err.error || "No se pudo quitar la tarea de la línea");
    if (btn) btn.disabled = false;
  } catch (err) {
    alert("No se pudo quitar la tarea de la línea");
    if (btn) btn.disabled = false;
  }
}

// ---------- Subtareas: marcar completada / eliminar ----------

// Marca o desmarca una subtarea como completada reutilizando el endpoint del
// módulo (academic/work/personal). Actualiza el DOM EN EL SITIO (no recarga la
// línea) para que el despliegue de subtareas permanezca abierto: solo el
// usuario lo cierra.
async function toggleSubtask(module, subtaskId, completed, checkbox) {
  const prefix = subtaskApiPrefixes[module];
  if (!prefix) return;
  const li = checkbox ? checkbox.closest(".line-subtask") : null;
  if (checkbox) checkbox.disabled = true;
  try {
    const res = await fetch(`${prefix}/${subtaskId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ completed }),
    });
    if (res.ok) {
      if (li) li.classList.toggle("done", completed);
      if (checkbox) checkbox.disabled = false;
      return;
    }
    const err = await res.json().catch(() => ({}));
    alert(err.error || "No se pudo actualizar la subtarea");
    if (checkbox) {
      checkbox.checked = !completed;
      checkbox.disabled = false;
    }
  } catch (err) {
    alert("No se pudo actualizar la subtarea");
    if (checkbox) {
      checkbox.checked = !completed;
      checkbox.disabled = false;
    }
  }
}

// Elimina una subtarea (p. ej. cuando ya se terminó) reutilizando el endpoint
// del módulo. Quita su fila del DOM EN EL SITIO (sin recargar la línea) para
// que el despliegue siga abierto, y actualiza el contador del control de
// divulgación. Si era la última subtarea, retira el despliegue por completo.
async function removeSubtask(module, subtaskId, btn) {
  const prefix = subtaskApiPrefixes[module];
  if (!prefix) return;
  const li = btn ? btn.closest(".line-subtask") : null;
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`${prefix}/${subtaskId}`, { method: "DELETE" });
    if (res.ok) {
      if (li) {
        const subList = li.closest(".line-subtasks");
        li.remove();
        updateDisclosureAfterRemoval(subList);
      }
      return;
    }
    const err = await res.json().catch(() => ({}));
    alert(err.error || "No se pudo eliminar la subtarea");
    if (btn) btn.disabled = false;
  } catch (err) {
    alert("No se pudo eliminar la subtarea");
    if (btn) btn.disabled = false;
  }
}

// Tras quitar una subtarea del DOM, recalcula el contador del control de
// divulgación. Si ya no quedan subtareas, elimina tanto la lista como el
// botón de divulgación del ítem.
function updateDisclosureAfterRemoval(subList) {
  if (!subList) return;
  const remaining = subList.querySelectorAll(".line-subtask").length;
  const body = subList.closest(".line-item-body");
  const disclosure = body ? body.querySelector(".line-disclosure") : null;
  if (remaining === 0) {
    if (disclosure) disclosure.remove();
    subList.remove();
    return;
  }
  if (disclosure) {
    const expanded = disclosure.getAttribute("aria-expanded") === "true";
    setDisclosureLabel(disclosure, remaining, expanded);
  }
}

// ---------- Eliminar la tarea completa ----------

// Elimina la tarea subyacente de su módulo (academic/work/personal). Pide
// confirmación por ser destructivo. Al borrarse, su ítem de línea queda
// colgante y `sweep_dangling` lo retira; por eso refrescamos línea y selector.
async function deleteTask(module, taskId, taskTitle, btn) {
  const prefix = taskApiPrefixes[module];
  if (!prefix) return;
  const label = taskTitle ? `"${taskTitle}"` : "esta tarea";
  if (!confirm(`¿Terminar ${label}? Se eliminará por completo y no se puede deshacer.`)) {
    return;
  }
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`${prefix}/${taskId}`, { method: "DELETE" });
    if (res.ok) {
      await loadLine();
      await loadPicker();
      return;
    }
    const err = await res.json().catch(() => ({}));
    alert(err.error || "No se pudo eliminar la tarea");
    if (btn) btn.disabled = false;
  } catch (err) {
    alert("No se pudo eliminar la tarea");
    if (btn) btn.disabled = false;
  }
}

// ---------- Selector de tareas disponibles ----------

async function loadPicker() {
  try {
    const res = await fetch(`${apiBase}/available`);
    if (!res.ok) {
      renderPickerError();
      return;
    }
    const grouped = await res.json();
    renderPicker(grouped);
  } catch (err) {
    renderPickerError();
  }
}

function renderPickerError() {
  if (!pickerEl) return;
  pickerEl.innerHTML =
    '<p class="empty-msg-small">No se pudieron cargar las tareas.</p>';
}

function renderPicker(grouped) {
  if (!pickerEl) return;
  pickerEl.innerHTML = "";

  const modules = Object.keys(grouped || {});
  const hasAny = modules.some((m) => (grouped[m] || []).length > 0);
  if (!hasAny) {
    pickerEl.innerHTML =
      '<p class="line-picker-empty">No hay tareas disponibles.</p>';
    return;
  }

  modules.forEach((module) => {
    const tasks = grouped[module] || [];
    if (tasks.length === 0) return;

    const group = document.createElement("div");
    group.className = "line-group";
    group.dataset.module = module;

    const heading = document.createElement("h3");
    heading.className = "line-group-title";
    heading.textContent = moduleLabels[module] || module;
    group.appendChild(heading);

    const list = document.createElement("ul");
    list.className = "line-picker-list";

    tasks.forEach((task) => {
      list.appendChild(renderPickerItem(module, task));
    });

    group.appendChild(list);
    pickerEl.appendChild(group);
  });
}

function renderPickerItem(module, task) {
  const li = document.createElement("li");
  li.className = "line-available-task";
  li.dataset.module = module;
  li.dataset.taskId = task.id;

  const title = document.createElement("span");
  title.className = "line-available-task-title";
  title.textContent = task.title || "";
  li.appendChild(title);

  const addBtn = document.createElement("button");
  addBtn.type = "button";
  addBtn.textContent = "Añadir";
  addBtn.addEventListener("click", () => addItem(module, task.id, addBtn));
  li.appendChild(addBtn);

  return li;
}

// ---------- Añadir a la línea ----------

async function addItem(module, taskId, btn) {
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`${apiBase}/items`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ module, task_id: taskId }),
    });

    if (res.ok) {
      // Refrescar la línea (y el selector) tras añadir.
      await loadLine();
      await loadPicker();
      return;
    }

    const err = await res.json().catch(() => ({}));
    alert(err.error || "No se pudo añadir la tarea a la línea");
    if (btn) btn.disabled = false;
  } catch (err) {
    alert("No se pudo añadir la tarea a la línea");
    if (btn) btn.disabled = false;
  }
}

// ---------- Inicio ----------

loadLine();
loadPicker();
