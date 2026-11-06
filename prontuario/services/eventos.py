"""Eventos clínicos em Redis Streams e notificações por profissional.

Os eventos NÃO carregam dados pessoais: apenas tipo e identificadores técnicos.
"""
from __future__ import annotations

import json

from redis import Redis

from ..core import trace
from ..core.tempo import agora

STREAM = "eventos:clinicos"
STREAM_TAMANHO_MAX = 1000
NOTIF_MAX = 50


class EventoService:
    def __init__(self, redis: Redis) -> None:
        self._r = redis

    def publicar(self, evento: str, /, **campos: object) -> None:
        # `evento` é só-posicional: assim um campo chamado "tipo" não colide com ele
        corpo = {"evento": evento, "ts": agora().isoformat(timespec="seconds")}
        corpo.update({k: str(v) for k, v in campos.items()})
        self._r.xadd(STREAM, corpo, maxlen=STREAM_TAMANHO_MAX, approximate=True)
        trace.registrar("redis", "XADD", f"{STREAM} {evento}")

    def recentes(self, n: int = 15) -> list[dict]:
        return [{"id": i, **campos} for i, campos in self._r.xrevrange(STREAM, count=n)]


class NotificacaoService:
    def __init__(self, redis: Redis) -> None:
        self._r = redis

    @staticmethod
    def _k_lista(prof_id: str) -> str:
        return f"notif:lista:{prof_id}"

    @staticmethod
    def _k_contador(prof_id: str) -> str:
        return f"notif:nao_lidas:{prof_id}"

    def enviar(self, profissional_id: str, titulo: str, corpo: str) -> None:
        if not profissional_id:
            return
        item = json.dumps({"titulo": titulo, "corpo": corpo, "ts": agora().isoformat(timespec="seconds")})
        pipe = self._r.pipeline()
        pipe.lpush(self._k_lista(profissional_id), item)
        pipe.ltrim(self._k_lista(profissional_id), 0, NOTIF_MAX - 1)
        pipe.incr(self._k_contador(profissional_id))
        pipe.execute()
        trace.registrar("redis", "LPUSH+INCR", f"notificação p/ {profissional_id}")

    def nao_lidas(self, profissional_id: str) -> int:
        if not profissional_id:
            return 0
        return int(self._r.get(self._k_contador(profissional_id)) or 0)

    def listar(self, profissional_id: str, limite: int = 20) -> list[dict]:
        if not profissional_id:
            return []
        return [json.loads(x) for x in self._r.lrange(self._k_lista(profissional_id), 0, limite - 1)]

    def marcar_lidas(self, profissional_id: str) -> None:
        if profissional_id:
            self._r.set(self._k_contador(profissional_id), 0)
