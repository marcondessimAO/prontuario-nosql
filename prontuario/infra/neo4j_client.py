"""Neo4j: wrapper fino sobre o driver oficial + constraints/índices do grafo clínico."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from neo4j import Driver, GraphDatabase, RoutingControl

from ..core import trace
from ..core.config import Settings, get_settings


def _nativo(valor: Any) -> Any:
    """Converte tipos temporais do Neo4j (neo4j.time.*) em tipos nativos do Python."""
    if hasattr(valor, "to_native"):
        return valor.to_native()
    if isinstance(valor, dict):
        return {k: _nativo(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_nativo(v) for v in valor]
    return valor


class GraphClient:
    def __init__(self, driver: Driver, database: str) -> None:
        self._driver = driver
        self._db = database

    @classmethod
    def from_settings(cls, s: Settings) -> "GraphClient":
        driver = GraphDatabase.driver(
            s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password), connection_timeout=5
        )
        return cls(driver, s.neo4j_database)

    # Leitura roteada para réplicas leitoras quando em cluster (AuraDB / Enterprise)
    def read(self, query: str, **params: Any) -> list[dict]:
        trace.registrar("neo4j", "READ", " ".join(query.split())[:90])
        registros, _, _ = self._driver.execute_query(
            query, parameters_=params, database_=self._db, routing_=RoutingControl.READ
        )
        return [_nativo(r.data()) for r in registros]

    def write(self, query: str, **params: Any) -> list[dict]:
        trace.registrar("neo4j", "WRITE", " ".join(query.split())[:90])
        registros, _, _ = self._driver.execute_query(
            query, parameters_=params, database_=self._db, routing_=RoutingControl.WRITE
        )
        return [_nativo(r.data()) for r in registros]

    def write_many(self, statements: list[tuple[str, dict]]) -> None:
        """Executa vários comandos em UMA transação (tudo ou nada)."""
        trace.registrar("neo4j", "WRITE TX", f"{len(statements)} comandos Cypher")

        def trabalho(tx: Any) -> None:
            for consulta, params in statements:
                tx.run(consulta, params).consume()

        with self._driver.session(database=self._db) as sessao:
            sessao.execute_write(trabalho)

    def ping(self) -> bool:
        try:
            self._driver.verify_connectivity()
            return True
        except Exception:
            return False

    def close(self) -> None:
        self._driver.close()


@lru_cache(maxsize=1)
def get_graph() -> GraphClient:
    return GraphClient.from_settings(get_settings())


CONSTRAINTS = [
    "CREATE CONSTRAINT paciente_id IF NOT EXISTS FOR (n:Paciente) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT profissional_id IF NOT EXISTS FOR (n:Profissional) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT medicamento_id IF NOT EXISTS FOR (n:Medicamento) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT diagnostico_cid IF NOT EXISTS FOR (n:Diagnostico) REQUIRE n.cid IS UNIQUE",
    "CREATE CONSTRAINT classe_nome IF NOT EXISTS FOR (n:Classe) REQUIRE n.nome IS UNIQUE",
    "CREATE CONSTRAINT especialidade_nome IF NOT EXISTS FOR (n:Especialidade) REQUIRE n.nome IS UNIQUE",
    "CREATE CONSTRAINT leito_id IF NOT EXISTS FOR (n:Leito) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT ala_nome IF NOT EXISTS FOR (n:Ala) REQUIRE n.nome IS UNIQUE",
    # Índice em propriedade de relacionamento: acelera "medicamentos em uso" (filtro por data de fim)
    "CREATE INDEX prescrito_fim IF NOT EXISTS FOR ()-[r:PRESCRITO]-() ON (r.fim)",
]


def criar_schema(graph: GraphClient) -> int:
    for comando in CONSTRAINTS:
        graph.write(comando)
    return len(CONSTRAINTS)
