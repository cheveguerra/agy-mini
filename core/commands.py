"""
Manejador de Metacomandos al Vuelo (/model, /effort, /clear, /guardar, /tasks).
Permite ajustar parámetros de ejecución sin reiniciar la sesión ni perder el contexto.
"""

from typing import Dict, Any, Tuple
import os
import subprocess
from core.usage import TokenTracker
from tools.terminal import is_command_sensitive
from tools.fs import list_dir

def handle_slash_command(cmd_text: str, agent_state: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Evalúa si la entrada del usuario es un comando de control.
    Devuelve (es_comando, mensaje_resultado).
    """
    parts = cmd_text.strip().split()
    if not parts or not parts[0].startswith("/"):
        return False, ""

    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in ["/help", "/ayuda"]:
        msg = """[bold cyan]Comandos de Control de Sysadmin Mini:[/bold cyan]
  [green]/model <identificador>[/green]   - Cambia el modelo (ej. /model gemini-3.8-flash, /model gemini-2.5-pro)
  [green]/effort <none|low|med|high>[/green] - Ajusta el nivel de razonamiento / thinking
  [green]/compact[/green]                 - Resume y compacta el historial acumulado
  [green]/test[/green]                    - Ejecuta auto-diagnóstico de integridad de agy-mini
  [green]/clear[/green]                   - Limpia el historial de la conversación actual
  [green]/tokens[/green]                  - Muestra el consumo acumulado de tokens y costo estimado
  [green]/guardar[/green]                 - Guarda CONTEXTO.md y consolida AutoDream en SQLite
  [green]/status[/green]                  - Muestra modelo activo, esfuerzo y configuración
  [green]/tasks[/green]                   - Lista las tareas desacopladas activas en segundo plano
  [green]/exit[/green] o [green]/salir[/green]           - Finaliza la sesión
"""
        return True, msg

    if cmd == "/model":
        if not arg:
            return True, f"[yellow]Modelo actual:[/yellow] {agent_state.get('model')}"
        agent_state["model"] = arg
        agent_state["reinit_chat"] = True
        return True, f"[bold green]✔ Modelo cambiado a:[/bold green] {arg}"

    if cmd == "/effort":
        if arg.lower() in ["none", "low", "medium", "high"]:
            agent_state["effort"] = arg.lower()
            agent_state["reinit_chat"] = True
            return True, f"[bold green]✔ Thinking effort ajustado a:[/bold green] {arg.lower()}"
        return True, "[red]Nivel de esfuerzo inválido. Usa: none, low, medium o high.[/red]"

    if cmd in ["/compact", "/compactar"]:
        agent_state["trigger_compact"] = True
        return True, "[bold cyan]Solicitando compactación de contexto...[/bold cyan]"

    if cmd == "/clear":
        agent_state["history"] = []
        agent_state["reinit_chat"] = True
        return True, "[bold yellow]Historial conversacional limpiado.[/bold yellow]"

    if cmd == "/status":
        msg = f"""[bold cyan]Estado del Agente:[/bold cyan]
  • Modelo: [green]{agent_state.get('model')}[/green]
  • Thinking Effort: [green]{agent_state.get('effort')}[/green]
  • Turnos en Historial: {len(agent_state.get('history', []))}
"""
        return True, msg

    if cmd in ["/tokens", "/uso", "/cost", "/costo"]:
        tracker = TokenTracker()
        session_id = agent_state.get("session_id", "")
        s_summary = tracker.get_session_summary(session_id) if session_id else {}
        t_summary = tracker.get_today_summary()
        key_breakdown = tracker.get_today_breakdown_by_key()
        rate = s_summary.get("exchange_rate") or t_summary.get("exchange_rate") or 18.0

        breakdown_text = ""
        if key_breakdown:
            breakdown_text = "\n[bold magenta]Desglose de Hoy por Llave API:[/bold magenta]\n"
            for kb in key_breakdown:
                breakdown_text += f"  • Llave [bold]{kb['key_suffix']}[/bold]: {kb['total_tokens']:,} tokens ({kb['calls']} calls) ~${kb['cost_mxn']:.4f} MXN [dim](${kb['cost_usd']:.4f} USD)[/dim]\n"

        msg = f"""[bold cyan]📊 Telemetría de Tokens de Sysadmin Mini[/bold cyan] [dim](Tasa: ${rate:.2f} MXN/USD)[/dim]:

[bold green]Sesión Actual:[/bold green]
  • Llamadas API: {s_summary.get('calls', 0)}
  • Entrada: [dim]{s_summary.get('prompt_tokens', 0):,}[/dim] tokens
  • Salida: [dim]{s_summary.get('candidates_tokens', 0):,}[/dim] tokens
  • Pensamiento: [dim]{s_summary.get('thinking_tokens', 0):,}[/dim] tokens
  • Total Sesión: [bold]{s_summary.get('total_tokens', 0):,}[/bold] tokens (~${s_summary.get('estimated_cost_mxn', 0.0):.4f} MXN / [dim]${s_summary.get('estimated_cost_usd', 0.0):.4f} USD[/dim])

[bold yellow]Total Acumulado Hoy (Todas las sesiones):[/bold yellow]
  • Llamadas API: {t_summary.get('calls', 0)}
  • Entrada: [dim]{t_summary.get('prompt_tokens', 0):,}[/dim] tokens
  • Salida: [dim]{t_summary.get('candidates_tokens', 0):,}[/dim] tokens
  • Pensamiento: [dim]{t_summary.get('thinking_tokens', 0):,}[/dim] tokens
  • Total Hoy: [bold]{t_summary.get('total_tokens', 0):,}[/bold] tokens (~${t_summary.get('estimated_cost_mxn', 0.0):.4f} MXN / [dim]${t_summary.get('estimated_cost_usd', 0.0):.4f} USD[/dim])
{breakdown_text}"""
        return True, msg

    if cmd in ["/test", "/diagnostico"]:
        # 1. Test Safety Gate
        sg_ok = is_command_sensitive("rm -rf /tmp/test") and not is_command_sensitive("uptime")
        # 2. Test Tools Nativas
        fs_res = list_dir(".")
        fs_ok = isinstance(fs_res, dict) and "items" in fs_res
        # 3. Test Telemetría SQLite
        try:
            tracker = TokenTracker()
            rate = tracker.get_usd_to_mxn_rate()
            db_ok = rate > 0
        except Exception:
            db_ok = False
            rate = 18.0

        status_msg = f"""[bold cyan]🧪 Auto-Diagnóstico de Salud Operativa (Sysadmin Mini):[/bold cyan]
  • [bold]{'✔' if sg_ok else '❌'}[/bold] Safety Gate (Filtro de riesgo): {'[green]OPERATIVO[/green]' if sg_ok else '[red]FALLA[/red]'}
  • [bold]{'✔' if fs_ok else '❌'}[/bold] Herramientas Nativas Filesystem: {'[green]OPERATIVO[/green]' if fs_ok else '[red]FALLA[/red]'}
  • [bold]{'✔' if db_ok else '❌'}[/bold] Telemetría SQLite y Divisas MXN (${rate:.2f}): {'[green]OPERATIVO[/green]' if db_ok else '[red]FALLA[/red]'}
  • [bold]✔[/bold] Turnos Activos: {len(agent_state.get('history', []))} | Modelo: {agent_state.get('model')}
"""
        return True, status_msg

    if cmd == "/guardar":
        save_scripts = [
            "/usr/local/bin/save_session.py",
            "/mnt/data1/agy_shared/tools/save_session.py",
            os.path.expanduser("~/.local/bin/save_session.py")
        ]
        for script in save_scripts:
            if os.path.exists(script):
                try:
                    subprocess.run(["python3", script], check=True, timeout=10)
                    return True, f"[bold green]✔ Sesión guardada y replicada exitosamente con {script}[/bold green]"
                except Exception as e:
                    return True, f"[red]Error al ejecutar {script}: {e}[/red]"
        return True, "[red]save_session.py no encontrado en ninguna ruta conocida.[/red]"

    return False, ""
