# SYSADMIN MINI (`agy-mini`) 🤖🖥️

> Agente CLI autónomo de administración de sistemas y desarrollo bare-metal para Proxmox VE impulsado por la API de Google Gemini.

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Proxmox%20VE%20%7C%20Debian-orange.svg)]()

---

## 📋 Resumen

`agy-mini` es un asistente de terminal inteligente diseñado para operar directamente en el hipervisor (bare-metal) sin depender de frameworks pesados (sin LangChain ni LlamaIndex). Todo el sistema cabe en **~2,000 líneas de código modular**, consumiendo únicamente entre 50 y 80 MB de RAM.

Incorpora una interfaz gráfica de consola (**TUI Split-Screen multihilo**) que permite escribir y ejecutar comandos continuamente sin congelar la entrada mientras el modelo genera respuestas o despacha herramientas.

---

## ✨ Características Principales

* 🖥️ **TUI Split-Screen Multihilo (`prompt_toolkit`):**
  * Panel superior de conversación/razonamiento con scroll fluido mediante **rueda del ratón** y teclado (`PgUp`/`PgDn`/`Home`/`End`).
  * Bypass nativo de selección y copiado al portapapeles mediante `Shift + Clic y arrastre`.
  * Blindaje de viewport anti-`IndexError` ante desfases de salto de línea (*linewrapping*) en `asyncio`.
* 🛡️ **Safety Gate Interactivo:** Requiere confirmación obligatoria en consola `[s/N]` antes de ejecutar comandos potencialmente destructivos o mutativos (`rm`, `reboot`, `systemctl stop`, `pct destroy`, etc.).
* ⏱️ **Timeouts Duros Anti-Bloqueo:** Límite estricto de 15 segundos para comandos síncronos; soporte de desacople para procesos largos (`tools/async_tasks.py`).
* 💵 **Telemetría y Costos en Pesos Mexicanos (MXN):** Contabilidad persistente de tokens en SQLite local (modo `TRUNCATE` anti-WAL) con cotización USD/MXN en tiempo real mediante APIs cambiarias públicas y caché de 6 horas.
* 🛠️ **Suite de Herramientas Nativas:**
  * Filesystem seguro: `list_dir` (estricto 1 nivel), `read_file` (paginado), `write_file`, `replace_file_content`, `search_files`, `grep_text`.
  * Conector MCP: Soporte para servidores de memoria semántica (`tools/mcp_client.py`).
  * Desacople en segundo plano: Lanzamiento y auditoría de tareas con logging en `/var/log/agy_tasks/` y webhooks.

---

## 📂 Estructura del Proyecto

```text
agy-mini/
├── agy_mini.py             # Entrypoint CLI y TUI Split-Screen multihilo
├── config.yaml             # Configuración declarativa (modelos, exclusiones, timeouts)
├── CONTEXT.md              # Contexto de desarrollo del subproyecto
├── requirements.txt        # Dependencias de producción
├── core/
│   ├── agent.py            # Orquestador conversacional y ciclo de tool calling
│   ├── commands.py         # Metacomandos interactivos (/tokens, /model, /clear, etc.)
│   ├── context.py          # Inyector cognitivo de reglas maestras (<user_rules>)
│   └── usage.py            # Tracker de tokens y conversión a Pesos Mexicanos (MXN)
└── tools/
    ├── async_tasks.py      # Tareas desacopladas en segundo plano
    ├── fs.py               # Inspección y manipulación segura de archivos
    ├── mcp_client.py       # Cliente JSON-RPC stdio para servidores MCP
    ├── mcp_manager.py      # Gestor de procesos MCP locales
    ├── terminal.py         # Ejecución shell protegida con Safety Gate
    └── web.py              # Búsqueda ligera y extracción web
```

---

## 🚀 Instalación y Puesta en Marcha

### 1. Clonar el Repositorio
```bash
git clone https://github.com/cheveguerra/agy-mini.git
cd agy-mini
```

### 2. Instalar Dependencias
```bash
pip install -r requirements.txt
```

### 3. Configurar la API Key de Gemini
```bash
export GEMINI_API_KEY="tu_api_key_de_google_ai_studio"
```

### 4. Ejecutar
```bash
python3 agy_mini.py
```
*(Opcional: Crear enlace simbólico para acceso global)*
```bash
ln -sf $(pwd)/agy_mini.py /usr/local/bin/agy-mini
chmod +x /usr/local/bin/agy-mini
agy-mini
```

---

## ⌨️ Metacomandos en Terminal

| Comando | Descripción |
| :--- | :--- |
| `/tokens` | Despliega el resumen de consumo de la sesión y acumulado histórico en **Pesos Mexicanos (MXN)** y USD. |
| `/model <nombre>` | Cambia el modelo de Gemini en caliente (ej: `/model gemini-2.5-pro`). |
| `/effort <low|medium|high>` | Ajusta el presupuesto de razonamiento (*thinking*) del modelo. |
| `/clear` | Limpia la pantalla y reinicia el contexto de la sesión activa. |
| `/guardar` | Dispara el guardado y sincronización persistente de la sesión. |
| `/exit` o `/quit` | Cierra la sesión de `agy-mini`. |

---

## 📄 Licencia

Este proyecto está bajo la Licencia MIT.
