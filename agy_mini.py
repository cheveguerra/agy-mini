#!/usr/bin/env python3
"""
Sysadmin Mini (`agy-mini`) - CLI Autónoma de Administración y Desarrollo
Diseñado específicamente para el Homelab de FamGuerra en Proxmox VE.
Arquitectura TUI Split-Screen Multihilo con Encolamiento Asíncrono.
"""

import os
import sys
import io
import yaml
import queue
import threading
import shutil
import argparse
from typing import Any, List

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl, BufferControl, UIContent
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.widgets import Frame
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.mouse_events import MouseEventType, MouseEvent
from prompt_toolkit.formatted_text import ANSI, to_formatted_text
from prompt_toolkit.data_structures import Point

# Asegurar path de módulos internos
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.agent import AgyMiniAgent
from core.commands import handle_slash_command
from tools.terminal import set_safety_gate_handler

def load_config() -> dict:
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            pass
    return {}


class ChatLog:
    """Gestiona el buffer de líneas formateadas en ANSI del panel superior."""
    def __init__(self, max_lines: int = 5000):
        self.lines: List[str] = []
        self.max_lines = max_lines
        self.auto_scroll: bool = True
        self.cursor_line: int = 0
        self._lock = threading.Lock()

    def get_width(self) -> int:
        cols, _ = shutil.get_terminal_size(fallback=(100, 30))
        # Descontar márgenes de borde del Frame (aprox 4 caracteres)
        return max(40, cols - 4)

    def render_to_ansi(self, content: Any) -> str:
        w = self.get_width()
        s = io.StringIO()
        c = Console(file=s, force_terminal=True, color_system="standard", width=w)
        if isinstance(content, str):
            c.print(content)
        else:
            c.print(content)
        return s.getvalue().rstrip("\n")

    def append(self, content: Any):
        ansi_text = self.render_to_ansi(content)
        with self._lock:
            for line in ansi_text.splitlines():
                self.lines.append(line)
            if len(self.lines) > self.max_lines:
                self.lines = self.lines[-self.max_lines:]
            if self.auto_scroll:
                self.cursor_line = max(0, len(self.lines) - 1)

    def get_formatted_text(self):
        with self._lock:
            full_str = "\n".join(self.lines)
        return to_formatted_text(ANSI(full_str))

    def get_cursor_position(self) -> Point:
        with self._lock:
            if not self.lines:
                return Point(x=0, y=0)
            if self.auto_scroll:
                self.cursor_line = max(0, len(self.lines) - 1)
            else:
                self.cursor_line = max(0, min(self.cursor_line, len(self.lines) - 1))
            return Point(x=0, y=self.cursor_line)

    def scroll_up(self, amount: int = 5):
        with self._lock:
            self.auto_scroll = False
            self.cursor_line = max(0, self.cursor_line - amount)

    def scroll_down(self, amount: int = 5):
        with self._lock:
            max_idx = max(0, len(self.lines) - 1)
            self.cursor_line = min(max_idx, self.cursor_line + amount)
            if self.cursor_line >= max_idx:
                self.auto_scroll = True

    def scroll_home(self):
        with self._lock:
            self.auto_scroll = False
            self.cursor_line = 0

    def scroll_end(self):
        with self._lock:
            self.auto_scroll = True
            self.cursor_line = max(0, len(self.lines) - 1)


