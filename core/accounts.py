"""Contas de usuário (cadastro com aprovação, login, papéis e administração), sem dependência do Streamlit.

Ligue com ``AUTH_MODE = "contas"`` (ou apenas defina ``DATABASE_URL`` sem ``APP_PASSWORD``). Os usuários ficam na chave
``_users.json`` do armazenamento (Supabase/Postgres): só o *hash* da senha é guardado (scrypt com sal aleatório).

Fluxo: a pessoa pede a conta → fica **pendente** → um **admin** autoriza (ou recusa) no painel → só então ela entra.
Admins podem bloquear, reativar, excluir (com os dados), redefinir senha e promover outras contas a admin.

Secrets:
* ``ADMIN_USER`` + ``ADMIN_PASSWORD`` — admin principal, definido só nos Secrets (não existe cadastro desse nome, não pode ser
  bloqueado nem excluído pelo painel);
* ``SIGNUP_CODE``  — código de convite opcional no pedido de conta (filtra pedidos de estranhos);
* ``ALLOW_SIGNUP`` — ``false`` fecha os pedidos de conta novos;
* ``AUTH_SECRET``  — chave que assina o link de "manter conectado" (se faltar, é derivada de DATABASE_URL);
* ``LEGACY_OWNER`` — usuário que herda os dados anteriores às contas (ver core/storage.py);
* ``AUTH_MODE = "aberto"`` — desliga as contas mesmo com DATABASE_URL (uso sem login)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import time
from datetime import datetime, timezone

from core.storage import USERS_KEY, delete_user_data, get_secret, load_json, locked_update

MAX_FAILS = 5
LOCK_SECONDS = 300
TOKEN_DAYS = 14
MAX_PENDING = 100
_USER_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,19}$")
_WEAK = {"12345678", "123456789", "1234567890", "password", "senha123", "qwertyui", "11111111", "abc12345", "senhasenha"}
_N, _R, _P = 2 ** 14, 8, 1
PENDING, ACTIVE, BLOCKED = "pendente", "ativo", "bloqueado"


def enabled() -> bool:
    mode = (get_secret("AUTH_MODE") or "").strip().lower()
    if mode in ("contas", "accounts", "usuarios"):
        return True
    if mode in ("aberto", "open", "off", "senha"):
        return False
    # Sem AUTH_MODE: ter um banco (Supabase) e nenhuma senha única já indica o modo contas — evita deixar o app aberto por esquecimento.
    return bool(get_secret("DATABASE_URL")) and not get_secret("APP_PASSWORD")


def signup_open() -> bool:
    return (get_secret("ALLOW_SIGNUP") or "true").strip().lower() not in ("false", "0", "nao", "não", "no")


def needs_code() -> bool:
    return bool(get_secret("SIGNUP_CODE"))


def normalize(username: str) -> str:
    return (username or "").strip().lower()


def admin_user() -> str:
    return normalize(get_secret("ADMIN_USER") or "")


def is_primary_admin(user: str) -> bool:
    return bool(user) and normalize(user) == admin_user() and bool(get_secret("ADMIN_PASSWORD"))


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


def check_password_strength(password: str) -> str | None:
    if len(password) < 8:
        return "A senha precisa ter pelo menos 8 caracteres."
    if password.lower() in _WEAK or len(set(password)) < 4:
        return "Senha fraca demais: evite sequências e repetições."
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _users() -> dict:
    return load_json(USERS_KEY, {}) or {}


def _status(rec: dict | None) -> str:
    return (rec or {}).get("status") or ACTIVE  # contas antigas, sem o campo, continuam ativas


# ------------------------------------------------------------------------------ pedido de conta e login
def register(username: str, password: str, code: str | None = None, note: str = "") -> str:
    """Registra o PEDIDO de conta (fica pendente até um admin autorizar). Levanta ``ValueError`` com a mensagem ao usuário."""
    if not signup_open():
        raise ValueError("Os pedidos de conta nova estão fechados.")
    if needs_code() and not hmac.compare_digest((code or "").strip().encode(), get_secret("SIGNUP_CODE").encode()):
        raise ValueError("Código de convite incorreto.")
    user = normalize(username)
    if not _USER_RE.match(user):
        raise ValueError("Usuário: de 3 a 20 caracteres, só letras minúsculas, números, ponto, hífen e sublinhado.")
    if user == admin_user():
        raise ValueError("Este nome é reservado. Escolha outro.")
    if (msg := check_password_strength(password)):
        raise ValueError(msg)
    pw = hash_password(password)
    note = (note or "").strip()[:200]

    def _apply(users: dict):
        if user in users:
            raise ValueError("Este usuário já existe. Escolha outro.")
        if sum(1 for r in users.values() if _status(r) == PENDING) >= MAX_PENDING:
            raise ValueError("Há pedidos demais aguardando autorização. Tente mais tarde.")
        users[user] = {"hash": pw, "created": _now(), "fails": 0, "locked_until": 0, "status": PENDING, "role": "user", "note": note}

    locked_update(USERS_KEY, {}, _apply)
    return user


def authenticate(username: str, password: str) -> str:
    """Confere usuário e senha (com bloqueio por tentativas erradas) e se a conta está autorizada.
    Devolve o usuário ou levanta ``ValueError``."""
    user = normalize(username)
    rec = _users().get(user)
    if rec and rec.get("locked_until", 0) > time.time():
        raise ValueError(f"Conta bloqueada por tentativas erradas. Tente de novo em {int((rec['locked_until'] - time.time()) // 60) + 1} min.")
    if is_primary_admin(user):
        ok = hmac.compare_digest(password.encode(), get_secret("ADMIN_PASSWORD").encode())
        known = True
    else:
        ok = verify_password(password, rec["hash"] if rec else _DUMMY)  # sempre calcula: não revela se o usuário existe
        known = bool(rec)
    if not (known and ok):
        if known:
            def _fail(us: dict):
                r = us.setdefault(user, {"hash": "", "created": _now(), "status": ACTIVE, "role": "admin", "primary": True})
                r["fails"] = r.get("fails", 0) + 1
                if r["fails"] >= MAX_FAILS:
                    r["fails"], r["locked_until"] = 0, time.time() + LOCK_SECONDS

            if rec or is_primary_admin(user):
                locked_update(USERS_KEY, {}, _fail)
        raise ValueError("Usuário ou senha incorretos.")
    status = ACTIVE if is_primary_admin(user) else _status(rec)
    if status == PENDING:
        raise ValueError("Sua conta ainda não foi autorizada pelo administrador. Você poderá entrar assim que ela for liberada.")
    if status == BLOCKED:
        raise ValueError("O seu acesso foi bloqueado pelo administrador.")

    def _ok(us: dict):
        r = us.setdefault(user, {"hash": "", "created": _now(), "status": ACTIVE, "role": "admin", "primary": True})
        r["fails"], r["last_login"] = 0, _now()
        if is_primary_admin(user):
            r.update(status=ACTIVE, role="admin", primary=True)

    locked_update(USERS_KEY, {}, _ok)
    return user


def is_active(user: str | None) -> bool:
    if not user:
        return False
    if is_primary_admin(user):
        return True
    rec = _users().get(normalize(user))
    return bool(rec) and _status(rec) == ACTIVE


def is_admin(user: str | None) -> bool:
    if not user:
        return False
    if is_primary_admin(user):
        return True
    rec = _users().get(normalize(user))
    return bool(rec) and _status(rec) == ACTIVE and rec.get("role") == "admin"


def change_password(username: str, old: str, new: str) -> None:
    user = authenticate(username, old)
    if is_primary_admin(user):
        raise ValueError("A senha do admin principal é definida nos Secrets (ADMIN_PASSWORD).")
    if (msg := check_password_strength(new)):
        raise ValueError(msg)
    pw = hash_password(new)

    def _apply(users: dict):
        users[user]["hash"] = pw

    locked_update(USERS_KEY, {}, _apply)


def info(username: str) -> dict | None:
    rec = _users().get(normalize(username))
    return {"created": rec["created"], "role": "admin" if is_admin(username) else "user"} if rec else None


def list_users() -> list[str]:
    """Contas ativas (usadas pelo worker.py)."""
    names = {u for u, r in _users().items() if _status(r) == ACTIVE and (r.get("hash") or r.get("primary"))}
    if admin_user() and is_primary_admin(admin_user()):
        names.add(admin_user())
    return sorted(names)


# ------------------------------------------------------------------------------ administração
def list_accounts() -> list[dict]:
    rows = []
    for u, r in _users().items():
        rows.append({"usuario": u, "estado": _status(r), "papel": "admin" if (r.get("role") == "admin") else "usuário",
                     "principal": bool(r.get("primary")) or is_primary_admin(u), "criado": r.get("created", ""),
                     "ultimo_acesso": r.get("last_login", ""), "nota": r.get("note", "")})
    if is_primary_admin(admin_user()) and admin_user() not in {r["usuario"] for r in rows}:
        rows.append({"usuario": admin_user(), "estado": ACTIVE, "papel": "admin", "principal": True, "criado": "", "ultimo_acesso": "", "nota": ""})
    order = {PENDING: 0, ACTIVE: 1, BLOCKED: 2}
    return sorted(rows, key=lambda r: (order.get(r["estado"], 3), r["criado"]))


def pending_count() -> int:
    return sum(1 for r in _users().values() if _status(r) == PENDING)


def _require_admin(admin: str) -> None:
    if not is_admin(admin):
        raise PermissionError("Só administradores podem fazer isso.")


def _target(admin: str, user: str, *, allow_self: bool = False) -> str:
    _require_admin(admin)
    user = normalize(user)
    if is_primary_admin(user):
        raise ValueError("O admin principal é definido nos Secrets e não pode ser alterado aqui.")
    if user == normalize(admin) and not allow_self:
        raise ValueError("Você não pode fazer isso na sua própria conta.")
    if user not in _users():
        raise ValueError("Usuário não encontrado.")
    return user


def _set(user: str, **fields) -> None:
    def _apply(users: dict):
        users[user].update(fields)

    locked_update(USERS_KEY, {}, _apply)


def approve(admin: str, user: str) -> None:
    _set(_target(admin, user), status=ACTIVE, approved_by=normalize(admin), approved_at=_now())


def block(admin: str, user: str) -> None:
    _set(_target(admin, user), status=BLOCKED)


def unblock(admin: str, user: str) -> None:
    _set(_target(admin, user), status=ACTIVE, fails=0, locked_until=0)


def set_admin(admin: str, user: str, flag: bool) -> None:
    _set(_target(admin, user), role="admin" if flag else "user")


def reset_password(admin: str, user: str, new_password: str) -> None:
    target = _target(admin, user, allow_self=True)
    if (msg := check_password_strength(new_password)):
        raise ValueError(msg)
    _set(target, hash=hash_password(new_password), fails=0, locked_until=0)


def delete(admin: str, user: str, wipe_data: bool = True) -> int:
    """Exclui a conta (e, por padrão, todos os dados dela). Devolve quantos arquivos de dados foram apagados."""
    target = _target(admin, user)

    def _apply(users: dict):
        users.pop(target, None)

    locked_update(USERS_KEY, {}, _apply)
    return delete_user_data(target) if wipe_data else 0


# ------------------------------------------------------------------------------ "manter conectado"
def _secret_key() -> bytes:
    return (get_secret("AUTH_SECRET") or hashlib.sha256((get_secret("DATABASE_URL") or "tradebot-local").encode()).hexdigest()).encode()


def _pw_tag(user: str, rec: dict | None) -> str:
    base = get_secret("ADMIN_PASSWORD") if is_primary_admin(user) else (rec or {}).get("hash", "")
    return hashlib.sha256((base or "").encode()).hexdigest()[:10]  # trocar a senha invalida o link


def make_token(username: str, days: int = TOKEN_DAYS) -> str:
    user = normalize(username)
    payload = f"{user}|{int(time.time() + days * 86400)}|{_pw_tag(user, _users().get(user))}"
    sig = hmac.new(_secret_key(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode().rstrip("=")


def verify_token(token: str | None) -> str | None:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        user, exp, tag, sig = raw.split("|")
        good = hmac.new(_secret_key(), f"{user}|{exp}|{tag}".encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, good) or int(exp) < time.time():
            return None
        rec = _users().get(user)
        if (not rec and not is_primary_admin(user)) or _pw_tag(user, rec) != tag or not is_active(user):
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
