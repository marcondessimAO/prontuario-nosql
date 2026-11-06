"""Indicadores do painel: agregações do MongoDB (cache 30s) + estado vivo do Redis."""
from __future__ import annotations

from datetime import timedelta

from pymongo.database import Database

from ..core import trace
from ..core.config import Settings
from ..core.rbac import Sessao
from ..core.tempo import agora
from .cache import CHAVE_INDICADORES, CacheClinico
from .eventos import EventoService
from .grafo import ERROS_GRAFO, GrafoService
from .leitos import LeitoService
from .triagem import TriagemService

JANELA_DIAS = 30


class IndicadoresService:
    def __init__(
        self, db: Database, cache: CacheClinico, grafo: GrafoService, leitos: LeitoService,
        triagem: TriagemService, eventos: EventoService, settings: Settings,
    ) -> None:
        self._db = db
        self._cache = cache
        self._grafo = grafo
        self._leitos = leitos
        self._triagem = triagem
        self._eventos = eventos
        self._ttl = settings.cache_indicadores_ttl

    def _agregados_mongo(self) -> dict:
        desde = agora() - timedelta(days=JANELA_DIAS)
        na_janela = {"$match": {"data_hora": {"$gte": desde}}}
        trace.registrar("mongo", "AGGREGATE atendimentos", "por dia / CID / especialidade ($lookup)")
        por_dia = self._db.atendimentos.aggregate([
            na_janela,
            {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$data_hora"}}, "total": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ])
        top_cids = self._db.atendimentos.aggregate([
            na_janela, {"$unwind": "$diagnosticos"},
            {"$group": {"_id": {"cid": "$diagnosticos.cid", "descricao": "$diagnosticos.descricao"},
                        "total": {"$sum": 1}}},
            {"$sort": {"total": -1}}, {"$limit": 10},
        ])
        por_especialidade = self._db.atendimentos.aggregate([
            na_janela,
            {"$lookup": {"from": "profissionais", "localField": "profissional_id",
                         "foreignField": "_id", "as": "prof"}},
            {"$unwind": "$prof"},
            {"$group": {"_id": "$prof.especialidade", "total": {"$sum": 1}}},
            {"$sort": {"total": -1}},
        ])
        return {
            "total_pacientes": self._db.pacientes.estimated_document_count(),
            "atendimentos_janela": self._db.atendimentos.count_documents({"data_hora": {"$gte": desde}}),
            "por_dia": [{"dia": r["_id"], "total": r["total"]} for r in por_dia],
            "top_cids": [{"cid": r["_id"]["cid"], "descricao": r["_id"]["descricao"], "total": r["total"]}
                         for r in top_cids],
            "por_especialidade": [{"especialidade": r["_id"], "total": r["total"]} for r in por_especialidade],
        }

    def painel(self, sessao: Sessao) -> dict:
        sessao.exigir("indicadores:ver")
        mongo = self._cache.obter(CHAVE_INDICADORES)
        origem = "redis"
        if mongo is None:
            mongo = self._agregados_mongo()
            self._cache.gravar(CHAVE_INDICADORES, mongo, self._ttl)
            origem = "mongodb"
        try:
            comorbidades = self._grafo.comorbidades(5)
        except ERROS_GRAFO:
            comorbidades = []
        return {
            "mongo": mongo,
            "origem_mongo": origem,
            "janela_dias": JANELA_DIAS,
            # Estado "vivo": nunca cacheado, lido direto do Redis
            "fila": self._triagem.tamanho_fila(),
            "chamados_hoje": self._triagem.chamados_hoje(),
            "ocupacao": self._leitos.ocupacao_por_ala(),
            "cache": self._cache.metricas(),
            "eventos": self._eventos.recentes(10),
            "comorbidades": comorbidades,
        }
