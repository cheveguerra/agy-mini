"""
Módulo de Gestión y Descubrimiento Dinámico de Servidores MCP.
Lee la configuración declarativa (estilo Claude Desktop / Goose / Antigravity),
inicia los servidores por stdio, negocia capabilities e inyecta dinámicamente
sus esquemas y herramientas en Google Gemini sin quemar código en duro.
"""

import os
from typing import Dict, Any, List, Tuple
from google.genai import types
from tools.mcp_client import MCPClient

class MCPManager:
    def __init__(self, mcp_config: Dict[str, Any]):
        self.mcp_config = mcp_config or {}
        self.clients: Dict[str, MCPClient] = {}
        # Mapeo: tool_name -> (server_name, client)
        self.tool_routes: Dict[str, Tuple[str, MCPClient]] = {}
        # Declaraciones listas para Gemini
        self.declarations: List[types.FunctionDeclaration] = []

    def start_all(self):
        """Inicia los servidores MCP habilitados y descubre sus herramientas en caliente."""
        for server_name, server_def in self.mcp_config.items():
            if not isinstance(server_def, dict):
                continue

            enabled = server_def.get("enabled", True)
            if not enabled:
                continue

            # Compatible con sintaxis command/cmd y args
            cmd = server_def.get("command") or server_def.get("cmd")
            if not cmd:
                continue

            args = server_def.get("args", [])
            env = server_def.get("env", None)

            try:
                client = MCPClient(cmd, args)
                if client.start():
                    self.clients[server_name] = client
                    tools = client.list_tools()
                    for t in tools:
                        t_name = t.get("name")
                        t_desc = t.get("description", "")
                        t_schema = t.get("inputSchema")

                        # Registrar ruta de ejecución
                        self.tool_routes[t_name] = (server_name, client)

                        # Crear declaración nativa para Gemini types
                        decl = types.FunctionDeclaration(
                            name=t_name,
                            description=t_desc,
                            parameters_json_schema=t_schema
                        )
                        self.declarations.append(decl)
                else:
                    print(f"[Aviso] No se pudo inicializar el servidor MCP: {server_name}")
            except Exception as e:
                print(f"[Error] Fallo al cargar servidor MCP {server_name}: {e}")

    def get_function_declarations(self) -> List[types.FunctionDeclaration]:
        """Devuelve las declaraciones de herramientas descubiertas."""
        return self.declarations

    def has_tool(self, name: str) -> bool:
        return name in self.tool_routes

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Enruta la ejecución al cliente MCP correspondiente."""
        if name not in self.tool_routes:
            return {"error": f"Herramienta MCP '{name}' no registrada."}
        
        server_name, client = self.tool_routes[name]
        try:
            return client.call_tool(name, arguments)
        except Exception as e:
            return {"error": f"Fallo al ejecutar herramienta MCP '{name}' en '{server_name}': {e}"}

    def close_all(self):
        """Cierra todos los procesos hijos de MCP de forma limpia."""
        for name, client in self.clients.items():
            try:
                client.close()
            except Exception:
                pass
