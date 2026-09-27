"""
Bucle Conversacional de Sysadmin Mini con la API Oficial de Google Gemini (google-genai).
Gestiona el ciclo de Function Calling, ejecución de herramientas nativas, MCP dinámicos y streaming Rich.
"""

import os
from typing import Dict, Any, List, Callable
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from google import genai
from google.genai import types

# Importar herramientas nativas
from tools.fs import list_dir, read_file, write_file, replace_file_content, search_files
from tools.terminal import run_command
from tools.async_tasks import launch_detached_task, check_task_status
from tools.mcp_manager import MCPManager
from core.context import build_system_instruction
from core.usage import TokenTracker
from datetime import datetime

console = Console()

NATIVE_FUNCTIONS: Dict[str, Callable] = {
    "list_dir": list_dir,
    "read_file": read_file,
    "write_file": write_file,
    "replace_file_content": replace_file_content,
    "search_files": search_files,
    "run_command": run_command,
    "launch_detached_task": launch_detached_task,
    "check_task_status": check_task_status,
}

NATIVE_DECLARATIONS = [
    list_dir,
    read_file,
    write_file,
    replace_file_content,
    search_files,
    run_command,
    launch_detached_task,
    check_task_status,
]

EFFORT_BUDGET_MAP = {
    "none": 0,
    "low": 1024,
    "medium": 4096,
    "high": 16384
}

