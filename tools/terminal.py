"""
Módulo de Ejecución de Comandos con Safety Gate y Timeouts Asíncronos.
Garantiza que la terminal jamás se congele y protege el sistema de operaciones destructivas.
"""

import subprocess
import shlex
import os
import signal
from typing import Dict, Any, List

SENSITIVE_KEYWORDS = [
    "rm ",
    "rmdir",
    "reboot",
    "poweroff",
    "shutdown",
    "systemctl stop",
    "systemctl restart",
    "pct stop",
    "pct destroy",
    "docker stop",
    "docker rm",
    "docker compose down",
    "docker-compose down",
    "chmod",
    "chown",
    "mkfs",
    "fdisk",
    "dd "
]

SAFE_PREFIXES = [
    "pct status",
    "pct list",
    "docker ps",
    "uptime",
    "free",
    "df -h",
    "cat ",
    "head ",
    "tail ",
    "journalctl -n",
    "systemctl status",
    "git status",
    "git log",
    "git diff"
]

SAFETY_GATE_HANDLER = None

def set_safety_gate_handler(handler):
    """Permite inyectar un gestor de confirmación interactivo (ej. para TUI multihilo)."""
    global SAFETY_GATE_HANDLER
    SAFETY_GATE_HANDLER = handler

def is_command_sensitive(command: str) -> bool:
    """Evalúa si un comando coincide con patrones críticos que requieren confirmación."""
    cmd_clean = command.strip()
    for safe in SAFE_PREFIXES:
        if cmd_clean.startswith(safe):
            return False
    return any(kw in cmd_clean for kw in SENSITIVE_KEYWORDS)

def check_safety_gate(command: str) -> bool:
    """
    Evalúa si un comando requiere confirmación humana obligatoria.
    Devuelve True si está autorizado para correr, False si fue rechazado.
    """
    if not is_command_sensitive(command):
        return True

    # Si hay un handler inyectado (por ejemplo desde la TUI), delegar en él
    if SAFETY_GATE_HANDLER is not None:
        return SAFETY_GATE_HANDLER(command)

    # Interceptar con prompt interactivo en consola estándar (fallback)
    print("\n\033[1;31m" + "━" * 60 + "\033[0m")
    print("\033[1;33m⚠️  [SAFETY GATE] Gemini solicita ejecutar un comando sensible:\033[0m")
    print(f"   \033[1;37m{command}\033[0m")
    print("\033[1;31m" + "━" * 60 + "\033[0m")

    try:
        choice = input("¿Autorizar ejecución en el sistema? [s/N]: ").strip().lower()
        return choice in ["s", "si", "y", "yes"]
    except (KeyboardInterrupt, EOFError):
        return False


def run_command(command: str, timeout: int = 15, bypass_safety: bool = False) -> Dict[str, Any]:
    """
    Ejecuta un comando en Bash con timeout estricto y Safety Gate.
    Si el comando supera el timeout (15s por defecto), se termina automáticamente con kill().
    """
    if not bypass_safety and not check_safety_gate(command):
        return {
            "error": "OPERACIÓN CANCELADA: El usuario rechazó la ejecución del comando en el Safety Gate.",
            "command": command
        }

    try:
        # Ejecutar a través de bash -c para admitir pipes y redirecciones acotadas
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            executable="/bin/bash" if os.path.exists("/bin/bash") else None,
            preexec_fn=os.setsid if hasattr(os, "setsid") else None
        )

        try:
            stdout, stderr = process.communicate(timeout=timeout)
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            # Matar el árbol completo del proceso hijo
            if hasattr(os, "killpg") and hasattr(os, "getpgid"):
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except Exception:
                    process.kill()
            else:
                process.kill()

            stdout, stderr = process.communicate()
            return {
                "error": f"TIMEOUT DE SEGURIDAD: El comando superó el límite de {timeout} segundos y fue terminado inmediatamente.",
                "command": command,
                "suggestion": "Si se trata de un proceso de larga duración (ej. backup, sync, build), ejecútalo como tarea desacoplada usando launch_detached_task()."
            }

        # Truncar salida si supera 80 líneas para no desbordar tokens
        stdout_lines = stdout.splitlines()
        total_lines = len(stdout_lines)
        if total_lines > 80:
            truncated_stdout = "\n".join(stdout_lines[:40]) + f"\n\n[... {total_lines - 80} líneas omitidas por brevedad ...]\n\n" + "\n".join(stdout_lines[-40:])
        else:
            truncated_stdout = stdout

        return {
            "command": command,
            "exit_code": exit_code,
            "stdout": truncated_stdout,
            "stderr": stderr.strip(),
            "success": exit_code == 0
        }

    except Exception as e:
        return {"error": f"Fallo al ejecutar comando: {str(e)}", "command": command}
