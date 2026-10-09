# Implementation Plan: Line of Task (TaskManager)

## Overview

This plan implements the "Línea del día" feature as a self-contained Flask blueprint (`line_module.py`) that references existing tasks across the three per-module tables, orders them, and resolves/sweeps dangling references on read. It mirrors the structure of `calendar_module.py` (session guard, `init_db`, page route, JSON API over `database.get_connection()`), wires into `app.py` and `nav.py`, and adds the `templates/line.html` + `static/line.js` + `static/line.css` frontend.

Tasks build incrementally: schema and helpers first, then the API endpoints, then wiring, then the frontend, with property-based and example tests placed next to the code they validate. All code follows existing conventions (Spanish-labeled JSON errors, `sqlite3.Row` serialization, per-user isolation via `user_id`, `pytest + Hypothesis` with the existing `tests/conftest.py` fixtures and `tests/strategies.py` generators).

## Tasks

- [x] 1. Create `line_module.py` skeleton: blueprint, constants, schema, and session guard
  - [x] 1.1 Define blueprint, module maps, and `init_db()` for the new tables
    - Create `line_module.py` with `line_bp = Blueprint("line", __name__)`, `MODULE_LABELS`, `VALID_MODULES`, and `TASK_MODULES` (mirroring `calendar_module.py` / `api_module.py`).
    - Implement `line_bp.init_db()` creating `line` (with `user_id UNIQUE`, FK to `users`) and `line_items` (with `line_id` FK, `module`, `task_id`, `position`, `UNIQUE(line_id, module, task_id)`) using `CREATE TABLE IF NOT EXISTS` via `database.get_connection()`.
    - _Requirements: 1.1, NFR-02, NFR-03_

  - [x] 1.2 Add the session guard `before_request`
    - Add `@line_bp.before_request require_login()` matching the calendar/task pattern: pass when `session.get("user_id")`, return `401 {"error": "No autorizado"}` for `/api/` paths, redirect to `auth.login` with `next` otherwise.
    - _Requirements: NFR-02_

  - [ ]* 1.3 Write schema/no-regression tests for `init_db`
    - Reuse `temp_db`/`connection` fixtures; assert `line` and `line_items` exist with expected columns, and that `PRAGMA table_info` of `tasks`/`work_tasks`/`personal_tasks` is unchanged after `init_db`.
    - _Requirements: NFR-03_

- [x] 2. Implement core line logic helpers in `line_module.py`
  - [x] 2.1 Implement `get_or_create_line` and `task_exists`
    - `get_or_create_line(conn, user_id)` returns the user's single line id, inserting the `line` row if absent.
    - `task_exists(conn, module, task_id, user_id)` returns True only when `(module, task_id)` is a task owned by `user_id` in that module's table (uses `TASK_MODULES`).
    - _Requirements: 1.4, NFR-03_

  - [x] 2.2 Implement `resolve_line` and `sweep_dangling`
    - `sweep_dangling(conn, line_id)` deletes `line_items` whose `(module, task_id)` target no longer exists, returns count removed.
    - `resolve_line(conn, user_id)` calls `sweep_dangling`, then returns items ordered by `position ASC`, each with resolved task fields and a `subtasks` list (ordered by `id ASC`, always present) in the serialized shape from the design.
    - _Requirements: 1.9, 1.11_

  - [x] 2.3 Implement position normalization helper
    - Add a helper that renumbers a line's `line_items.position` to a contiguous gap-free `0..n-1` sequence by current order; call it after every add/remove/reorder inside a transaction with `rollback` on exception.
    - _Requirements: 1.7_

  - [ ]* 2.4 Write property test for nature derivation
    - **Property 1: Nature is derived from module**
    - **Validates: Requirements 1.1**
    - Tag: `# Feature: LineTask, Property 1: Nature is derived from module`; `@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])`.

  - [ ]* 2.5 Write property test for resolved subtask subtree
    - **Property 7: Resolved items always include their subtask subtree**
    - **Validates: Requirements 1.9**
    - Reuse `tasks`/`subtasks` strategies and `insert_*` helpers; add a small helper to materialize a line + items.

  - [ ]* 2.6 Write property test for dangling-reference sweep
    - **Property 6: Deleting a referenced task removes its line item**
    - **Validates: Requirements 1.11**

- [x] 3. Checkpoint - core logic
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement the read API endpoints
  - [x] 4.1 Implement `GET /api/line`
    - Return the current user's ordered, swept line via `resolve_line` as a JSON array of serialized line items.
    - _Requirements: 1.9, 1.11_

  - [x] 4.2 Implement `GET /api/line/available`
    - Return the user's existing tasks grouped by nature (keyed by module), filtering by `user_id`; honor optional `?module=academic|work|personal` to return a single group; `400` on invalid module.
    - _Requirements: 1.2, 1.5_

  - [ ]* 4.3 Write property test for available-tasks grouping isolation
    - **Property 2: Available tasks are grouped by nature with owner/module isolation**
    - **Validates: Requirements 1.2**
    - Seed tasks for multiple users across all three modules; assert returned tasks are exactly the caller's and each appears only under its own module group.

