"""Chaves de API das corretoras (Binance, Bybit, OKX, Coinbase…) de cada usuário, guardadas criptografadas na conta dela.

* Criptografia Fernet (AES-128-CBC + HMAC) com chave derivada (HKDF) de ``SECRETS_KEY`` — um segredo do dono da plataforma nos
  Secrets, que **não** fica no banco — mais o nome do usuário (cada conta tem uma chave de criptografia diferente). Quem só
  tem acesso ao banco (Supabase) não consegue ler as chaves.
* O que vai para o banco: API Key e Secret cifrados, os 4 últimos caracteres da API Key e o resultado da validação.
  O Secret nunca é exibido de volta nem entra em backup/exportação.
* Uma chave por corretora (a corretora em uso é a escolhida em Minha conta). OKX, KuCoin e Bitget pedem também a *passphrase*.
* Validação: na Binance, assinada com HMAC-SHA256 e recusando chaves com permissão de **saque**; nas demais, pelo ccxt (consulta de
  saldo, que só funciona com uma chave válida).

Hoje as ordens do app são simuladas; a chave fica guardada para quando a execução real for ativada (ver core/broker.py)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

from core.storage import get_secret, load_json, locked_update, save_json

FILE = "credentials.json"
_KEY_RE = re.compile(r"^[A-Za-z0-9]{20,128}$")                     # Binance
_ANY_RE = re.compile(r"^[\x20-\x7e\n\r]{8,4096}$")                 # demais (OKX usa hífens; Coinbase usa chave PEM com várias linhas)
NEEDS_PASSPHRASE = {"okx", "kucoin", "bitget"}
HAS_TESTNET = {"binance", "bybit", "okx", "gate", "bingx"}
REAL_URL = "https://api.binance.com"
TESTNET_URL = "https://testnet.binancefuture.com"


def configured() -> bool:
    """O dono da plataforma definiu SECRETS_KEY? Sem ela não se guarda nenhuma chave."""
    return bool(get_secret("SECRETS_KEY"))


def _fernet(user: str):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    master = get_secret("SECRETS_KEY")
    if not master:
        raise RuntimeError("SECRETS_KEY não está definida nos Secrets: não é possível guardar chaves com segurança.")
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=user.encode(), info=b"tradebot-binance-v1").derive(master.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def _enc(user: str, text: str) -> str:
    return _fernet(user).encrypt(text.encode()).decode()


def _dec(user: str, token: str) -> str:
    return _fernet(user).decrypt(token.encode()).decode()


# ------------------------------------------------------------------------------ validação na Binance
def _signed(api_secret: str, params: dict) -> str:
    qs = urlencode(params)
    return qs + "&signature=" + hmac.new(api_secret.encode(), qs.encode(), hashlib.sha256).hexdigest()


def validate(api_key: str, api_secret: str, testnet: bool = False) -> dict:
    """Confere a chave na Binance. ``ok``: True (válida), False (recusada: inválida ou com permissão de saque) ou None
    (não deu para conferir, ex.: a Binance bloqueia o servidor)."""
    params = {"timestamp": int(time.time() * 1000), "recvWindow": 10000}
    headers = {"X-MBX-APIKEY": api_key}
    url = (TESTNET_URL + "/fapi/v2/account") if testnet else (REAL_URL + "/sapi/v1/account/apiRestrictions")
    try:
        resp = requests.get(url + "?" + _signed(api_secret, params), headers=headers, timeout=10)
    except requests.RequestException as exc:
        return {"ok": None, "message": f"Não foi possível falar com a Binance agora ({type(exc).__name__}).", "perms": {}}
    if resp.status_code in (403, 451):
        return {"ok": None, "message": "A Binance bloqueia a região deste servidor, então a chave não pôde ser conferida.", "perms": {}}
    try:
        data = resp.json()
    except ValueError:
        return {"ok": None, "message": f"Resposta inesperada da Binance (HTTP {resp.status_code}).", "perms": {}}
    if resp.status_code != 200:
        code = data.get("code") if isinstance(data, dict) else None
        msg = {-2014: "API Key em formato inválido.", -2015: "Chave inválida, IP não autorizado ou sem permissão de leitura.",
               -1022: "Assinatura inválida: confira o Secret.", -1021: "Relógio fora de sincronia com a Binance."}.get(code)
        return {"ok": False, "message": msg or f"A Binance recusou a chave ({code}).", "perms": {}}
    if testnet:
        return {"ok": True, "message": "Chave de testes (testnet) válida.", "perms": {"testnet": True}}
    perms = {k: bool(data.get(k)) for k in ("enableReading", "enableSpotAndMarginTrading", "enableFutures", "enableWithdrawals",
                                             "enableInternalTransfer", "ipRestrict")}
    if perms["enableWithdrawals"]:
        return {"ok": False, "perms": perms, "message": "Esta chave tem permissão de SAQUE ligada. Por segurança ela foi recusada: na Binance, "
                "crie outra com só Leitura e Trade (sem Saque)."}
    note = "" if perms["ipRestrict"] else " Dica: restrinja a chave a IPs confiáveis na Binance."
    return {"ok": True, "perms": perms, "message": "Chave válida, sem permissão de saque." + note}


def validate_any(exchange: str, api_key: str, api_secret: str, testnet: bool = False, passphrase: str | None = None) -> dict:
    """Confere a chave na corretora escolhida (Binance pela rota própria; as demais pelo ccxt, consultando o saldo)."""
    if exchange == "binance":
        return validate(api_key, api_secret, testnet)
    try:
        from core import exchanges

        cid = exchanges.EXCHANGES[exchange][1]
        import ccxt

        ex = getattr(ccxt, cid)({"apiKey": api_key, "secret": api_secret, "password": passphrase or None, "timeout": 10000, "enableRateLimit": True})
        if testnet and exchange in HAS_TESTNET:
            ex.set_sandbox_mode(True)
        ex.fetch_balance()
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        if name in ("AuthenticationError", "PermissionDenied", "AccountSuspended"):
            return {"ok": False, "message": f"A corretora recusou a chave ({name}). Confira a API Key, o Secret e a passphrase.", "perms": {}}
        return {"ok": None, "message": f"Não foi possível conferir a chave agora ({name}).", "perms": {}}
    return {"ok": True, "message": "Chave válida. Confira na corretora se ela NÃO tem permissão de saque.", "perms": {}}


# ------------------------------------------------------------------------------ guardar, consultar, remover
def _exchange(exchange: str | None) -> str:
    if exchange:
        return exchange
    from core import exchanges

    return exchanges.selected()


def save(user: str, api_key: str, api_secret: str, testnet: bool, check: dict | None, exchange: str = "binance",
         passphrase: str | None = None) -> dict:
    api_key, api_secret, passphrase = (api_key or "").strip(), (api_secret or "").strip(), (passphrase or "").strip()
    rule = _KEY_RE if exchange == "binance" else _ANY_RE
    if not rule.match(api_key) or not rule.match(api_secret):
        raise ValueError("API Key e Secret parecem incompletos ou com caracteres inválidos. Confira se copiou inteiro, sem espaços sobrando."
                         if exchange != "binance" else
                         "API Key e Secret devem ter só letras e números (de 20 a 128 caracteres). Confira se copiou inteiro, sem espaços.")
    if exchange in NEEDS_PASSPHRASE and not passphrase:
        raise ValueError("Esta corretora pede também a passphrase (a senha que você criou junto com a chave).")
    if check and check.get("ok") is False:
        raise ValueError(check["message"])
    rec = {"api_key": _enc(user, api_key), "api_secret": _enc(user, api_secret), "last4": api_key[-4:], "testnet": bool(testnet),
           "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "validated": None if not check else check.get("ok"), "perms": (check or {}).get("perms", {})}
    if passphrase:
        rec["passphrase"] = _enc(user, passphrase)

    def _apply(data):
        data[exchange] = rec

    locked_update(FILE, {}, _apply)
    return status(user, exchange)


def status(user: str, exchange: str | None = None) -> dict | None:
    """Dados para exibir (nunca a chave nem o Secret) da corretora pedida ou, sem ela, da corretora em uso."""
    rec = (load_json(FILE, {}) or {}).get(_exchange(exchange))
    if not rec:
        return None
    return {k: rec.get(k) for k in ("last4", "testnet", "saved_at", "validated", "perms")}


def all_status(user: str) -> dict:
    """{corretora: status} de todas as chaves guardadas."""
    return {ex: status(user, ex) for ex in (load_json(FILE, {}) or {})}


def get(user: str, exchange: str | None = None) -> tuple[str, str, bool] | None:
    """API Key e Secret em texto puro, só para uso do servidor (execução real, futura). Nunca mostre isto na tela."""
    rec = (load_json(FILE, {}) or {}).get(_exchange(exchange))
    if not rec:
        return None
    return _dec(user, rec["api_key"]), _dec(user, rec["api_secret"]), bool(rec.get("testnet"))


def passphrase(user: str, exchange: str | None = None) -> str | None:
    rec = (load_json(FILE, {}) or {}).get(_exchange(exchange)) or {}
    return _dec(user, rec["passphrase"]) if rec.get("passphrase") else None


def delete(user: str, exchange: str | None = None) -> None:
    ex = _exchange(exchange)

    def _apply(data):
        data.pop(ex, None)

    locked_update(FILE, {}, _apply)
