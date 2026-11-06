"""Composition root: monta todos os serviços com injeção de dependências."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pymongo.database import Database
from redis import Redis

from ..core.config import Settings, get_settings
from ..infra.mongo import get_db
from ..infra.neo4j_client import GraphClient, get_graph
from ..infra.redis_client import get_redis
from .auditoria import AuditoriaService
from .auth import AuthService
from .bloqueio import BloqueioProntuario
from .cache import CacheClinico
from .catalogos import CatalogoService
from .eventos import EventoService, NotificacaoService
from .grafo import GrafoService
from .indicadores import IndicadoresService
from .leitos import LeitoService
from .pacientes import PacienteService
from .prontuario import ProntuarioService
from .triagem import TriagemService


@dataclass(frozen=True)
class Servicos:
    settings: Settings
    db: Database
    redis: Redis
    graph: GraphClient
    auditoria: AuditoriaService
    cache: CacheClinico
    eventos: EventoService
    notificacoes: NotificacaoService
    bloqueio: BloqueioProntuario
    auth: AuthService
    catalogos: CatalogoService
    grafo: GrafoService
    pacientes: PacienteService
    prontuario: ProntuarioService
    triagem: TriagemService
    leitos: LeitoService
    indicadores: IndicadoresService


def montar(
    settings: Settings | None = None,
    db: Database | None = None,
    redis: Redis | None = None,
    graph: Any | None = None,
) -> Servicos:
    """Sem argumentos usa os bancos reais; em testes injetam-se mongomock/fakeredis/fake grafo."""
    s = settings or get_settings()
    db = db if db is not None else get_db()
    redis = redis if redis is not None else get_redis()
    graph = graph if graph is not None else get_graph()

    auditoria = AuditoriaService(db)
    cache = CacheClinico(redis)
    eventos = EventoService(redis)
    notificacoes = NotificacaoService(redis)
    bloqueio = BloqueioProntuario(redis, s.lock_ttl)
    grafo = GrafoService(db, graph)
    leitos = LeitoService(db, redis, auditoria, cache, grafo, eventos)
    triagem = TriagemService(db, redis, auditoria, eventos)
    return Servicos(
        settings=s, db=db, redis=redis, graph=graph, auditoria=auditoria, cache=cache,
        eventos=eventos, notificacoes=notificacoes, bloqueio=bloqueio,
        auth=AuthService(db, redis, auditoria, s),
        catalogos=CatalogoService(db, cache, s),
        grafo=grafo,
        pacientes=PacienteService(db, auditoria, cache, grafo, eventos),
        prontuario=ProntuarioService(db, auditoria, cache, grafo, bloqueio, eventos, notificacoes, s),
        triagem=triagem,
        leitos=leitos,
        indicadores=IndicadoresService(db, cache, grafo, leitos, triagem, eventos, s),
    )