class AgyMiniAgent:
    def __init__(self, config: Dict[str, Any], api_key: str, output_handler: Callable[[Any], None] = None, status_handler: Callable[[str], None] = None):
        self.config = config
        self.api_key = api_key
        self.output_handler = output_handler
        self.status_handler = status_handler
        self.model_name = config.get("agent", {}).get("default_model", "gemini-3.8-flash")
        self.effort = config.get("agent", {}).get("default_effort", "medium")
        self.system_instruction = build_system_instruction(config)
        self.client = None
        self.chat = None
        
        # Gestor dinámico de servidores MCP
        self.mcp_manager = MCPManager(config.get("mcp_servers", {}))
        self.mcp_manager.start_all()

        # Telemetría de tokens SQLite (libre de WAL)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.tracker = TokenTracker()
        self.key_suffix = f"...{self.api_key[-4:]}" if len(self.api_key) >= 4 else "unknown"
        self.recent_tool_calls: List[tuple] = []
        self.turn_counter = 0

        self._init_client()

    def emit(self, content: Any):
        """Emite contenido al callback registrado o directamente a console.print."""
        if self.output_handler:
            self.output_handler(content)
        else:
            console.print(content)

    def set_status(self, text: str):
        """Notifica el estado actual de ejecución a la TUI."""
        if self.status_handler:
            self.status_handler(text)

    def _init_client(self):
        try:
            self.client = genai.Client(api_key=self.api_key)
            
            # Mapear esfuerzo a presupuesto de pensamiento
            budget = EFFORT_BUDGET_MAP.get(self.effort, 4096)
            thinking_config = types.ThinkingConfig(thinking_budget=budget)

            # Combinar herramientas nativas de Python + herramientas descubiertas por MCP
            tools_list = list(NATIVE_DECLARATIONS)
            mcp_decls = self.mcp_manager.get_function_declarations()
            if mcp_decls:
                tools_list.append(types.Tool(function_declarations=mcp_decls))

            generate_config = types.GenerateContentConfig(
                system_instruction=self.system_instruction,
                temperature=self.config.get("agent", {}).get("temperature", 0.2),
                max_output_tokens=self.config.get("agent", {}).get("max_output_tokens", 8192),
                tools=tools_list,
                thinking_config=thinking_config
            )

            self.chat = self.client.chats.create(
                model=self.model_name,
                config=generate_config
            )
        except Exception as e:
            self.emit(f"[bold red]Error al inicializar cliente Gemini:[/bold red] {e}")

    def update_model_or_effort(self, new_model: str = None, new_effort: str = None):
        if new_model:
            self.model_name = new_model
        if new_effort:
            self.effort = new_effort
        # Reiniciar sesión con nueva configuración
        self._init_client()

    def compact_history(self) -> bool:
        """Compacta el historial conversacional resumiendo turnos anteriores sin romper la alternancia."""
        if not self.chat or not hasattr(self.chat, "_history") or len(self.chat._history) < 3:
            self.emit("[yellow]Historial insuficiente para compactar.[/yellow]")
            return False

        self.set_status("Compactando historial...")
        try:
            history_text = []
            for item in self.chat._history:
                role = item.role
                texts = [p.text for p in item.parts if hasattr(p, "text") and p.text]
                if texts:
                    history_text.append(f"{role.upper()}: {' '.join(texts)}")

            full_history = "\n".join(history_text)
            prompt = (
                "Resume en menos de 500 palabras el siguiente historial técnico de administración de sistemas. "
                "Conserva estrictamente: acuerdos tomados, rutas de archivos modificados, comandos ejecutados "
                "y estado actual del sistema. Homelab Proxmox VE:\n\n"
                f"{full_history}"
            )

            # Inferencia rápida sin thinking para resumir
            summary_response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=1024,
                    thinking_config=types.ThinkingConfig(thinking_budget=0)
                )
            )

            summary_text = summary_response.text.strip() if summary_response.text else "Historial previo condensado."

            self.chat._history = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=f"[Contexto previo compactado]:\n{summary_text}")]
                ),
                types.Content(
                    role="model",
                    parts=[types.Part.from_text(text="Entendido, mantengo en memoria el contexto compactado de los turnos previos. ¿En qué continuamos?")]
                )
            ]
            self.emit(Panel(
                Markdown(f"**Historial compactado exitosamente.**\n\n*Resumen activo:*\n{summary_text}"),
                title="[bold cyan]Contexto Compactado[/bold cyan]",
                border_style="cyan",
                expand=False
            ))
            return True
        except Exception as e:
            self.emit(f"[red]Error al compactar historial: {e}[/red]")
            return False
        finally:
            self.set_status("Listo")

    def process_turn(self, user_input: str):
        """Procesa una consulta del usuario gestionando múltiples llamadas a herramientas."""
        if not self.chat:
            self.emit("[red]Cliente Gemini no inicializado.[/red]")
            return

        history_len_before = len(self.chat._history) if hasattr(self.chat, "_history") else 0
        self.set_status("Razonando y procesando...")
        if not self.status_handler:
            with console.status("[bold cyan]Razonando y procesando...[/bold cyan]", spinner="dots"):
                response = self.chat.send_message(user_input)
        else:
            response = self.chat.send_message(user_input)

        if hasattr(response, "usage_metadata") and response.usage_metadata:
            self.tracker.record_usage(self.session_id, self.model_name, response.usage_metadata, "user_turn", self.key_suffix)

        had_tool_calls = False
        self.turn_counter += 1
        # Bucle de llamadas a herramientas (Tool Calls)
        while response.function_calls:
            had_tool_calls = True
            parts_responses = []
            for call in response.function_calls:
                fn_name = call.name
                fn_args = dict(call.args) if call.args else {}
                args_key = (fn_name, str(sorted(fn_args.items())))

                # Centinela de degradación: detectar si pide exactamente lo mismo que en turnos recientes
                duplicate_calls = [t for t, k in self.recent_tool_calls[-12:] if k == args_key and t < self.turn_counter]
                if duplicate_calls:
                    self.emit(f"[bold yellow]⚠️ [Monitoreo] Re-ejecución redundante de {fn_name}(). Posible amnesia o degradación de contexto.[/bold yellow]")
                self.recent_tool_calls.append((self.turn_counter, args_key))

                self.set_status(f"Ejecutando tool: {fn_name}...")
                self.emit(f"[dim cyan]🔧 [Tool Call] {fn_name}({fn_args})[/dim cyan]")

                # 1. ¿Es herramienta nativa de Python?
                if fn_name in NATIVE_FUNCTIONS:
                    try:
                        tool_result = NATIVE_FUNCTIONS[fn_name](**fn_args)
                    except Exception as e:
                        tool_result = {"error": f"Error ejecutando {fn_name}: {str(e)}"}
                # 2. ¿Es herramienta proveída dinámicamente por algún servidor MCP?
                elif self.mcp_manager.has_tool(fn_name):
                    tool_result = self.mcp_manager.call_tool(fn_name, fn_args)
                else:
                    tool_result = {"error": f"Herramienta desconocida: {fn_name}"}

                parts_responses.append(
                    types.Part.from_function_response(
                        name=fn_name,
                        response={"result": tool_result}
                    )
                )

            # Devolver los resultados de las herramientas a Gemini
            self.set_status("Procesando respuesta de herramientas...")
            if not self.status_handler:
                with console.status("[bold cyan]Procesando respuesta de herramientas...[/bold cyan]", spinner="dots"):
                    response = self.chat.send_message(parts_responses)
            else:
                response = self.chat.send_message(parts_responses)

            if hasattr(response, "usage_metadata") and response.usage_metadata:
                self.tracker.record_usage(self.session_id, self.model_name, response.usage_metadata, "tool_turn", self.key_suffix)

        # Mostrar respuesta final formateada en Markdown
        if response.text:
            self.emit(Panel(
                Markdown(response.text),
                title="[bold green]Sysadmin Mini[/bold green]",
                border_style="green",
                expand=False
            ))

        # PODA DE RONDAS INTERMEDIAS DE TOOL CALLS:
        # Reemplaza los pares intermedios por un único par limpio user -> model.
        if had_tool_calls and hasattr(self.chat, "_history"):
            try:
                user_content = types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=user_input)]
                )
                model_content = types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=response.text or "Herramientas ejecutadas exitosamente.")]
                )
                self.chat._history = self.chat._history[:history_len_before] + [user_content, model_content]
            except Exception as e:
                self.emit(f"[dim yellow](Poda de herramientas omitida: {e})[/dim yellow]")

        # AUTO-COMPACTACIÓN POR UMBRAL (60,000 tokens):
        last_prompt_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            last_prompt_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        if last_prompt_tokens > 60000:
            self.emit(f"[yellow]⚠️ Contexto superó {last_prompt_tokens:,} tokens. Auto-compactando historial...[/yellow]")
            self.compact_history()

        self.set_status("Listo")

    def close(self):
        """Libera clientes y procesos MCP."""
        if self.mcp_manager:
            self.mcp_manager.close_all()
