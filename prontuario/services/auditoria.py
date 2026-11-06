"""Trilha de auditoria (LGPD art. 37 / CFM 1.821): quem acessou o quê e quando.

Política "fail closed": se a gravação da auditoria falhar, a operação NÃO prossegue
(a exceção propaga). Os registros são append-only — não há método de update/delete.
"""
from __future__ import annotations

from typing import Any

from pymongo.database import Database

from ..core import trace
from ..core.tempo import agora


class AuditoriaService:
    def __init__(self, db: Database) -> None:
        self._col = db["auditoria"]

    def registrar(
        self,
        *,
        usuario: str,
        perfil: str,
        acao: str,
        recurso: str,
        recurso_id: str | None = None,
        paciente_id: str | None = None,
        detalhes: dict[str, Any] | None = None,
    ) -> None:
        self._col.insert_one({
            "usuario": usuario,
            "perfil": perfil,
            "acao": acao,
            "recurso": recurso,
            "recurso_id": recurso_id,
            "paciente_id": paciente_id,
            "detalhes": detalhes or {},
            "data_hora": agora(),
        })
        trace.registrar("mongo", "INSERT auditoria", acao)

    def listar(
        self,
        *,
        paciente_id: str | None = None,
        usuario: str | None = None,
        acao: str | None = None,
        limite: int = 200,
    ) -> list[dict]:
        filtro = {
            k: v for k, v in
            {"paciente_id": paciente_id, "usuario": usuario, "acao": acao}.items() if v
        }
        trace.registrar("mongo", "FIND auditoria", str(filtro))
        return list(self._col.find(filtro).sort("data_hora", -1).limit(limite))

    def contagem_por_acao(self) -> list[dict]:
        pipeline = [
            {"$group": {"_id": "$acao", "total": {"$sum": 1}}},
            {"$sort": {"total": -1}},
        ]
        return [{"acao": r["_id"], "total": r["total"]} for r in self._col.aggregate(pipeline)]
