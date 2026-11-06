"""Cache-aside sobre Redis, com métricas de hit/miss e invalidação explícita."""
from __future__ import annotations

import json
from typing import Any

from redis import Redis

from ..core import trace
from ..core.serialization import para_json

CHAVE_HITS = "stats:cache:hit"
CHAVE_MISSES = "stats:cache:miss"
CHAVE_INDICADORES = "cache:indicadores"


def chave_prontuario(paciente_id: str) -> str:
    return f"cache:prontuario:{paciente_id}"


class CacheClinico:
    def __init__(self, redis: Redis) -> None:
        self._r = redis

    def obter(self, chave: str) -> Any | None:
        bruto = self._r.get(chave)
        if bruto is None:
            self._r.incr(CHAVE_MISSES)
            trace.registrar("redis", "GET (miss)", chave)
            return None
        self._r.incr(CHAVE_HITS)
        trace.registrar("redis", "GET (hit)", chave)
        return json.loads(bruto)

    def gravar(self, chave: str, valor: Any, ttl: int) -> None:
        self._r.setex(chave, ttl, para_json(valor))
        trace.registrar("redis", f"SETEX {ttl}s", chave)

    def invalidar(self, *chaves: str) -> None:
        if chaves:
            self._r.delete(*chaves)
            trace.registrar("redis", "DEL (invalidação)", ", ".join(chaves))

    def invalidar_paciente(self, paciente_id: str) -> None:
        """Toda escrita clínica derruba o resumo do paciente e os indicadores agregados."""
        self.invalidar(chave_prontuario(paciente_id), CHAVE_INDICADORES)

    def metricas(self) -> dict[str, float]:
        hits = int(self._r.get(CHAVE_HITS) or 0)
        misses = int(self._r.get(CHAVE_MISSES) or 0)
        total = hits + misses
        return {"hits": hits, "misses": misses, "taxa_acerto": (hits / total) if total else 0.0}
