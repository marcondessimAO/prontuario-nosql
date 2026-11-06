"""Bloqueio pessimista de edição do prontuário (lock distribuído em Redis).

Evita que dois profissionais registrem atendimento no mesmo prontuário ao mesmo
tempo. `SET NX EX` é atômico; liberar/renovar usam Lua para o padrão
"compare-and-delete" (só o dono mexe no lock). O TTL impede lock órfão se o
navegador fechar.
"""
from __future__ import annotations

from redis import Redis

from ..core import trace
from ..core.errors import ConflitoErro

_LUA_LIBERAR = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end
"""
_LUA_RENOVAR = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end
"""


def _chave(paciente_id: str) -> str:
    return f"lock:prontuario:{paciente_id}"


class BloqueioProntuario:
    def __init__(self, redis: Redis, ttl: int) -> None:
        self._r = redis
        self._ttl = ttl
        self._liberar = redis.register_script(_LUA_LIBERAR)
        self._renovar = redis.register_script(_LUA_RENOVAR)

    def adquirir(self, paciente_id: str, login: str) -> bool:
        """True se o lock é (ou já era) do usuário; False se outro usuário o detém."""
        if self._r.set(_chave(paciente_id), login, nx=True, ex=self._ttl):
            trace.registrar("redis", "SET NX EX", f"lock prontuário {paciente_id}")
            return True
        return self.renovar(paciente_id, login)

    def dono(self, paciente_id: str) -> str | None:
        return self._r.get(_chave(paciente_id))

    def renovar(self, paciente_id: str, login: str) -> bool:
        return bool(self._renovar(keys=[_chave(paciente_id)], args=[login, self._ttl]))

    def liberar(self, paciente_id: str, login: str) -> bool:
        liberado = bool(self._liberar(keys=[_chave(paciente_id)], args=[login]))
        if liberado:
            trace.registrar("redis", "DEL (lock)", f"liberado {paciente_id}")
        return liberado

    def exigir_posse(self, paciente_id: str, login: str) -> None:
        dono = self.dono(paciente_id)
        if dono is None:
            raise ConflitoErro("O prontuário não está bloqueado para edição. Inicie o atendimento novamente.")
        if dono != login:
            raise ConflitoErro(f"Prontuário em edição por '{dono}'. Tente novamente em instantes.")
