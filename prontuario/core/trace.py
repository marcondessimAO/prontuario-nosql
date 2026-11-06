"""Console poliglota: registro em memória das últimas operações em cada banco.

Serve à demonstração/defesa: mostra, em tempo real, qual banco foi acionado por
cada ação do usuário. Não contém dados de pacientes — apenas descrições técnicas.
Estado por processo (compartilhado entre sessões do Streamlit).
"""
from __future__ import annotations

from collections import deque
from threading import Lock

from .tempo import agora

_EVENTOS: deque[dict] = deque(maxlen=300)
_LOCK = Lock()


def registrar(banco: str, operacao: str, detalhe: str = "") -> None:
    with _LOCK:
        _EVENTOS.appendleft(
            {"hora": agora().strftime("%H:%M:%S"), "banco": banco, "operacao": operacao, "detalhe": detalhe}
        )


def recentes(n: int = 20) -> list[dict]:
    with _LOCK:
        return list(_EVENTOS)[:n]


def limpar() -> None:
    with _LOCK:
        _EVENTOS.clear()
