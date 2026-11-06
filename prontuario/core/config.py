"""Configuração central lida de variáveis de ambiente (12-factor).

Nenhum segredo é fixado em código: tudo vem do ambiente / arquivo .env.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import quote_plus

try:  # python-dotenv é opcional dentro do container (variáveis já vêm do compose)
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


def _int(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, padrao))
    except ValueError:
        return padrao


def _bool(nome: str, padrao: bool) -> bool:
    return os.getenv(nome, str(padrao)).strip().lower() in {"1", "true", "yes", "sim"}


def _mongo_uri() -> str:
    uri = os.getenv("MONGO_URI")
    if uri:
        return uri
    host = os.getenv("MONGO_HOST", "localhost")
    porta = os.getenv("MONGO_PORT", "27017")
    usuario = os.getenv("MONGO_USER")
    senha = os.getenv("MONGO_PASSWORD")
    if usuario and senha:
        return f"mongodb://{quote_plus(usuario)}:{quote_plus(senha)}@{host}:{porta}/?authSource=admin"
    return f"mongodb://{host}:{porta}"


def _redis_url() -> str:
    url = os.getenv("REDIS_URL")
    if url:
        return url
    host = os.getenv("REDIS_HOST", "localhost")
    porta = os.getenv("REDIS_PORT", "6379")
    senha = os.getenv("REDIS_PASSWORD")
    auth = f":{quote_plus(senha)}@" if senha else ""
    return f"redis://{auth}{host}:{porta}/0"


@dataclass(frozen=True)
class Settings:
    mongo_uri: str
    mongo_db: str
    redis_url: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    neo4j_database: str
    # Sessão e autenticação
    session_ttl: int = 1800
    login_max_falhas: int = 5
    login_janela_bloqueio: int = 300
    pbkdf2_iteracoes: int = 600_000
    # Cache (Redis)
    cache_prontuario_ttl: int = 120
    cache_indicadores_ttl: int = 30
    cache_catalogo_ttl: int = 3600
    # Bloqueio de edição do prontuário
    lock_ttl: int = 120
    demo_mode: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        mongo_uri=_mongo_uri(),
        mongo_db=os.getenv("MONGO_DB", "prontuario"),
        redis_url=_redis_url(),
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USERNAME", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", ""),
        neo4j_database=os.getenv("NEO4J_DATABASE", "neo4j"),
        session_ttl=_int("SESSION_TTL_SECONDS", 1800),
        demo_mode=_bool("DEMO_MODE", True),
    )
