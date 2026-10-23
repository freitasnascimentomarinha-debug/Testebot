"""Contas de usuário (cadastro, login e senhas), sem dependência do Streamlit.

Ligue com o secret ``AUTH_MODE = "contas"``. Os usuários ficam na chave ``_users.json`` do armazenamento (Supabase/Postgres):
só o *hash* da senha é guardado (scrypt com sal aleatório). Segredos opcionais:

* ``SIGNUP_CODE``  — código de convite exigido no cadastro (sem ele, qualquer pessoa com o link pode criar conta);
* ``ALLOW_SIGNUP`` — ``false`` fecha o cadastro (só entram contas já criadas);
* ``AUTH_SECRET``  — chave que assina o link de "manter conectado" (se faltar, é derivada de DATABASE_URL);
* ``LEGACY_OWNER`` — usuário que herda os dados anteriores às contas (ver core/storage.py)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import time
from datetime import datetime, timezone

from core.storage import USERS_KEY, get_secret, locked_update, load_json

MAX_FAILS = 5
LOCK_SECONDS = 300
TOKEN_DAYS = 14
_USER_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,19}$")
_WEAK = {"12345678", "123456789", "1234567890", "password", "senha123", "qwertyui", "11111111", "abc12345", "senhasenha"}
_N, _R, _P = 2 ** 14, 8, 1


def enabled() -> bool:
    return (get_secret("AUTH_MODE") or "").strip().lower() in ("contas", "accounts", "usuarios")


def signup_open() -> bool:
    return (get_secret("ALLOW_SIGNUP") or "true").strip().lower() not in ("false", "0", "nao", "não", "no")


def needs_code() -> bool:
    return bool(get_secret("SIGNUP_CODE"))


# ------------------------------------------------------------------------------ senhas
def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got, base64.b64decode(dk))
    except Exception:  # noqa: BLE001
        return False


_DUMMY = hash_password("senha-falsa-para-igualar-o-tempo")


def normalize(username: str) -> str:
    return (username or "").strip().lower()


def check_password_strength(password: str) -> str | None:
    if len(password) < 8:
        return "A senha precisa ter pelo menos 8 caracteres."
    if password.lower() in _WEAK or len(set(password)) < 4:
        return "Senha fraca demais: evite sequências e repetições."
    return None


# ------------------------------------------------------------------------------ cadastro e login
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def register(username: str, password: str, code: str | None = None) -> str:
    """Cria a conta e devolve o usuário normalizado. Levanta ``ValueError`` com a mensagem para o usuário."""
    if not signup_open():
        raise ValueError("O cadastro de novas contas está fechado.")
    if needs_code() and not hmac.compare_digest((code or "").strip().encode(), get_secret("SIGNUP_CODE").encode()):
        raise ValueError("Código de convite incorreto.")
    user = normalize(username)
    if not _USER_RE.match(user):
        raise ValueError("Usuário: de 3 a 20 caracteres, só letras minúsculas, números, ponto, hífen e sublinhado.")
    if (msg := check_password_strength(password)):
        raise ValueError(msg)
    pw = hash_password(password)

    def _apply(users: dict):
        if user in users:
            raise ValueError("Este usuário já existe. Escolha outro.")
        users[user] = {"hash": pw, "created": _now(), "fails": 0, "locked_until": 0}

    locked_update(USERS_KEY, {}, _apply)
    return user


def authenticate(username: str, password: str) -> str:
    """Confere usuário e senha (com bloqueio após tentativas erradas). Devolve o usuário ou levanta ``ValueError``."""
    user = normalize(username)
    generic = ValueError("Usuário ou senha incorretos.")
    users = load_json(USERS_KEY, {}) or {}
    rec = users.get(user)
    if rec and rec.get("locked_until", 0) > time.time():
        raise ValueError(f"Conta bloqueada por tentativas erradas. Tente de novo em {int((rec['locked_until'] - time.time()) // 60) + 1} min.")
    ok = verify_password(password, rec["hash"] if rec else _DUMMY)  # sempre calcula: não revela se o usuário existe
    if not (rec and ok):
        if rec:
            def _fail(us: dict):
                r = us.get(user)
                if r:
                    r["fails"] = r.get("fails", 0) + 1
                    if r["fails"] >= MAX_FAILS:
                        r["fails"], r["locked_until"] = 0, time.time() + LOCK_SECONDS

            locked_update(USERS_KEY, {}, _fail)
        raise generic
    if rec.get("fails"):
        def _reset(us: dict):
            if user in us:
                us[user]["fails"] = 0

        locked_update(USERS_KEY, {}, _reset)
    return user


def change_password(username: str, old: str, new: str) -> None:
    user = authenticate(username, old)
    if (msg := check_password_strength(new)):
        raise ValueError(msg)
    pw = hash_password(new)

    def _apply(users: dict):
        users[user]["hash"] = pw

    locked_update(USERS_KEY, {}, _apply)


def info(username: str) -> dict | None:
    rec = (load_json(USERS_KEY, {}) or {}).get(normalize(username))
    return {"created": rec["created"]} if rec else None


def list_users() -> list[str]:
    return sorted((load_json(USERS_KEY, {}) or {}))


# ------------------------------------------------------------------------------ "manter conectado"
def _secret_key() -> bytes:
    return (get_secret("AUTH_SECRET") or hashlib.sha256((get_secret("DATABASE_URL") or "tradebot-local").encode()).hexdigest()).encode()


def make_token(username: str, days: int = TOKEN_DAYS) -> str:
    rec = (load_json(USERS_KEY, {}) or {}).get(normalize(username)) or {}
    tag = hashlib.sha256(rec.get("hash", "").encode()).hexdigest()[:10]  # trocar a senha invalida o link
    payload = f"{normalize(username)}|{int(time.time() + days * 86400)}|{tag}"
    sig = hmac.new(_secret_key(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode().rstrip("=")


def verify_token(token: str | None) -> str | None:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        user, exp, tag, sig = raw.split("|")
        good = hmac.new(_secret_key(), f"{user}|{exp}|{tag}".encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, good) or int(exp) < time.time():
            return None
        rec = (load_json(USERS_KEY, {}) or {}).get(user)
        if not rec or hashlib.sha256(rec["hash"].encode()).hexdigest()[:10] != tag:
            return None
        return user
    except Exception:  # noqa: BLE001
        return None


def storage_problem() -> tuple[str, bool] | None:
    """(mensagem, bloqueia?) se o armazenamento atual não é adequado para guardar contas."""
    from core.storage import backend

    b = backend()
    if "GitHub" in b.name:
        return ("Contas de usuário exigem um banco privado: no modo GitHub os dados (inclusive o hash das senhas) ficam num branch "
                "do repositório, que pode ser público. Configure DATABASE_URL (Supabase).", True)
    if not b.persistent:
        return ("Armazenamento temporário: as contas somem quando o app reinicia. Configure DATABASE_URL (Supabase) nos Secrets.", False)
    return None
