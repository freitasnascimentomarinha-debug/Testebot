"""Conta de operação: onde as ordens dos bots e as suas são executadas.

* ``simulada`` — conta demo da própria plataforma (paper trading, carteira em USDT). Sempre disponível.
* ``demo``     — conta demo da Exchange (Binance testnet): exige a chave de testes cadastrada em Minha conta.
* ``real``     — conta real da Exchange (Binance): exige a chave real cadastrada (sem permissão de saque).

A escolha é pessoal (fica salva na conta do usuário). A execução de ordens na Exchange ainda não foi ativada nesta versão
(``EXCHANGE_ORDERS_ENABLED``): enquanto isso, nos modos ``demo`` e ``real`` nenhuma ordem é enviada nem simulada — o app avisa
em vez de fingir que operou na Exchange.
"""
from __future__ import annotations

from core import credentials
from core.storage import current_user, load_json, locked_update

MODE_FILE = "account_mode.json"
DEFAULT_MODE = "simulada"
MODES = {
    "simulada": "🧪 Conta demo da plataforma",
    "demo": "🔶 Conta demo da Exchange (Binance testnet)",
    "real": "🔴 Conta real da Exchange (Binance)",
}
SHORT = {"demo": "conta demo da Exchange", "real": "conta real da Exchange"}
EXCHANGE_ORDERS_ENABLED = False


def get_mode() -> str:
    mode = (load_json(MODE_FILE, {}) or {}).get("mode", DEFAULT_MODE)
    return mode if mode in MODES else DEFAULT_MODE


def set_mode(mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"Conta desconhecida: {mode}")

    def _apply(data):
        data["mode"] = mode

    locked_update(MODE_FILE, {}, _apply)


def key_problem(mode: str, user: str | None = None) -> str | None:
    """Por que a conta da Exchange ainda não pode ser usada (None = chave pronta ou conta da plataforma)."""
    if mode == "simulada":
        return None
    user = user or current_user()
    stt = credentials.status(user) if user else None
    if not stt:
        return "Cadastre a chave da Binance em **Minha conta** para usar a conta da Exchange."
    if mode == "demo" and not stt["testnet"]:
        return "A chave cadastrada é da conta real. Para a conta demo da Exchange, cadastre uma chave da conta de testes (testnet)."
    if mode == "real" and stt["testnet"]:
        return "A chave cadastrada é da conta de testes (testnet). Para a conta real, cadastre uma chave da conta real."
    if stt["validated"] is False:
        return "A chave cadastrada foi recusada pela Binance. Cadastre outra em **Minha conta**."
    return None


def orders_problem(mode: str | None = None) -> str | None:
    """Motivo de as ordens não poderem ser enviadas agora (None = pode enviar)."""
    mode = mode or get_mode()
    if mode == "simulada":
        return None
    if (why := key_problem(mode)):
        return why
    if not EXCHANGE_ORDERS_ENABLED:
        return (f"O envio de ordens para a {SHORT[mode]} ainda não está ativo nesta versão: nenhuma ordem é enviada. "
                "Volte para a conta demo da plataforma para operar.")
    return None


def orders_enabled() -> bool:
    return orders_problem() is None
