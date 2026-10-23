"""Persistência simples em JSON com escrita atômica e trava de arquivo.

Streamlit (várias sessões) e o worker podem gravar ao mesmo tempo, por isso
toda leitura-modificação-escrita passa por ``locked_update``.
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

try:  # fcntl não existe no Windows; lá usamos apenas a trava de thread.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

DATA_DIR = Path(os.environ.get("TRADEBOT_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

_thread_lock = threading.RLock()


@contextlib.contextmanager
def _file_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    with _thread_lock:
        with open(lock_path, "a+") as fh:
            if fcntl:
                fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl:
                    fcntl.flock(fh, fcntl.LOCK_UN)


def _read(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return default


def _write(path: Path, data: Any) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, path)


def load_json(name: str, default: Any = None) -> Any:
    path = DATA_DIR / name
    with _file_lock(path):
        return _read(path, default)


def save_json(name: str, data: Any) -> None:
    path = DATA_DIR / name
    with _file_lock(path):
        _write(path, data)


def locked_update(name: str, default: Any, fn: Callable[[Any], Any]) -> Any:
    """Lê o JSON, aplica ``fn`` (que altera e/ou devolve o objeto) e grava."""
    path = DATA_DIR / name
    with _file_lock(path):
        data = _read(path, default)
        result = fn(data)
        _write(path, data)
        return result
