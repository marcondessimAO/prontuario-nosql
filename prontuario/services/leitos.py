"""Leitos e internações.

Estado em tempo real no Redis (ocupação), histórico no MongoDB (internações) e
relações de contato no Neo4j. Fluxo de `internar`:
  1. HSETNX no Redis reserva o leito atomicamente (impede dupla ocupação);
  2. insert no MongoDB — índices únicos parciais garantem 1 internação ativa por
     paciente e por leito; se falhar, a reserva do Redis é desfeita;
  3. projeção no Neo4j (consistência eventual).
O estado do Redis é DERIVADO: `reconstruir_estado()` o recria a partir do MongoDB.
"""
from __future__ import annotations

from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from redis import Redis

from ..core import trace
from ..core.errors import ConflitoErro, NaoEncontrado
from ..core.rbac import Sessao
from ..core.tempo import agora
from .auditoria import AuditoriaService
from .cache import CHAVE_INDICADORES, CacheClinico
from .eventos import EventoService
from .grafo import GrafoService

OCUPANTES = "leitos:ocupantes"  # hash: leito_id -> paciente_id


def _chave_ala(ala: str) -> str:
    return f"leitos:ocupados:{ala}"


class LeitoService:
    def __init__(
        self, db: Database, redis: Redis, auditoria: AuditoriaService, cache: CacheClinico,
        grafo: GrafoService, eventos: EventoService,
    ) -> None:
        self._db = db
        self._r = redis
        self._audit = auditoria
        self._cache = cache
        self._grafo = grafo
        self._eventos = eventos

    # ---------------- leitura ---------------- #
    def estado(self) -> list[dict]:
        ocupantes = self._r.hgetall(OCUPANTES)
        trace.registrar("redis", "HGETALL", OCUPANTES)
        nomes = {
            p["_id"]: p["nome"]
            for p in self._db.pacientes.find({"_id": {"$in": list(ocupantes.values())}}, {"nome": 1})
        }
        return [
            {
                "leito": l["_id"], "ala": l["ala"], "tipo": l.get("tipo", ""),
                "ocupado": l["_id"] in ocupantes,
                "paciente_id": ocupantes.get(l["_id"], ""),
                "paciente": nomes.get(ocupantes.get(l["_id"], ""), ""),
            }
            for l in self._db.leitos.find().sort("_id", 1)
        ]

    def ocupacao_por_ala(self) -> list[dict]:
        totais = self._db.leitos.aggregate([{"$group": {"_id": "$ala", "total": {"$sum": 1}}}, {"$sort": {"_id": 1}}])
        resultado = []
        for t in totais:
            ocupados = int(self._r.scard(_chave_ala(t["_id"])))
            resultado.append({
                "ala": t["_id"], "total": t["total"], "ocupados": ocupados,
                "livres": t["total"] - ocupados, "taxa": round(100 * ocupados / t["total"], 1),
            })
        return resultado

    def internacoes_ativas(self) -> list[dict]:
        ativas = list(self._db.internacoes.find({"ativa": True}).sort("entrada", 1))
        nomes = {
            p["_id"]: p["nome"]
            for p in self._db.pacientes.find({"_id": {"$in": [i["paciente_id"] for i in ativas]}}, {"nome": 1})
        }
        return [{**i, "paciente": nomes.get(i["paciente_id"], i["paciente_id"])} for i in ativas]

    # ---------------- escrita ---------------- #
    def internar(self, sessao: Sessao, paciente_id: str, leito_id: str, motivo: str) -> str:
        sessao.exigir("leito:operar")
        leito = self._db.leitos.find_one({"_id": leito_id})
        if not leito:
            raise NaoEncontrado("Leito não encontrado.")
        if not self._db.pacientes.count_documents({"_id": paciente_id}, limit=1):
            raise NaoEncontrado("Paciente não encontrado.")

        if not self._r.hsetnx(OCUPANTES, leito_id, paciente_id):
            raise ConflitoErro(f"O leito {leito_id} acabou de ser ocupado por outro atendimento.")
        trace.registrar("redis", "HSETNX", f"{OCUPANTES} {leito_id} (reserva atômica)")

        documento = {
            "_id": f"int-{uuid4().hex[:8]}", "paciente_id": paciente_id, "leito_id": leito_id,
            "ala": leito["ala"], "entrada": agora(), "saida": None, "ativa": True,
            "motivo": (motivo or "").strip(), "registrado_por": sessao.login, "sync_grafo": False,
        }
        try:
            self._db.internacoes.insert_one(documento)
        except DuplicateKeyError as exc:
            self._r.hdel(OCUPANTES, leito_id)  # compensação: desfaz a reserva
            raise ConflitoErro("Paciente já possui internação ativa (ou o leito já está em uso).") from exc
        except Exception:
            self._r.hdel(OCUPANTES, leito_id)
            raise
        trace.registrar("mongo", "INSERT internacoes", documento["_id"])

        self._r.sadd(_chave_ala(leito["ala"]), leito_id)
        self._grafo.sincronizar_internacao(documento)
        self._cache.invalidar(CHAVE_INDICADORES)
        self._eventos.publicar("internacao", leito=leito_id, ala=leito["ala"])
        self._audit.registrar(
            usuario=sessao.login, perfil=sessao.perfil, acao="leito:internar", recurso="internacao",
            recurso_id=documento["_id"], paciente_id=paciente_id, detalhes={"leito": leito_id},
        )
        return documento["_id"]

    def dar_alta(self, sessao: Sessao, paciente_id: str) -> None:
        sessao.exigir("leito:operar")
        encerrada = self._db.internacoes.find_one_and_update(
            {"paciente_id": paciente_id, "ativa": True},
            {"$set": {"ativa": False, "saida": agora(), "sync_grafo": False}},
            return_document=ReturnDocument.AFTER,
        )
        if not encerrada:
            raise NaoEncontrado("Paciente não possui internação ativa.")
        trace.registrar("mongo", "UPDATE internacoes", f"{encerrada['_id']} alta")
        pipe = self._r.pipeline()
        pipe.hdel(OCUPANTES, encerrada["leito_id"])
        pipe.srem(_chave_ala(encerrada["ala"]), encerrada["leito_id"])
        pipe.execute()
        trace.registrar("redis", "HDEL+SREM", f"leito {encerrada['leito_id']} liberado")
        self._grafo.sincronizar_internacao(encerrada)
        self._cache.invalidar(CHAVE_INDICADORES)
        self._eventos.publicar("alta", leito=encerrada["leito_id"])
        self._audit.registrar(
            usuario=sessao.login, perfil=sessao.perfil, acao="leito:alta", recurso="internacao",
            recurso_id=encerrada["_id"], paciente_id=paciente_id,
        )

    def reconstruir_estado(self) -> int:
        """Recria a ocupação no Redis a partir das internações ativas do MongoDB."""
        chaves = [OCUPANTES] + [_chave_ala(a) for a in self._db.leitos.distinct("ala")]
        self._r.delete(*chaves)
        ativas = list(self._db.internacoes.find({"ativa": True}))
        pipe = self._r.pipeline()
        for i in ativas:
            pipe.hset(OCUPANTES, i["leito_id"], i["paciente_id"])
            pipe.sadd(_chave_ala(i["ala"]), i["leito_id"])
        pipe.execute()
        return len(ativas)
