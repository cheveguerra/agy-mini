"""
Módulo de Tareas Desacopladas (Background Daemons y Notificaciones).
Permite lanzar operaciones de larga duración (vzdump, sync, scrubs) sin bloquear
la sesión de consola, con logs persistentes y notificación por webhook HTTP opcional.
"""

import os
import time
import uuid
import json
import subprocess
import requests
from typing import Dict, Any

TASK_LOG_DIR = "/var/log/agy_tasks"
WEBHOOK_URL = "http://192.168.100.50:9020/v1/messages"

def ensure_log_dir() -> str:
    """Asegura que el directorio de logs exista (con fallback a /tmp si no hay permisos)."""
    target_dir = TASK_LOG_DIR
    try:
        os.makedirs(target_dir, exist_ok=True)
    except PermissionError:
        target_dir = "/tmp/agy_tasks"
        os.makedirs(target_dir, exist_ok=True)
    return target_dir


def launch_detached_task(command: str, description: str = "", notify_whatsapp: bool = True) -> Dict[str, Any]:
    """
    Lanza un proceso desacoplado en segundo plano.
    Redirige la salida a un archivo de log y programa notificación HTTP opcional al terminar.
    """
    log_dir = ensure_log_dir()
    task_id = f"task_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    log_file = os.path.join(log_dir, f"{task_id}.log")
    meta_file = os.path.join(log_dir, f"{task_id}.json")

    # Script wrapper para capturar fin de tarea y disparar webhook
    wrapper_script = os.path.join(log_dir, f"{task_id}.sh")
    
    notify_block = ""
    if notify_whatsapp:
        notify_block = f"""
EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
    MSG="✅ *Tarea Finalizada:* {description or command}\\nID: {task_id}\\nEstado: Exitoso"
else
    MSG="❌ *Tarea Fallida:* {description or command}\\nID: {task_id}\\nExit code: $EXIT_CODE"
fi
curl -s -X POST -H "Content-Type: application/json" -d "{{\\"recipient\\":\\"homelab\\",\\"text\\":\\"$MSG\\"}}" {WEBHOOK_URL} >/dev/null 2>&1 || true
"""

    script_content = f"""#!/bin/bash
exec > "{log_file}" 2>&1
echo "=== INICIO DE TAREA: {task_id} ==="
echo "Comando: {command}"
echo "Fecha: $(date -Iseconds)"
echo "----------------------------------------"

{command}

{notify_block}
echo "----------------------------------------"
echo "=== FIN DE TAREA (Exit code: $EXIT_CODE) ==="
"""

    with open(wrapper_script, "w", encoding="utf-8") as f:
        f.write(script_content)
    os.chmod(wrapper_script, 0o755)

    try:
        # Lanzar desacoplado con nohup
        process = subprocess.Popen(
            [wrapper_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True
        )

        metadata = {
            "task_id": task_id,
            "pid": process.pid,
            "command": command,
            "description": description,
            "start_time": time.time(),
            "log_file": log_file,
            "status": "running"
        }

        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        return {
            "status": "launched",
            "task_id": task_id,
            "pid": process.pid,
            "log_file": log_file,
            "message": f"Tarea desacoplada iniciada con PID {process.pid}. La consola queda libre de inmediato."
        }

    except Exception as e:
        return {"error": f"Fallo al desacoplar tarea: {str(e)}"}


def check_task_status(task_id: str) -> Dict[str, Any]:
    """Consulta el estado actual de una tarea desacoplada y las últimas líneas de su log."""
    log_dir = ensure_log_dir()
    meta_file = os.path.join(log_dir, f"{task_id}.json")
    log_file = os.path.join(log_dir, f"{task_id}.log")

    if not os.path.exists(meta_file):
        return {"error": f"No se encontró la tarea con ID: {task_id}"}

    with open(meta_file, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    pid = metadata.get("pid")
    is_running = False
    if pid:
        try:
            # Comprobar si el proceso sigue vivo
            os.kill(pid, 0)
            is_running = True
        except OSError:
            is_running = False

    last_logs = ""
    if os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                last_logs = "".join(lines[-20:])
        except Exception:
            last_logs = "No se pudo leer el log."

    return {
        "task_id": task_id,
        "pid": pid,
        "is_running": is_running,
        "status": "running" if is_running else "finished",
        "log_tail": last_logs
    }
