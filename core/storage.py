"""Persistência dos dados da plataforma (contas, configurações e logs).

Dois modos, escolhidos automaticamente:

* **Banco Postgres** — quando ``DATABASE_URL`` está definida (secrets do
  Streamlit ou variável de ambiente). Recomendado para o Streamlit Community
  Cloud, cujo disco é apagado a cada reinício. Serve qualquer Postgres
  gratuito (Neon, Supabase etc.). Tudo fica em uma única tabela chave/valor
  ``tradebot_kv`` criada automaticamente.
* **Arquivos JSON locais** em ``data/`` — quando não há banco configurado.

Toda leitura-modificação-escrita passa por ``locked_update``: no banco usa
``SELECT … FOR UPDATE`` (transação), nos arquivos usa trava de arquivo.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

try:  # fcntl não existe no Windows; lá usamos apenas a trava de thread.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

log = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("TRADEBOT_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
TABLE = "tradebot_kv"


def get_secret(name: str) -> str | None:
    """Variável de ambiente ou, se rodando no Streamlit, ``st.secrets``."""
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st

        value = st.secrets.get(name)
    except Exception:  # noqa: BLE001 - fora do Streamlit ou sem secrets.toml
        value = None
    return str(value) if value else None


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


class FileBackend:
    name = "Arquivos locais (data/)"
    persistent = False

    def __init__(self, directory: Path):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @contextlib.contextmanager
    def _locked(self, path: Path):
        with self._lock, open(path.with_suffix(path.suffix + ".lock"), "a+") as fh:
            if fcntl:
                fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl:
                    fcntl.flock(fh, fcntl.LOCK_UN)

    def _read(self, path: Path, default: Any) -> Any:
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return default

    def _write(self, path: Path, data: Any) -> None:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(_dumps(data))
        os.replace(tmp, path)

    def load(self, name: str, default: Any) -> Any:
        path = self.dir / name
        with self._locked(path):
            return self._read(path, default)

    def save(self, name: str, data: Any) -> None:
        path = self.dir / name
        with self._locked(path):
            self._write(path, data)

    def update(self, name: str, default: Any, fn: Callable[[Any], Any]) -> Any:
        path = self.dir / name
        with self._locked(path):
            data = self._read(path, default)
            result = fn(data)
            self._write(path, data)
            return result

    def names(self) -> list[str]:
        return sorted(p.name for p in self.dir.glob("*.json"))


class PostgresBackend:
    name = "Banco de dados Postgres"
    persistent = True

    def __init__(self, url: str):
        import psycopg  # noqa: F401 - falha cedo se a dependência não estiver instalada

        self.url = url
        self._conn = None
        self._lock = threading.RLock()

    def _connect(self):
        import psycopg

        if self._conn is None or self._conn.closed or self._conn.broken:
            # prepare_threshold=None: compatível com poolers (PgBouncer/Supabase/Neon)
            self._conn = psycopg.connect(self.url, autocommit=True, connect_timeout=15, prepare_threshold=None)
            self._conn.execute(
                f"CREATE TABLE IF NOT EXISTS {TABLE} (name TEXT PRIMARY KEY, data JSONB NOT NULL, "
                "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        return self._conn

    def _run(self, fn: Callable):
        """Executa com uma nova tentativa caso a conexão ociosa tenha caído."""
        import psycopg

        with self._lock:
            for attempt in (1, 2):
                try:
                    return fn(self._connect())
                except psycopg.OperationalError:
                    if self._conn is not None:
                        with contextlib.suppress(Exception):
                            self._conn.close()
                    self._conn = None
                    if attempt == 2:
                        raise

    def load(self, name: str, default: Any) -> Any:
        row = self._run(lambda c: c.execute(f"SELECT data FROM {TABLE} WHERE name = %s", (name,)).fetchone())
        return row[0] if row else default

    def save(self, name: str, data: Any) -> None:
        self._run(lambda c: c.execute(
            f"INSERT INTO {TABLE} (name, data) VALUES (%s, %s::jsonb) "
            "ON CONFLICT (name) DO UPDATE SET data = EXCLUDED.data, updated_at = now()", (name, _dumps(data))))

    def update(self, name: str, default: Any, fn: Callable[[Any], Any]) -> Any:
        def _tx(conn):
            with conn.transaction():
                conn.execute(f"INSERT INTO {TABLE} (name, data) VALUES (%s, %s::jsonb) ON CONFLICT DO NOTHING",
                             (name, _dumps(default)))
                data = conn.execute(f"SELECT data FROM {TABLE} WHERE name = %s FOR UPDATE", (name,)).fetchone()[0]
                result = fn(data)
                conn.execute(f"UPDATE {TABLE} SET data = %s::jsonb, updated_at = now() WHERE name = %s",
                             (_dumps(data), name))
                return result

        return self._run(_tx)

    def names(self) -> list[str]:
        return [r[0] for r in self._run(lambda c: c.execute(f"SELECT name FROM {TABLE} ORDER BY name").fetchall())]


_backend = None
_backend_lock = threading.Lock()


def backend():
    global _backend
    with _backend_lock:
        if _backend is None:
            url = get_secret("DATABASE_URL")
            if url:
                try:
                    _backend = PostgresBackend(url)
                    _backend.names()  # testa a conexão
                except Exception as exc:  # noqa: BLE001
                    log.error("Banco indisponível (%s); usando arquivos locais.", exc)
                    _backend = FileBackend(DATA_DIR)
                    _backend.error = str(exc)
            else:
                _backend = FileBackend(DATA_DIR)
        return _backend


def load_json(name: str, default: Any = None) -> Any:
    return backend().load(name, default)


def save_json(name: str, data: Any) -> None:
    backend().save(name, data)


def locked_update(name: str, default: Any, fn: Callable[[Any], Any]) -> Any:
    """Lê o valor, aplica ``fn`` (que altera e/ou devolve o objeto) e grava."""
    return backend().update(name, default, fn)


def export_all() -> dict:
    """Backup completo (todas as chaves) para download."""
    b = backend()
    return {name: b.load(name, None) for name in b.names()}


def import_all(payload: dict) -> int:
    for name, data in payload.items():
        if name.endswith(".json") and data is not None:
            save_json(name, data)
    return len(payload)
