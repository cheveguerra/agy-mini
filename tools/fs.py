"""
Módulo de Herramientas de Sistema de Archivos (Anti-Congelamiento).
Implementa operaciones deterministas con límites duros de profundidad y paginación
para prevenir escaneos masivos en discos de 16 TB.
"""

import os
import fnmatch
from typing import Dict, Any, List

BLACKLIST_PATHS = [
    "/mnt/data1",
    "/mnt/parity",
    "node_modules",
    ".git",
    ".venv",
    "__pycache__",
]

def list_dir(path: str = ".", max_items: int = 50) -> Dict[str, Any]:
    """
    Lista el contenido de un directorio con ESTRICTAMENTE UN SOLO NIVEL de profundidad.
    Jamás realiza recursión ciega, garantizando respuesta en milisegundos.
    """
    try:
        resolved_path = os.path.abspath(os.path.expanduser(path))
        if not os.path.exists(resolved_path):
            return {"error": f"La ruta no existe: {path}"}
        if not os.path.isdir(resolved_path):
            return {"error": f"La ruta no es un directorio: {path}"}

        items = []
        with os.scandir(resolved_path) as entries:
            for entry in entries:
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    size = entry.stat().st_size if not is_dir else None
                    items.append({
                        "name": entry.name,
                        "is_dir": is_dir,
                        "size_bytes": size
                    })
                except (PermissionError, FileNotFoundError):
                    continue

        # Ordenar: primero carpetas, luego alfabético
        items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        total_found = len(items)
        truncated = total_found > max_items

        return {
            "path": resolved_path,
            "total_items": total_found,
            "truncated": truncated,
            "items": items[:max_items]
        }
    except Exception as e:
        return {"error": f"Fallo al listar directorio {path}: {str(e)}"}


def read_file(path: str, start_line: int = 1, end_line: int = 250) -> Dict[str, Any]:
    """
    Lee el contenido de un archivo de texto de forma paginada y numerada (1-indexed).
    Evita saturar la ventana de tokens del LLM con lecturas completas innecesarias.
    """
    try:
        resolved_path = os.path.abspath(os.path.expanduser(path))
        if not os.path.exists(resolved_path):
            return {"error": f"El archivo no existe: {path}"}
        if not os.path.isfile(resolved_path):
            return {"error": f"La ruta no es un archivo: {path}"}

        with open(resolved_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)
        if start_line < 1:
            start_line = 1
        if end_line > total_lines:
            end_line = total_lines

        if start_line > total_lines:
            return {
                "path": resolved_path,
                "total_lines": total_lines,
                "error": f"start_line ({start_line}) es mayor que el total de líneas ({total_lines})"
            }

        sliced_lines = lines[start_line - 1 : end_line]
        formatted = "".join(f"{i + start_line}: {line}" for i, line in enumerate(sliced_lines))

        return {
            "path": resolved_path,
            "total_lines": total_lines,
            "start_line": start_line,
            "end_line": end_line,
            "content": formatted
        }
    except Exception as e:
        return {"error": f"Error al leer archivo {path}: {str(e)}"}


