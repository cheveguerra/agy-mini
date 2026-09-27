"""
Cliente Ligero MCP (Model Context Protocol) sobre stdio.
Permite conectar herramientas expuestas por servidores MCP locales (como sqlite-memory)
utilizando el protocolo estándar JSON-RPC 2.0 sin frameworks pesados.
"""

import subprocess
import json
import os
from typing import Dict, Any, List, Optional

class MCPClient:
    def __init__(self, command: str, args: Optional[List[str]] = None):
        self.command = command
        self.args = args or []
        self.process: Optional[subprocess.Popen] = None
        self._msg_id = 0

    def start(self) -> bool:
        """Inicia el proceso del servidor MCP."""
        try:
            full_cmd = [self.command] + self.args
            self.process = subprocess.Popen(
                full_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            # Inicialización básica MCP
            self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agy-mini", "version": "0.1.0"}
            })
            return True
        except Exception as e:
            print(f"Error al iniciar MCP server ({self.command}): {e}")
            return False

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def _send_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        if not self.process or not self.process.stdin or not self.process.stdout:
            return None

        req_id = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {}
        }

        try:
            msg = json.dumps(payload) + "\n"
            self.process.stdin.write(msg)
            self.process.stdin.flush()

            # Leer respuesta
            line = self.process.stdout.readline()
            if not line:
                return None
            return json.loads(line)
        except Exception as e:
            print(f"Error en comunicación MCP: {e}")
            return None

    def list_tools(self) -> List[Dict[str, Any]]:
        """Solicita la lista de herramientas disponibles al servidor MCP."""
        resp = self._send_request("tools/list")
        if resp and "result" in resp and "tools" in resp["result"]:
            return resp["result"]["tools"]
        return []

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta una herramienta en el servidor MCP."""
        resp = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments
        })
        if resp and "result" in resp:
            return resp["result"]
        if resp and "error" in resp:
            return {"error": resp["error"]}
        return {"error": "Respuesta vacía o inválida del servidor MCP."}

    def close(self):
        """Cierra el proceso del servidor."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                self.process.kill()
