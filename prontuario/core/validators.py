"""Validações e normalizações de dados de entrada (fronteira do sistema)."""
from __future__ import annotations

import re
import unicodedata


def somente_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def _digito_cpf(digitos: str) -> int:
    peso = len(digitos) + 1
    soma = sum(int(d) * (peso - i) for i, d in enumerate(digitos))
    resto = (soma * 10) % 11
    return 0 if resto == 10 else resto


def calcular_dv_cpf(base9: str) -> str:
    """Retorna os 2 dígitos verificadores de uma base de 9 dígitos."""
    d1 = _digito_cpf(base9)
    d2 = _digito_cpf(base9 + str(d1))
    return f"{d1}{d2}"


def cpf_valido(cpf: str) -> bool:
    d = somente_digitos(cpf)
    if len(d) != 11 or len(set(d)) == 1:
        return False
    return d[9:] == calcular_dv_cpf(d[:9])


def formatar_cpf(cpf: str) -> str:
    d = somente_digitos(cpf)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else cpf


def mascarar_cpf(cpf: str) -> str:
    """Exibe apenas o miolo: ***.456.789-** (minimização de dados — LGPD)."""
    d = somente_digitos(cpf)
    return f"***.{d[3:6]}.{d[6:9]}-**" if len(d) == 11 else "***"


def normalizar_texto(texto: str) -> str:
    """minúsculas e sem acentos, para busca por prefixo indexada."""
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sem_acento).strip().lower()