def write_file(path: str, content: str, overwrite: bool = False) -> Dict[str, Any]:
    """
    Escribe contenido en un archivo. Crea los directorios padre de forma automática.
    Si el archivo ya existe y overwrite=False, rechaza la operación por seguridad.
    """
    try:
        resolved_path = os.path.abspath(os.path.expanduser(path))
        parent = os.path.dirname(resolved_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

        if os.path.exists(resolved_path) and not overwrite:
            return {
                "error": f"El archivo {path} ya existe. Especifica overwrite=True si deseas sobrescribirlo."
            }

        with open(resolved_path, "w", encoding="utf-8") as f:
            f.write(content)

        return {
            "status": "success",
            "path": resolved_path,
            "bytes_written": len(content.encode("utf-8"))
        }
    except Exception as e:
        return {"error": f"Error al escribir archivo {path}: {str(e)}"}


def replace_file_content(path: str, target: str, replacement: str) -> Dict[str, Any]:
    """
    Reemplaza quirúrgicamente un fragmento exacto de texto en un archivo existente.
    Exige que el fragmento 'target' aparezca exactamente una sola vez para evitar colisiones.
    """
    try:
        resolved_path = os.path.abspath(os.path.expanduser(path))
        if not os.path.exists(resolved_path):
            return {"error": f"El archivo no existe: {path}"}

        with open(resolved_path, "r", encoding="utf-8") as f:
            original = f.read()

        occurrences = original.count(target)
        if occurrences == 0:
            return {"error": f"El fragmento target no se encontró en el archivo {path}."}
        if occurrences > 1:
            return {
                "error": f"El fragmento target aparece {occurrences} veces. Proporciona más contexto alrededor para que sea único."
            }

        updated = original.replace(target, replacement, 1)
        with open(resolved_path, "w", encoding="utf-8") as f:
            f.write(updated)

        return {
            "status": "success",
            "path": resolved_path,
            "message": "Reemplazo quirúrgico aplicado exitosamente."
        }
    except Exception as e:
        return {"error": f"Error en reemplazo quirúrgico: {str(e)}"}


def search_files(pattern: str, base_path: str = "/mnt/data2/Software", max_depth: int = 2) -> Dict[str, Any]:
    """
    Búsqueda acotada de nombres de archivo por patrón glob (ej. '*.ts', 'docker-compose*.yml').
    Tiene una profundidad máxima obligatoria y listas negras estrictas para evitar atascos.
    """
    try:
        root_dir = os.path.abspath(os.path.expanduser(base_path))
        # Validar listas negras
        for bl in BLACKLIST_PATHS:
            if root_dir == bl or root_dir.startswith(bl + os.sep):
                return {
                    "error": f"La búsqueda en '{root_dir}' está prohibida por lista negra de seguridad ({bl})."
                }

        results = []
        base_depth = root_dir.rstrip(os.sep).count(os.sep)

        for current_root, dirs, files in os.walk(root_dir):
            current_depth = current_root.rstrip(os.sep).count(os.sep) - base_depth
            if current_depth >= max_depth:
                dirs.clear()  # No descender más

            # Filtrar carpetas prohibidas in-place
            dirs[:] = [d for d in dirs if d not in BLACKLIST_PATHS and not d.startswith(".")]

            for file in files:
                if fnmatch.fnmatch(file, pattern):
                    full_path = os.path.join(current_root, file)
                    results.append(full_path)
                    if len(results) >= 50:
                        break
            if len(results) >= 50:
                break

        return {
            "base_path": root_dir,
            "pattern": pattern,
            "max_depth": max_depth,
            "total_matches": len(results),
            "matches": results
        }
    except Exception as e:
        return {"error": f"Error en búsqueda de archivos: {str(e)}"}


def grep_text(
    query: str,
    path: str = ".",
    file_pattern: str = "*",
    case_insensitive: bool = True,
    max_results: int = 50,
    max_depth: int = 3
) -> Dict[str, Any]:
    """
    Busca patrones de texto o código DENTRO de los archivos de un directorio o archivo específico.
    Devuelve nombre de archivo, número de línea y fragmento coincidente.
    Protegido con listas negras estrictas y límites de profundidad contra atascos en discos masivos.
    """
    try:
        resolved_path = os.path.abspath(os.path.expanduser(path))
        if not os.path.exists(resolved_path):
            return {"error": f"La ruta no existe: {path}"}

        # Validar listas negras
        for bl in BLACKLIST_PATHS:
            if resolved_path == bl or resolved_path.startswith(bl + os.sep):
                return {
                    "error": f"La búsqueda en '{resolved_path}' está prohibida por lista negra de seguridad ({bl})."
                }

        results = []
        target_query = query.lower() if case_insensitive else query

        # Si es un solo archivo
        if os.path.isfile(resolved_path):
            files_to_scan = [resolved_path]
        else:
            files_to_scan = []
            base_depth = resolved_path.rstrip(os.sep).count(os.sep)
            for current_root, dirs, files in os.walk(resolved_path):
                current_depth = current_root.rstrip(os.sep).count(os.sep) - base_depth
                if current_depth >= max_depth:
                    dirs.clear()
                dirs[:] = [d for d in dirs if d not in BLACKLIST_PATHS and not d.startswith(".")]

                for f in files:
                    if fnmatch.fnmatch(f, file_pattern):
                        files_to_scan.append(os.path.join(current_root, f))
                        if len(files_to_scan) >= 200:
                            break
                if len(files_to_scan) >= 200:
                    break

        for fpath in files_to_scan:
            try:
                # Omitir archivos mayores a 5 MB
                if os.path.getsize(fpath) > 5 * 1024 * 1024:
                    continue
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for line_num, line in enumerate(f, start=1):
                        check_line = line.lower() if case_insensitive else line
                        if target_query in check_line:
                            results.append({
                                "file": fpath,
                                "line_number": line_num,
                                "content": line.strip()[:200]
                            })
                            if len(results) >= max_results:
                                break
            except Exception:
                continue
            if len(results) >= max_results:
                break

        return {
            "query": query,
            "path": resolved_path,
            "files_scanned": len(files_to_scan),
            "total_matches": len(results),
            "matches": results
        }
    except Exception as e:
        return {"error": f"Error en grep_text: {str(e)}"}

