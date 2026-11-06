"""Controle de acesso baseado em perfis (RBAC) — princípio do menor privilégio."""
from __future__ import annotations

from dataclasses import dataclass

from .errors import PermissaoNegada

PERFIS = ("medico", "enfermeiro", "recepcao", "admin")

PERMISSOES: dict[str, frozenset[str]] = {
    "medico": frozenset({
        "paciente:ver", "paciente:cpf", "prontuario:ler", "prontuario:escrever",
        "prontuario:adendo", "prescricao:criar", "triagem:ver", "leito:ver",
        "grafo:consultar", "indicadores:ver",
    }),
    "enfermeiro": frozenset({
        "paciente:ver", "paciente:cpf", "prontuario:ler", "prontuario:escrever",
        "prontuario:adendo", "triagem:ver", "triagem:operar", "leito:ver",
        "leito:operar", "grafo:consultar", "indicadores:ver",
    }),
    "recepcao": frozenset({
        "paciente:ver", "paciente:cadastrar", "triagem:ver", "triagem:operar",
    }),
    "admin": frozenset({
        "paciente:ver", "triagem:ver", "leito:ver", "grafo:consultar",
        "indicadores:ver", "auditoria:ler", "sistema:administrar",
    }),
}


@dataclass(frozen=True)
class Sessao:
    """Identidade autenticada, reconstruída do Redis a cada requisição."""

    token: str
    login: str
    nome: str
    perfil: str
    profissional_id: str = ""

    def pode(self, permissao: str) -> bool:
        return permissao in PERMISSOES.get(self.perfil, frozenset())

    def exigir(self, permissao: str) -> None:
        if not self.pode(permissao):
            raise PermissaoNegada(
                f"O perfil '{self.perfil}' não tem permissão para esta operação ({permissao})."
            )
