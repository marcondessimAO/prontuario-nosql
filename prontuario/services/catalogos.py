"""Catálogos de leitura intensiva (medicamentos, CID-10, profissionais, leitos).

Dados de referência quase estáticos: ideais para cache Redis com TTL longo.
"""
from __future__ import annotations

from pymongo.database import Database

from ..core import trace
from ..core.config import Settings
from .cache import CacheClinico

_PROJECOES = {
    "medicamentos": {"nome": 1, "classe": 1, "controlado": 1, "posologia_padrao": 1},
    "cid10": {"descricao": 1},
    "profissionais": {"nome": 1, "especialidade": 1, "registro": 1},
    "leitos": {"ala": 1, "tipo": 1},
}
_ORDENACAO = {"medicamentos": "nome", "cid10": "_id", "profissionais": "nome", "leitos": "_id"}


class CatalogoService:
    def __init__(self, db: Database, cache: CacheClinico, settings: Settings) -> None:
        self._db = db
        self._cache = cache
        self._ttl = settings.cache_catalogo_ttl

    def _listar(self, colecao: str) -> list[dict]:
        chave = f"cache:catalogo:{colecao}"
        em_cache = self._cache.obter(chave)
        if em_cache is not None:
            return em_cache
        trace.registrar("mongo", f"FIND {colecao}", "catálogo (cache miss)")
        itens = list(self._db[colecao].find({}, _PROJECOES[colecao]).sort(_ORDENACAO[colecao], 1))
        self._cache.gravar(chave, itens, self._ttl)
        return itens

    def medicamentos(self) -> list[dict]:
        return self._listar("medicamentos")

    def cids(self) -> list[dict]:
        return self._listar("cid10")

    def profissionais(self) -> list[dict]:
        return self._listar("profissionais")

    def leitos(self) -> list[dict]:
        return self._listar("leitos")