class MouseScrollableTextControl(FormattedTextControl):
    """Control de texto que captura eventos de rueda y protege límites de cursor."""
    def __init__(self, text, get_cursor_position=None, on_scroll_up=None, on_scroll_down=None, **kwargs):
        super().__init__(text, get_cursor_position=get_cursor_position, **kwargs)
        self.on_scroll_up = on_scroll_up
        self.on_scroll_down = on_scroll_down

    def mouse_handler(self, mouse_event: MouseEvent):
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            if self.on_scroll_up:
                self.on_scroll_up()
            return None
        elif mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            if self.on_scroll_down:
                self.on_scroll_down()
            return None
        return super().mouse_handler(mouse_event)

    def create_content(self, width: int, height: int | None) -> UIContent:
        content = super().create_content(width, height)
        line_count = content.line_count
        cur_pos = content.cursor_position
        if cur_pos is not None:
            safe_y = max(0, min(cur_pos.y, line_count - 1)) if line_count > 0 else 0
            if safe_y != cur_pos.y:
                content.cursor_position = Point(x=cur_pos.x, y=safe_y)

        # Envolver get_line para blindar contra cualquier IndexError en _scroll_when_linewrapping
        orig_get_line = content.get_line
        def safe_get_line(i: int):
            try:
                if 0 <= i < line_count:
                    return orig_get_line(i)
                return []
            except Exception:
                return []
        content.get_line = safe_get_line
        return content


