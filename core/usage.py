"""
Gestor de Telemetría y Registro Persistente de Tokens para Sysadmin Mini.
Almacena métricas en SQLite local (~/.agy_mini_usage.db) con modo TRUNCATE (libre de WAL).
"""

import os
import json
import sqlite3
import urllib.request
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

DEFAULT_DB_PATH = os.path.expanduser("~/.agy_mini_usage.db")
DEFAULT_EXCHANGE_RATE = 18.0
RATE_CACHE_TTL_HOURS = 6

# Tarifas estándar estimadas (Gemini 3.8 / 2.5 Flash por millón de tokens)
COST_PER_M_INPUT = 0.15    # $0.15 USD por millón de tokens de entrada
COST_PER_M_OUTPUT = 0.60   # $0.60 USD por millón de tokens de salida

class TokenTracker:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        # Configuración estándar blindada FamGuerra (cero WAL)
        conn.execute("PRAGMA journal_mode = TRUNCATE;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def _init_db(self):
        """Inicializa las tablas token_usage y app_metadata si no existen."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS token_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT (datetime('now', 'localtime')),
                    session_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER DEFAULT 0,
                    candidates_tokens INTEGER DEFAULT 0,
                    thinking_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    call_type TEXT DEFAULT 'turn'
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_token_usage_session ON token_usage(session_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_token_usage_timestamp ON token_usage(timestamp);")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS app_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at DATETIME DEFAULT (datetime('now', 'localtime'))
                );
            """)

    def _fetch_live_rate(self) -> Optional[float]:
        """Consulta APIs públicas livianas para obtener USD/MXN con timeout corto."""
        endpoints = [
            ("https://open.er-api.com/v6/latest/USD", lambda d: d.get("rates", {}).get("MXN")),
            ("https://api.exchangerate-api.com/v4/latest/USD", lambda d: d.get("rates", {}).get("MXN"))
        ]
        for url, extractor in endpoints:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "AgyMini/1.0"})
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        rate = extractor(data)
                        if rate and isinstance(rate, (int, float)) and rate > 0:
                            return float(rate)
            except Exception:
                continue
        return None

    def get_usd_to_mxn_rate(self) -> float:
        """Obtiene la tasa USD a MXN utilizando caché local en SQLite con TTL de 6h."""
        cached_rate = None
        needs_refresh = True
        try:
            with self._get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT value, updated_at FROM app_metadata WHERE key = 'usd_to_mxn_rate';")
                row = cur.fetchone()
                if row:
                    val_str, updated_str = row
                    cached_rate = float(val_str)
                    try:
                        updated_dt = datetime.strptime(updated_str, "%Y-%m-%d %H:%M:%S")
                        if datetime.now() - updated_dt < timedelta(hours=RATE_CACHE_TTL_HOURS):
                            needs_refresh = False
                    except Exception:
                        pass
        except Exception:
            pass

        if not needs_refresh and cached_rate:
            return cached_rate

        # Intentar refrescar en vivo
        live_rate = self._fetch_live_rate()
        if live_rate is not None:
            try:
                with self._get_connection() as conn:
                    conn.execute("""
                        INSERT INTO app_metadata (key, value, updated_at)
                        VALUES ('usd_to_mxn_rate', ?, datetime('now', 'localtime'))
                        ON CONFLICT(key) DO UPDATE SET
                            value = excluded.value,
                            updated_at = excluded.updated_at;
                    """, (str(live_rate),))
                return live_rate
            except Exception:
                return live_rate

        # Fallback a caché previa si la consulta falló
        if cached_rate:
            return cached_rate

        return DEFAULT_EXCHANGE_RATE

    def record_usage(self, session_id: str, model: str, usage_metadata: Any, call_type: str = "turn"):
        """Registra el consumo de un turno o respuesta de herramienta en SQLite."""
        if not usage_metadata:
            return

        prompt = getattr(usage_metadata, "prompt_token_count", 0) or 0
        candidates = getattr(usage_metadata, "candidates_token_count", 0) or 0
        total = getattr(usage_metadata, "total_token_count", 0) or 0
        
        # Buscar tokens de pensamiento si existen en el SDK
        thinking = getattr(usage_metadata, "thoughts_token_count", 0) or 0
        if not thinking and hasattr(usage_metadata, "candidates_tokens_details"):
            details = getattr(usage_metadata, "candidates_tokens_details", None)
            if details and hasattr(details, "thoughts_tokens_count"):
                thinking = details.thoughts_tokens_count or 0

        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO token_usage (
                        session_id, model, prompt_tokens, candidates_tokens, thinking_tokens, total_tokens, call_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """, (session_id, model, prompt, candidates, thinking, total, call_type))
        except Exception as e:
            # Fallback silencioso para no romper la conversación por telemetría
            pass

    def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """Calcula el total consumido en la sesión activa."""
        rate = self.get_usd_to_mxn_rate()
        try:
            with self._get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT 
                        COUNT(*),
                        COALESCE(SUM(prompt_tokens), 0),
                        COALESCE(SUM(candidates_tokens), 0),
                        COALESCE(SUM(thinking_tokens), 0),
                        COALESCE(SUM(total_tokens), 0)
                    FROM token_usage
                    WHERE session_id = ?;
                """, (session_id,))
                row = cur.fetchone()
                calls, p, c, th, tot = row
                cost_usd = (p / 1_000_000 * COST_PER_M_INPUT) + (c / 1_000_000 * COST_PER_M_OUTPUT)
                cost_mxn = cost_usd * rate
                return {
                    "calls": calls,
                    "prompt_tokens": p,
                    "candidates_tokens": c,
                    "thinking_tokens": th,
                    "total_tokens": tot,
                    "estimated_cost_usd": cost_usd,
                    "estimated_cost_mxn": cost_mxn,
                    "exchange_rate": rate
                }
        except Exception:
            return {
                "calls": 0, "prompt_tokens": 0, "candidates_tokens": 0, "thinking_tokens": 0, "total_tokens": 0,
                "estimated_cost_usd": 0.0, "estimated_cost_mxn": 0.0, "exchange_rate": rate
            }

    def get_today_summary(self) -> Dict[str, Any]:
        """Calcula el total consumido en el día de hoy."""
        rate = self.get_usd_to_mxn_rate()
        try:
            with self._get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT 
                        COUNT(*),
                        COALESCE(SUM(prompt_tokens), 0),
                        COALESCE(SUM(candidates_tokens), 0),
                        COALESCE(SUM(thinking_tokens), 0),
                        COALESCE(SUM(total_tokens), 0)
                    FROM token_usage
                    WHERE DATE(timestamp) = DATE('now', 'localtime');
                """)
                row = cur.fetchone()
                calls, p, c, th, tot = row
                cost_usd = (p / 1_000_000 * COST_PER_M_INPUT) + (c / 1_000_000 * COST_PER_M_OUTPUT)
                cost_mxn = cost_usd * rate
                return {
                    "calls": calls,
                    "prompt_tokens": p,
                    "candidates_tokens": c,
                    "thinking_tokens": th,
                    "total_tokens": tot,
                    "estimated_cost_usd": cost_usd,
                    "estimated_cost_mxn": cost_mxn,
                    "exchange_rate": rate
                }
        except Exception:
            return {
                "calls": 0, "prompt_tokens": 0, "candidates_tokens": 0, "thinking_tokens": 0, "total_tokens": 0,
                "estimated_cost_usd": 0.0, "estimated_cost_mxn": 0.0, "exchange_rate": rate
            }
