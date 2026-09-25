# Task-Manager

Gestor de tareas y calendario multiusuario en Flask + SQLite. Además de la
interfaz web basada en sesión, expone una **API externa de solo lectura**
(`/api/v1`) pensada para consumo máquina a máquina, autenticada con un token
Bearer.

## API externa (`/api/v1`)

API de solo lectura para que una aplicación externa recupere las tareas y los
eventos de calendario de un usuario. Vive bajo su propio prefijo y su propio
mecanismo de autenticación; los endpoints web basados en sesión no cambian.

### ¿Cómo sabe la API de qué usuario son los datos?

Por el **token**. Cada petición a `/api/v1/...` debe incluir un token Bearer, y
ese token está asociado en la base de datos a un único usuario. El servidor
resuelve el dueño del token y filtra todos los resultados por él, así que una
app externa solo puede ver los datos del usuario propietario del token que usa.
La app externa nunca indica un id de usuario; el servidor lo deduce del token.

### 1. Emitir un token (requiere sesión)

El token se genera desde una sesión web activa (login normal con usuario y
contraseña). No forma parte de la API `/api/v1`.

```
POST /api/token
```

Respuesta `201`:

```json
{ "token": "<token-en-claro>" }
```

Notas importantes:

- El valor en claro se muestra **una sola vez**. En la base solo se guarda su
  hash SHA-256, por lo que no es recuperable después. Guárdalo al emitirlo.
- Hay **un token activo por usuario**. Volver a llamar a `POST /api/token`
  **rota** el token: genera uno nuevo e invalida el anterior.
- Si falla la generación/almacenamiento responde `500` y el token previo queda
  intacto.

### 2. Revocar el token (requiere sesión)

```
DELETE /api/token
```

- `200` `{ "message": "Token revocado" }` si había un token activo.
- `404` `{ "error": "No hay un token activo para revocar" }` si no había ninguno.

### 3. Autenticación en las peticiones

La app externa envía el token en cada petición mediante la cabecera:

```
Authorization: Bearer <token-en-claro>
```

Si la cabecera falta, no empieza por `Bearer `, el token está vacío o no
coincide con ninguno registrado, la respuesta es `401`:

```json
{ "error": "Token de API inválido o ausente" }
```

### Endpoints

#### `GET /api/v1/tasks`

Devuelve las tareas del usuario dueño del token, agregando los tres módulos
(`academic`, `work`, `personal`). La lista se ordena por `created_at` ascendente
y, ante empate, por `id` ascendente.

Parámetro de consulta opcional:

- `?module=academic|work|personal` → solo ese módulo.
- Ausente → los tres módulos.
- Valor no válido → `400` `{ "error": "Módulo no válido: ..." }` sin devolver tareas.

Ejemplo:

```bash
curl -H "Authorization: Bearer $TOKEN" \
     "http://localhost:5000/api/v1/tasks?module=work"
```

Respuesta `200` (lista raíz):

```json
[
  {
    "id": 1,
    "title": "Preparar informe",
    "description": null,
    "due_date": "2026-03-10",
    "complexity": 3,
    "subject": "IEEE",
    "created_at": "2026-02-20 09:00:00",
    "module": "work",
    "subtasks": [
      { "id": 5, "title": "Recolectar datos", "completed": true },
      { "id": 6, "title": "Redactar", "completed": false }
    ]
  }
]
```

Las claves de cada tarea siempre están presentes; los campos opcionales sin
valor se emiten como `null`, y `subtasks` es `[]` si no hay. `completed` es un
booleano. Si no hay coincidencias, la respuesta es una lista vacía `[]`.

#### `GET /api/v1/events`

Devuelve los eventos de calendario del usuario dueño del token, ordenados por
`event_date` ascendente y, ante empate, por `id` ascendente.

Parámetro de consulta opcional:

- `?month=YYYY-MM` (mes `01`–`12`) → solo los eventos de ese mes.
- Ausente → todos los eventos del usuario.
- Formato no válido → `400` `{ "error": "El parámetro month debe tener formato YYYY-MM" }`
  sin devolver eventos.

Ejemplo:

```bash
curl -H "Authorization: Bearer $TOKEN" \
     "http://localhost:5000/api/v1/events?month=2026-02"
```

Respuesta `200` (lista raíz):

```json
[
  {
    "id": 1,
    "title": "Reunión de equipo",
    "description": null,
    "event_date": "2026-02-20",
    "module": "work",
    "created_at": "2026-02-01 12:00:00"
  }
]
```

### Errores

Todas las respuestas de esta API llevan `Content-Type: application/json`. Los
errores comparten el sobre `{ "error": "..." }`:

| Código | Cuándo |
| ------ | ------ |
| `400`  | Parámetro `module` o `month` no válido |
| `401`  | Token ausente o inválido |
| `404`  | Ruta o recurso inexistente bajo `/api/v1` |
| `500`  | Error interno del servidor |

### Ejemplo de flujo completo

```bash
# 1. Emitir el token desde una sesión web (cookie de sesión en $COOKIE)
TOKEN=$(curl -s -X POST -b "$COOKIE" http://localhost:5000/api/token | jq -r .token)

# 2. Consumir la API con el token
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/v1/tasks
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/v1/events

# 3. Revocar cuando ya no se necesite
curl -X DELETE -b "$COOKIE" http://localhost:5000/api/token
```