- [x] 5. Implement the mutation API endpoints
  - [x] 5.1 Implement `POST /api/line/items`
    - Parse `{"module", "task_id"}`; `400` on missing/invalid module; `404` when `(module, task_id)` is not owned/existing (via `task_exists`); `409` when the pair already exists in the line; otherwise append at end, normalize positions, return `201` with the resolved item.
    - _Requirements: 1.4, 1.5, 1.6_

  - [x] 5.2 Implement `DELETE /api/line/items/<int:item_id>`
    - Remove the item only if it belongs to the session user's line (`404` otherwise); normalize positions; return `200 {"ok": true}`.
    - _Requirements: 1.6, 1.7_

  - [x] 5.3 Implement `PUT /api/line/order`
    - Parse `{"item_ids": [...]}`; `400` unless the set exactly matches the user's current item ids (no missing/extra/foreign/duplicate ids); apply the permutation, normalize positions, return `200` reordered line. Wrap in a transaction with `rollback`.
    - _Requirements: 1.7_

  - [ ]* 5.4 Write property test for add/remove membership and uniqueness
    - **Property 3: Add/remove membership and uniqueness**
    - **Validates: Requirements 1.4, 1.6**

  - [ ]* 5.5 Write property test for mixed-nature lines
    - **Property 4: A line may mix tasks of different natures**
    - **Validates: Requirements 1.5**

  - [ ]* 5.6 Write property test for ordering permutation and contiguous positions
    - **Property 5: Ordering is an exact permutation with contiguous positions**
    - **Validates: Requirements 1.7**

  - [ ]* 5.7 Write example tests for the API error contract
    - Invalid `module` (`400`), non-existent/foreign `(module, task_id)` (`404`), duplicate add (`409`), malformed `PUT /api/line/order` payload (`400`).
    - _Requirements: 1.4, 1.6, 1.7_

- [x] 6. Add the page route and wire the module into the app
  - [x] 6.1 Implement `GET /linea` page route
    - Render `line.html` passing `nav_links=NAV_LINKS` (and `module_labels`), matching `calendar_page`.
    - _Requirements: 1.1, 1.8, NFR-01_

  - [x] 6.2 Register the blueprint and init hook in `app.py`
    - Add `from line_module import line_bp`, `app.register_blueprint(line_bp)`, and call `line_bp.init_db()` in `__main__` after the task modules' `init_db()`.
    - _Requirements: NFR-02, NFR-03_

  - [x] 6.3 Add the nav link in `nav.py`
    - Append `{"href": "/linea", "label": "Línea del día"}` to `NAV_LINKS`.
    - _Requirements: 1.8, NFR-01_

  - [ ]* 6.4 Write integration/regression tests for wiring
    - Assert every `/api/line*` endpoint returns `401` without a session and `GET /linea` redirects to `/login`; assert existing task endpoints still behave after `line_bp.init_db()`.
    - _Requirements: NFR-02, NFR-03_

- [x] 7. Checkpoint - backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Build the frontend
  - [x] 8.1 Create `templates/line.html`
    - Reuse the shared `<header>`/nav from `nav_links`, load `style.css` and `line.css`, set `window.APP_CONFIG = { apiBase: "/api/line" }`; include a timeline region and a picker region.
    - _Requirements: 1.8, NFR-01_

  - [x] 8.2 Create `static/line.css`
    - Style the vertical timeline (points) and picker within the existing palette/typography; no new colors.
    - _Requirements: 1.8, NFR-01_

  - [x] 8.3 Implement `static/line.js` timeline + picker rendering
    - Load the line via `GET /api/line` and render each item as a timeline point with title and nature label; populate the picker from `GET /api/line/available` grouped by nature; add selected tasks via `POST /api/line/items`.
    - _Requirements: 1.2, 1.4, 1.5, 1.8_

  - [x] 8.4 Implement `static/line.js` subtask disclosure and reorder/remove controls
    - Render a disclosure control per item; subtasks hidden on initial render (collapsed by default), toggling reveals/hides them; up/down controls call `PUT /api/line/order`; remove calls `DELETE /api/line/items/<id>`.
    - _Requirements: 1.6, 1.7, 1.9, 1.10_

  - [ ]* 8.5 Write example/DOM tests for timeline and subtask interaction
    - Timeline renders one point per line item (FR-08); an item with subtasks renders a disclosure control, subtasks are hidden initially (collapsed by default), toggling reveals then hides them (FR-09/FR-10).
    - _Requirements: 1.8, 1.9, 1.10_

- [x] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional (tests) and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each task references specific granular requirements (FR mapped to the requirements document's numbering) for traceability.
- Property tests (Properties 1–7) run a minimum of 100 iterations and are checked against the module's own functions/endpoints, reusing `tests/conftest.py` fixtures and `tests/strategies.py` generators — the feature logic is not reimplemented in tests.
- Each property test carries the comment tag `# Feature: LineTask, Property {n}: {text}`.
- Checkpoints ensure incremental validation at natural breaks (core logic, backend, final).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["2.1", "2.2", "2.3"] },
    { "id": 3, "tasks": ["2.4", "2.5", "2.6", "4.1", "4.2"] },
    { "id": 4, "tasks": ["4.3", "5.1", "5.2", "5.3", "6.1", "6.3"] },
    { "id": 5, "tasks": ["5.4", "5.5", "5.6", "5.7", "6.2"] },
    { "id": 6, "tasks": ["6.4", "8.1", "8.2", "8.3"] },
    { "id": 7, "tasks": ["8.4"] },
    { "id": 8, "tasks": ["8.5"] }
  ]
}
```
