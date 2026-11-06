"""Sincroniza o grafo Neo4j a partir do MongoDB.

Uso:
  python -m scripts.sync_grafo            # apenas documentos pendentes (sync_grafo != true)
  python -m scripts.sync_grafo --todos    # reconstrói o grafo inteiro (idempotente)
"""
from __future__ import annotations

import argparse

from prontuario.services.container import montar


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--todos", action="store_true", help="reprojeta catálogos e todos os documentos")
    args = parser.parse_args()
    sv = montar()
    resultado = sv.grafo.projetar_tudo() if args.todos else sv.grafo.reconciliar()
    print(resultado)


if __name__ == "__main__":
    main()