def main():
    parser = argparse.ArgumentParser(description="Sysadmin Mini CLI - Agente Bare-Metal para Proxmox VE")
    parser.add_argument("--model", "-m", type=str, help="Modelo Gemini a usar (ej. gemini-3.8-flash, gemini-2.5-pro)")
    parser.add_argument("--effort", "-e", type=str, choices=["none", "low", "medium", "high"], help="Presupuesto de thinking")
    parser.add_argument("--no-think", action="store_true", help="Desactiva el razonamiento thinking (thinking_budget=0)")
    parser.add_argument("--self-test", action="store_true", help="Ejecuta auto-diagnóstico de integridad operativa y finaliza")
    args = parser.parse_args()

    if args.self_test:
        from core.commands import handle_slash_command
        _, msg = handle_slash_command("/test", {"model": "check", "history": []})
        Console().print(msg)
        sys.exit(0)

    config = load_config()
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        print("\033[1;31mERROR:\033[0m No se encontró la variable de entorno GEMINI_API_KEY.")
        print("Exporta tu clave con: export GEMINI_API_KEY='tu_clave' antes de iniciar.")
        sys.exit(1)

    initial_model = args.model if args.model else config.get("agent", {}).get("default_model", "gemini-3.8-flash")
    initial_effort = "none" if args.no_think else (args.effort if args.effort else config.get("agent", {}).get("default_effort", "medium"))
    config.setdefault("agent", {})["default_model"] = initial_model
    config["agent"]["default_effort"] = initial_effort

    agent_state = {
        "model": initial_model,
        "effort": initial_effort,
        "reinit_chat": False,
        "trigger_compact": False,
        "history": []
    }

    chat_log = ChatLog()
    status_info = {
        "status": "Listo",
        "is_busy": False,
    }

    input_queue = queue.Queue()
    stop_event = threading.Event()

    # Mecánica interactiva para Safety Gate en TUI
    safety_waiting_event = threading.Event()
    safety_response_val = [False]
    safety_command_active = [""]

    def ui_safety_handler(command: str) -> bool:
        safety_command_active[0] = command
        chat_log.append(
            f"\n[bold red]⚠️  [SAFETY GATE] Gemini solicita ejecutar comando sensible:[/bold red]\n"
            f"[bold yellow]   {command}[/bold yellow]\n"
            f"[bold cyan]¿Autorizar en el Host? Escribe 's' o 'n' en la entrada inferior.[/bold cyan]\n"
        )
        status_info["status"] = "⚠️ Esperando confirmación [s/N]"
        try:
            get_app().invalidate()
        except Exception:
            pass

        safety_waiting_event.clear()
        # Esperar hasta 60s por respuesta humana
        safety_waiting_event.wait(timeout=60)
        status_info["status"] = "Razonando y procesando..."
        safety_command_active[0] = ""
        try:
            get_app().invalidate()
        except Exception:
            pass
        return safety_response_val[0]

    # Registrar el Safety Gate Handler en tools/terminal
    set_safety_gate_handler(ui_safety_handler)

    # Callbacks desacoplados para el agente
    def on_agent_output(content: Any):
        chat_log.append(content)
        try:
            get_app().invalidate()
        except Exception:
            pass

    def on_agent_status(st: str):
        status_info["status"] = st
        try:
            get_app().invalidate()
        except Exception:
            pass

    # Inicializar el agente
    agent = AgyMiniAgent(
        config=config,
        api_key=api_key,
        output_handler=on_agent_output,
        status_handler=on_agent_status
    )
    agent_state["session_id"] = agent.session_id

    # Banner de bienvenida
    chat_log.append(Panel(
        "[bold cyan]Sysadmin Mini (`agy-mini`)[/bold cyan] [green]v0.1.0[/green]\n"
        "[dim]Agente Autónomo de FamGuerra en Proxmox VE (192.168.100.200)[/dim]\n"
        "[dim]Entorno TUI Split-Screen Activo: Puedes redactar y encolar mensajes continuamente.[/dim]\n"
        "[dim cyan]Atajos: [bold]Enter[/bold]: Enviar/Encolar │ [bold]Ctrl+J[/bold]: Salto de línea │ [bold]Rueda/PgUp/PgDn[/bold]: Scroll │ [bold]/help[/bold]: Comandos[/dim cyan]",
        border_style="cyan"
    ))

    # Definición de controles de interfaz Prompt Toolkit
    def get_chat_text():
        return chat_log.get_formatted_text()

    def on_mouse_scroll_up():
        chat_log.scroll_up(4)
        try:
            get_app().invalidate()
        except Exception:
            pass

    def on_mouse_scroll_down():
        chat_log.scroll_down(4)
        try:
            get_app().invalidate()
        except Exception:
            pass

    chat_window = Window(
        content=MouseScrollableTextControl(
            get_chat_text,
            get_cursor_position=chat_log.get_cursor_position,
            on_scroll_up=on_mouse_scroll_up,
            on_scroll_down=on_mouse_scroll_down
        ),
        wrap_lines=True,
        always_hide_cursor=True,
        right_margins=[ScrollbarMargin()]
    )

    def get_status_bar():
        model = agent_state.get("model", "gemini-3.8-flash")
        effort = agent_state.get("effort", "medium")
        st = status_info["status"]
        qsize = input_queue.qsize()

        busy_color = "#ffaf00" if status_info["is_busy"] else "#5fd700"
        q_color = "#d787ff" if qsize > 0 else "#888888"

        return to_formatted_text(ANSI(
            f"\033[48;5;236m "
            f"\033[1;36magy-mini\033[0m \033[2m│\033[0m "
            f"\033[32m{model}\033[0m (\033[33m{effort}\033[0m) \033[2m│\033[0m "
            f"\033[1mEstado:\033[0m \033[38;5;{214 if status_info['is_busy'] else 82}m● {st}\033[0m \033[2m│\033[0m "
            f"\033[1mCola:\033[0m \033[38;5;{177 if qsize > 0 else 244}m[{qsize}]\033[0m \033[2m│\033[0m "
            f"\033[2mRueda/PgUp/PgDn: Scroll │ Enter: Enviar │ C-J: Salto │ /exit\033[0m "
            f"\033[0m"
        ))

    status_window = Window(
        content=FormattedTextControl(get_status_bar),
        height=1,
        style="class:status-bar"
    )

    history_file = os.path.expanduser("~/.agy_mini_history")
    input_buffer = Buffer(
        history=FileHistory(history_file),
        multiline=True
    )

    input_window = Window(
        content=BufferControl(buffer=input_buffer),
        height=3
    )

    # Paneles con marco (Frame)
    chat_frame = Frame(
        body=chat_window,
        title=" [1] Conversación, Razonamiento & Herramientas "
    )

    input_frame = Frame(
        body=input_window,
        title=" [2] Entrada / Prompt Fijo "
    )

    root_container = HSplit([
        chat_frame,
        status_window,
        input_frame
    ])

    bindings = KeyBindings()

    @bindings.add('enter')
    def _(event):
        text = input_buffer.text.strip()
        if not text:
            return

        input_buffer.reset()

        # Si el safety gate está esperando respuesta
        if safety_command_active[0]:
            ans = text.lower() in ["s", "si", "y", "yes"]
            safety_response_val[0] = ans
            chat_log.append(f"[bold cyan]👤 Respuesta Safety Gate:[/bold cyan] {'✔ Autorizado' if ans else '❌ Rechazado'}")
            safety_waiting_event.set()
            return

        # Comando de salida
        if text.lower() in ["/exit", "/salir", "exit", "quit"]:
            chat_log.append("[yellow]Cerrando sesión de Sysadmin Mini. Hasta luego.[/yellow]")
            input_queue.put(None)
            event.app.exit()
            return

        # Reflejar inmediatamente en el panel superior
        if status_info["is_busy"]:
            chat_log.append(f"[dim cyan]👤 Tú (encolado):[/dim cyan] {text}")
        else:
            chat_log.append(f"[bold cyan]👤 Tú:[/bold cyan] {text}")

        # Asegurar auto-scroll al final al enviar
        chat_log.scroll_end()
        # Encolar para procesamiento asíncrono
        input_queue.put(text)
        event.app.invalidate()

    @bindings.add('c-j')
    def _(event):
        """Salto de línea con Ctrl+Enter / Ctrl+J."""
        event.current_buffer.insert_text('\n')

    @bindings.add('escape', 'enter')
    def _(event):
        """Alt+Enter para salto de línea."""
        event.current_buffer.insert_text('\n')

    @bindings.add('pageup')
    def _(event):
        chat_log.scroll_up(10)
        event.app.invalidate()

    @bindings.add('pagedown')
    def _(event):
        chat_log.scroll_down(10)
        event.app.invalidate()

    @bindings.add('home')
    def _(event):
        chat_log.scroll_home()
        event.app.invalidate()

    @bindings.add('end')
    def _(event):
        chat_log.scroll_end()
        event.app.invalidate()

    @bindings.add('c-c')
    def _(event):
        if input_buffer.text:
            input_buffer.reset()
        else:
            chat_log.append("[yellow]Usa [bold]/exit[/bold] o [bold]Ctrl+D[/bold] para salir.[/yellow]")
            event.app.invalidate()

    @bindings.add('c-d')
    def _(event):
        input_queue.put(None)
        event.app.exit()

    style = Style.from_dict({
        'status-bar': 'bg:#262626 #e0e0e0',
        'frame.border': '#00afff',
        'frame.label': '#00d7ff bold',
    })

    app = Application(
        layout=Layout(root_container, focused_element=input_window),
        key_bindings=bindings,
        style=style,
        mouse_support=True,
        full_screen=True
    )

    # Worker Thread en segundo plano
    def worker_loop():
        while not stop_event.is_set():
            try:
                item = input_queue.get()
                if item is None:
                    break

                status_info["is_busy"] = True
                status_info["status"] = "Razonando y procesando..."
                try:
                    app.invalidate()
                except Exception:
                    pass

                # Evaluar comandos de barra inclinada
                is_cmd, msg = handle_slash_command(item, agent_state)
                if is_cmd:
                    chat_log.append(msg)
                    if agent_state.get("reinit_chat"):
                        agent.update_model_or_effort(agent_state["model"], agent_state["effort"])
                        agent_state["reinit_chat"] = False
                    if agent_state.get("trigger_compact"):
                        agent.compact_history()
                        agent_state["trigger_compact"] = False
                else:
                    # Procesar turno con Gemini y herramientas
                    agent.process_turn(item)

                status_info["is_busy"] = False
                status_info["status"] = "Listo"
                try:
                    app.invalidate()
                except Exception:
                    pass
                input_queue.task_done()
            except Exception as e:
                chat_log.append(f"[bold red]Error en procesamiento:[/bold red] {e}")
                status_info["is_busy"] = False
                status_info["status"] = "Listo"
                try:
                    app.invalidate()
                except Exception:
                    pass

    worker = threading.Thread(target=worker_loop, daemon=True)
    worker.start()

    try:
        app.run()
    finally:
        stop_event.set()
        input_queue.put(None)
        agent.close()


if __name__ == "__main__":
    main()
