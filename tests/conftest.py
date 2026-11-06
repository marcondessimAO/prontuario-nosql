"""Fixtures: bancos em memória (mongomock + fakeredis) e um grafo falso injetável."""
from __future__ import annotations

import fakeredis
import mongomock
import pytest
from neo4j.exceptions import ServiceUnavailable

from prontuario.core import trace
from prontuario.core.config import Settings
from prontuario.data.seed_data import build_dataset
from prontuario.services.container import Servicos, montar
from scripts.seed import COLECOES_SEED

SENHA = "Senha12345"


class FakeGraph:
    """Substitui o GraphClient: respostas de leitura programáveis e falha sob demanda."""

    def __init__(self) -> None:
        self.falhar = False
        self.respostas: dict[str, list[dict]] = {}  # trecho da consulta -> linhas
        self.escritas: list[list[tuple[str, dict]]] = []

    def _checar(self) -> None:
        if self.falhar:
            raise ServiceUnavailable("neo4j fora do ar (simulado)")

    def read(self, query: str, **params):
        self._checar()
        for trecho, linhas in self.respostas.items():
            if trecho in query:
                return linhas
        return []

    def write(self, query: str, **params):
        self._checar()
        return []

    def write_many(self, statements):
        self._checar()
        self.escritas.append(statements)

    def ping(self) -> bool:
        return not self.falhar


@pytest.fixture
def settings() -> Settings:
    return Settings(
        mongo_uri="mongomock://", mongo_db="teste", redis_url="fakeredis://", neo4j_uri="bolt://fake",
        neo4j_user="neo4j", neo4j_password="x", neo4j_database="neo4j",
        pbkdf2_iteracoes=1_000, login_max_falhas=5, login_janela_bloqueio=300,
    )


@pytest.fixture
def grafo_falso() -> FakeGraph:
    return FakeGraph()


@pytest.fixture
def sv(settings: Settings, grafo_falso: FakeGraph) -> Servicos:
    trace.limpar()
    db = mongomock.MongoClient(tz_aware=True)["teste"]
    redis = fakeredis.FakeRedis(decode_responses=True)
    servicos = montar(settings, db, redis, grafo_falso)
    db.pacientes.create_index("cpf", unique=True)

    dados = build_dataset(seed=7)
    for colecao in COLECOES_SEED:
        db[colecao].insert_many(dados[colecao])
    for login, nome, perfil, prof in (
        ("dr.carlos", "Dr. Carlos", "medico", "prof-001"),
        ("enf.luciana", "Enf. Luciana", "enfermeiro", "prof-008"),
        ("recepcao", "Recepção", "recepcao", ""),
        ("admin", "Admin", "admin", ""),
    ):
        servicos.auth.criar_usuario(login, nome, perfil, SENHA, prof)
    return servicos


@pytest.fixture
def medico(sv: Servicos):
    return sv.auth.login("dr.carlos", SENHA)


@pytest.fixture
def enfermeiro(sv: Servicos):
    return sv.auth.login("enf.luciana", SENHA)


@pytest.fixture
def recepcao(sv: Servicos):
    return sv.auth.login("recepcao", SENHA)
