"""
Módulo de Herramientas Web para Sysadmin Mini.
Implementa búsqueda web y extracción de contenido en texto plano/Markdown
sin depender de claves de API externas de búsqueda.
"""

import re
import urllib.parse
import requests
from typing import Dict, Any, List
from html.parser import HTMLParser

class SimpleHTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.in_script = False
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        if tag in ["script", "style", "noscript"]:
            self.in_script = True
        elif tag in ["p", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"]:
            self.text_parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ["script", "style", "noscript"]:
            self.in_script = False
        elif tag in ["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"]:
            self.text_parts.append("\n")

    def handle_data(self, data):
        if not self.in_script:
            cleaned = data.strip()
            if cleaned:
                self.text_parts.append(" " + cleaned)

    def get_text(self) -> str:
        raw = "".join(self.text_parts)
        # Limpiar múltiples saltos de línea consecutivos
        return re.sub(r"\n\s*\n+", "\n\n", raw).strip()


def search_web(query: str, max_results: int = 5) -> Dict[str, Any]:
    """
    Realiza una búsqueda web pública y ligera para consultar documentación,
    manuales o errores técnicos de Linux/software.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return {"error": f"El servicio de búsqueda devolvió status HTTP {resp.status_code}"}

        html = resp.text
        # Extraer enlaces y títulos de resultados de DuckDuckGo HTML
        # <a class="result__snippet" ...> o <a class="result__url" ...>
        results = []
        # Expresión regular para bloques de resultados
        blocks = re.findall(r'<a[^>]+class="result__snippet[^"]*"[^>]*>(.*?)</a>', html, re.DOTALL)
        titles = re.findall(r'<a[^>]+class="result__url[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL)

        for i in range(min(len(titles), len(blocks), max_results)):
            link_raw, link_display = titles[i]
            # Desempaquetar URL de redirección DDG si aplica
            clean_url = link_raw
            if "uddg=" in link_raw:
                try:
                    clean_url = urllib.parse.unquote(link_raw.split("uddg=")[1].split("&")[0])
                except Exception:
                    pass

            snippet = re.sub(r"<[^>]+>", "", blocks[i]).strip()
            results.append({
                "title": re.sub(r"<[^>]+>", "", link_display).strip(),
                "url": clean_url,
                "snippet": snippet
            })

        return {
            "query": query,
            "total_results": len(results),
            "results": results
        }
    except Exception as e:
        return {"error": f"Fallo en la búsqueda web: {str(e)}"}


def read_url_content(url: str, max_chars: int = 8000) -> Dict[str, Any]:
    """
    Descarga el contenido de una URL web y lo convierte a texto limpio legible,
    descartando scripts, estilos y etiquetas HTML pesadas.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=12)
        if resp.status_code != 200:
            return {"error": f"Error al descargar URL. Status HTTP: {resp.status_code}"}

        content_type = resp.headers.get("Content-Type", "")
        if "text/html" in content_type:
            parser = SimpleHTMLTextExtractor()
            parser.feed(resp.text)
            text_content = parser.get_text()
        else:
            text_content = resp.text.strip()

        total_length = len(text_content)
        truncated = total_length > max_chars
        final_text = text_content[:max_chars]

        if truncated:
            final_text += f"\n\n[... Truncado a {max_chars} caracteres de un total de {total_length} ...]"

        return {
            "url": url,
            "total_chars": total_length,
            "truncated": truncated,
            "content": final_text
        }
    except Exception as e:
        return {"error": f"Fallo al leer contenido de la URL {url}: {str(e)}"}
