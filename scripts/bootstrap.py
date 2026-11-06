"""Inicialização completa e idempotente: schemas + índices + constraints + carga inicial.

Uso:  python -m scripts.bootstrap [--reset]

É executado pelo serviço `init` do docker-compose antes de a aplicação subir.
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Callable

from prontuario.infra import mongo, neo4j_client
from prontuario.services.container import montar
from scripts.seed import executar, limpar_tudo


def aguardar(nome: str, verificar: Callable[[], object], tentativas: int = 30, intervalo: float = 2.0) -> None:
    for n in range(1, tentativas + 1):
        try:
            verificar()
            print(f"[ok] {nome} disponível")
            return
        except Exception as exc:  # noqa: BLE001 — qualquer falha de conexão => tenta de novo
            print(f"[..] aguardando {nome} ({n}/{tentativas}): {type(exc).__name__}")
            time.sleep(intervalo)
    print(f"[erro] {nome} não respondeu a tempo", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="recria tudo do zero")
    args = parser.parse_args()

    sv = montar()
    aguardar("MongoDB", lambda: sv.db.command("ping"))
    aguardar("Redis", lambda: sv.redis.ping())
    aguardar("Neo4j", lambda: sv.graph._driver.verify_connectivity())  # noqa: SLF001

    if args.reset:
        print("[..] --reset: limpando dados do projeto")
        limpar_tudo(sv)

    print("[..] MongoDB: coleções com $jsonSchema + índices", mongo.criar_schema(sv.db))
    print("[..] Neo4j: constraints/índices:", neo4j_client.criar_schema(sv.graph))

    if sv.db.pacientes.count_documents({}, limit=1) == 0:
        print("[..] carga inicial (dados sintéticos)")
        for chave, valor in executar(sv).items():
            print(f"     {chave}: {valor}")
    else:
        print("[ok] dados já presentes — carga inicial ignorada (use --reset para recriar)")
        sv.leitos.reconstruir_estado()  # garante o estado do Redis após restart sem AOF
        pendentes = sv.grafo.pendencias()
        if pendentes:
            print(f"[..] reconciliando {pendentes} documento(s) pendente(s) no grafo:", sv.grafo.reconciliar())
    print("[ok] bootstrap concluído")


if __name__ == "__main__":
    main()
