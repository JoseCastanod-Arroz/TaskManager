# Requirements: Line of Task (TaskManager)

Oct 9, 2026 · @Jose Castaño

## Scope

TaskManager gets a new section called "Line of task", where the user builds the list of activities for the day by choosing from tasks that already exist in the database. The section does not create new tasks: it only selects and orders them.

The "nature" of a task (academic, personal or work) is **not** a new field: it is derived from the module/table the task already belongs to (`tasks` → academic, `work_tasks` → work, `personal_tasks` → personal). No schema change is made to the existing task tables.

## Data Model

A Line of task is a new, ordered list of references to tasks that already exist. Because tasks live in three separate per-module tables, a task is identified by the pair `(module, task_id)`, never by `task_id` alone.

| Entity | Description |
| --- | --- |
| Line | One line per user (the user's "line of the day"). Belongs to a `user_id`. |
| Line item | A reference inside a line. Stores `module` (`academic`/`work`/`personal`), `task_id` (id within that module's table) and `position` (order within the line). |

## Functional Requirements

### Categorization

| ID | Requirement |
| --- | --- |
| FR-01 | A task's nature (academic, personal or work) is derived from the module/table it belongs to, with no new field added to the task tables. |
| FR-02 | Existing tasks can be viewed grouped by nature (i.e. by module of origin). |

### Building the Line

| ID | Requirement |
| --- | --- |
| FR-04 | The user creates a Line of task by selecting tasks that already exist in the database. |
| FR-05 | A single line can mix tasks of different natures (items from different modules). |
| FR-06 | The user can add tasks to and remove tasks from the line. |
| FR-07 | The user can define the order of the tasks within the line (`position`). |
| FR-11 | When a referenced task is deleted from its module, its corresponding line item is removed from the line. |

### Visualization

| ID | Requirement |
| --- | --- |
| FR-08 | The line is displayed as a vertical timeline, where each point represents a task. |
| FR-09 | Each task can optionally expand to show its list of subtasks, forming a tree structure. |
| FR-10 | Subtasks can be collapsed and expanded at any time, and are collapsed by default. |

## Non-Functional Requirements

| ID | Requirement |
| --- | --- |
| NFR-01 | Keep the sober, minimalist design of the rest of the app, with no extra colors or features. |
| NFR-02 | Reuse the current stack (Flask, SQLite, HTML). The new endpoints follow the existing session/cookie authentication pattern used by the internal task modules (not the external `/api/v1` Bearer API). |
| NFR-03 | Existing tasks and modules must keep working without breaking; no changes to the existing task table schemas. |
