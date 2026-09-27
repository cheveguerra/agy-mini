# CONTEXTO DEL SUBPROYECTO: SYSADMIN MINI (`agy-mini`)

## 1. Estado y Versión
* **Versión Actual:** v0.1.0-alpha
* **Foco Activo:** Creación del andamiaje base, módulos de herramientas nativas, motor de ejecución asíncrono y cliente Gemini.
* **Entorno de Ejecución:** Bare-metal en Host Proxmox VE (`pve` / `192.168.100.200`) bajo `/usr/local/bin/agy-mini`, accesible y sincronizado con `/mnt/data2/Software/agy-mini/` y `Z:\data2\Software\agy-mini\`.
* **Motor LLM:** Google Gemini API (`google-genai`), modelo por defecto `gemini-3.8-flash` con `thinking_budget` configurable.

---

## 2. Mapa de Componentes y Módulos
* **`agy_mini.py`:** Punto de entrada CLI ejecutable con arquitectura TUI Split-Screen de dos paneles (`prompt_toolkit.Application` + `HSplit`): Panel superior de conversación/razonamiento/tools con scroll dinámico tanto por teclado (PgUp/PgDn/Home/End) como por rueda del ratón (`MouseScrollableTextControl` + `mouse_support=True`) y Panel inferior de entrada editable multilínea con encolamiento asíncrono (`queue.Queue`) y Safety Gate interactivo integrado.
* **`config.yaml`:** Archivo declarativo de ajustes (modelos, timeouts síncronos, rutas de búsqueda de `AGENTS.md`, exclusión de filesystem y servidores MCP).
* **`core/agent.py`:** Orquestador principal del ciclo conversacional. Maneja el envío de mensajes, recepción de Function Calls, invocación determinista de tools y streaming de respuestas formateadas en Markdown.
* **`core/context.py`:** Módulo de precarga cognitiva. Localiza y carga dinámicamente el archivo maestro `AGENTS.md` y lo inyecta en la cúspide del *System Instruction* dentro de la etiqueta `<user_rules>` con precedencia absoluta sobre cualquier otra instrucción (idéntico a Antigravity). NO quema en duro `CONTEXTO.md` ni `INFRAESTRUCTURA.md`, sino que delega en las reglas de `AGENTS.md` para que el modelo los lea dinámicamente con herramientas nativas.
* **`core/commands.py`:** Manejador de metacomandos interactivos en consola (`/model`, `/effort`, `/clear`, `/tokens`, `/guardar`, `/help`, `/exit`).
* **`core/usage.py`:** Gestor de telemetría y contabilidad persistente de tokens (`TokenTracker`) sobre SQLite local (`~/.agy_mini_usage.db`) en modo TRUNCATE (cero WAL) con cálculo de costos en tiempo real.
* **`tools/fs.py`:** Herramientas nativas de inspección del sistema de archivos con guardas duras:
  - `list_dir`: Exploración de estrictamente 1 nivel con `os.scandir()`.
  - `read_file`: Lectura paginada (máx 250 líneas) con numeración de líneas.
  - `write_file` / `replace_file_content`: Modificaciones exactas sin inflar tokens.
  - `search_files`: Búsqueda acotada de nombres por glob con lista negra obligatoria (`/mnt/data1`, `/mnt/parity`, `node_modules`, `.git`).
  - `grep_text`: Búsqueda de patrones de texto y código DENTRO de archivos con numeración de líneas y límites anti-atasco.
* **`tools/terminal.py`:** Ejecutor de shell con timeout síncrono de 15 segundos y `Safety Gate` interactivo `[s/N]` para comandos mutativos o de riesgo.
* **`tools/async_tasks.py`:** Motor de desacople de tareas pesadas o que superan el timeout hacia `systemd-run` o procesos daemon en background con logging a `/var/log/agy_tasks/` y notificación opcional vía webhook HTTP (`:9020`).
* **`tools/web.py`:** Herramientas de conectividad web:
  - `search_web`: Búsqueda web pública ligera (DuckDuckGo) sin APIs de pago.
  - `read_url_content`: Extractor de texto limpio y Markdown a partir de páginas web o manuales técnicos.
* **`tools/mcp_client.py`:** Cliente ligero JSON-RPC 2.0 stdio para conectar servidores MCP locales (específicamente `sqlite-memory`).

---

## 3. Persistencia y Almacenamiento
* **Directrices Maestras (`AGENTS.md`):** Buscado prioritariamente en `./AGENTS.md`, `/mnt/data1/agy_shared/AGENTS.md`, `/root/AGENTS.md` o `Z:/data1/agy_shared/AGENTS.md`.
* **Configuración Local:** `config.yaml` en la raíz del proyecto.
* **Memoria Episódica e Híbrida:** Servidor MCP `sqlite-memory` (`/mnt/data1/agy_shared/tools/sqlite_memory_mcp.sh`) operando sobre bases SQLite con `PRAGMA journal_mode = TRUNCATE`.
* **Logs de Tareas Desacopladas:** `/var/log/agy_tasks/<task_id>.log` en Proxmox VE.

---

## 4. Reglas Críticas e Invariantes
1. **Jerarquía Absoluta de `AGENTS.md`:** Todo lo contenido en `<user_rules>` tiene fuerza de ley inmutable. `agy-mini` debe leerlo al arrancar y regir su comportamiento por él.
2. **Cero Hardcoding de Contextos Efímeros:** `CONTEXTO.md` e `INFRAESTRUCTURA.md` se consultan de manera viva y dinámica con `read_file` según lo estipulen las directrices de `AGENTS.md`, ahorrando miles de tokens fijos por turno.
3. **Invariante de Timeouts Síncronos:** Ningún comando de terminal puede ejecutarse de forma síncrona por más de 15 segundos. Si supera ese límite, debe ser terminado de inmediato (`process.kill()`) o transferido a tarea desacoplada.
4. **Prohibición de Shell para Exploración:** El modelo jamás debe invocar `find`, `ls` ni `grep` en la shell para inspeccionar archivos. Debe usar estrictamente las herramientas nativas de `tools/fs.py`.
5. **Safety Gate Obligatorio:** Cualquier comando de consola con `rm`, `reboot`, `systemctl restart`, `pct stop`, `chmod`, `chown` o similar DEBE requerir confirmación interactiva `[s/N]` en terminal antes de ser despachado.
6. **Respeto a Discos Masivos:** Queda estrictamente prohibida la indexación o escaneo recursivo en `/mnt/data1` o `/mnt/parity`.
7. **Permisos y Modos SQLite:** Toda base de datos generada o modificada debe tener permisos `chmod 666` (para el UID 100000 de LXC 100) y operar en modo `TRUNCATE`.

---

## 5. Tareas Pendientes
- [x] Elaborar especificación técnica (`SYSADMIN_MINI_SPEC.md`).
- [x] Crear estructura de carpetas y `CONTEXT.md` del subproyecto.
- [x] Implementar `config.yaml` y `requirements.txt`.
- [x] Implementar herramientas nativas de filesystem en `tools/fs.py`.
- [x] Implementar ejecutor de comandos y Safety Gate en `tools/terminal.py`.
- [x] Implementar motor de desacople en `tools/async_tasks.py`.
- [x] Implementar conector MCP en `tools/mcp_client.py`.
- [x] Implementar inyección dinámica pura de `AGENTS.md` en `core/context.py` y metacomandos en `core/commands.py`.
- [x] Implementar bucle conversacional en `core/agent.py` y punto de entrada `agy_mini.py`.
- [x] Validación funcional en Proxmox VE (SDK `google-genai` oficial, tool calling nativo y symlink `/usr/local/bin/agy-mini` activos).
- [x] Implementación de telemetría de tokens y costos en SQLite (`core/usage.py`, comando `/tokens`, modo TRUNCATE anti-WAL).
- [x] Arquitectura multihilo y encolamiento asíncrono de mensajes en `agy-mini` (TUI Split-Screen de 2 paneles con `prompt_toolkit.Application`, `HSplit`, `queue.Queue` y worker thread para escribir/encolar mensajes continuamente sin congelar el teclado).
- [x] Soporte nativo para scroll con la rueda del ratón (`mouse_support=True`, captura de `SCROLL_UP` / `SCROLL_DOWN` vinculados a `ChatLog.scroll_up/down` en el panel superior).
- [x] Corrección de viewport y cursor virtual en TUI: Integración de `get_cursor_position` en `MouseScrollableTextControl` y `ChatLog` para scroll real de rueda/teclado y auto-scroll continuo al final.
- [x] Conversión y cálculo de costos en tiempo real en Pesos Mexicanos (MXN): Integración en `core/usage.py` y comando `/tokens` con consulta en vivo a APIs cambiarias públicas y caché SQLite con TTL de 6 horas.
- [x] Blindaje de viewport anti-IndexError en TUI: Sobrecarga de `create_content` en `MouseScrollableTextControl` con clamp de `cursor_position.y` y wrapper seguro en `get_line` para erradicar crashes del bucle de eventos asyncio durante linewrapping.
- [x] Optimización masiva de tokens: Poda de FunctionCall/FunctionResponse intermedios en `core/agent.py` manteniendo alternancia limpia `user -> model`.
- [x] Filtrado programático de reglas ajenas a Sysadmin en `core/context.py` (ahorro de ~3,000 tokens por petición sin duplicar archivos).
- [x] Compactación de contexto: Metacomando `/compact` y auto-compresión por umbral al superar 60,000 tokens de entrada.
- [x] Flags CLI de arranque en `agy_mini.py` (`--effort`, `--no-think`, `--model`) con soporte de thinking budget 0.
- [x] Publicación y versionado en repositorio GitHub (`github.com/cheveguerra/agy-mini`).
