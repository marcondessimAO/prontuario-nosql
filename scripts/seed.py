"""Carga inicial dos três bancos.

Uso:  python -m scripts.seed [--reset]

Ordem (o MongoDB é a fonte da verdade):
  1. MongoDB  — catálogos, pacientes, atendimentos, exames, internações, usuários;
  2. Redis    — reconstrói a ocupação de leitos (estado derivado);
  3. Neo4j    — projeta catálogos e documentos no grafo.
"""
from __future__ import annotations

import argparse
import os

from pymongo import ReplaceOne

from prontuario.data.seed_data import USUARIOS, build_dataset
from prontuario.services.container import Servicos, montar

COLECOES_SEED = (
    "cid10", "medicamentos", "interacoes", "profissionais", "leitos",
    "pacientes", "atendimentos", "exames", "internacoes",
)
COLECOES_APP = COLECOES_SEED + ("usuarios", "auditoria")
PREFIXOS_REDIS = (
    "sessao:", "cache:", "triagem:", "ficha:", "leitos:", "lock:", "notif:", "eventos:", "stats:", "login:",
)


def limpar_tudo(sv: Servicos) -> None:
    """Apaga os dados da aplicação nos 3 bancos (somente chaves/coleções do projeto)."""
    for colecao in COLECOES_APP:
        sv.db.drop_collection(colecao)
    for prefixo in PREFIXOS_REDIS:
        chaves = list(sv.redis.scan_iter(match=f"{prefixo}*", count=500))
        if chaves:
            sv.redis.delete(*chaves)
    sv.redis.delete("triagem:fila", "triagem:seq", "eventos:clinicos")
    sv.graph.write("MATCH (n) DETACH DELETE n")


def _gravar(sv: Servicos, colecao: str, docs: list[dict]) -> None:
    if docs:
        sv.db[colecao].bulk_write([ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in docs])


def executar(sv: Servicos) -> dict[str, int]:
    dados = build_dataset()
    for colecao in COLECOES_SEED:
        _gravar(sv, colecao, dados[colecao])

    senha = os.getenv("SEED_SENHA_DEMO", "Hosp2026demo")
    for login, nome, perfil, prof_id in USUARIOS:
        sv.auth.criar_usuario(login, nome, perfil, senha, prof_id)

    ocupados = sv.leitos.reconstruir_estado()
    resumo_grafo = sv.grafo.projetar_tudo()
    return {**{c: len(dados[c]) for c in COLECOES_SEED}, "leitos_ocupados": ocupados, **{f"grafo_{k}": v for k, v in resumo_grafo.items()}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Carga inicial (MongoDB + Redis + Neo4j)")
    parser.add_argument("--reset", action="store_true", help="apaga os dados do projeto antes de carregar")
    args = parser.parse_args()
    sv = montar()
    if args.reset:
        limpar_tudo(sv)
        from prontuario.infra.mongo import criar_schema
        criar_schema(sv.db)
    for chave, valor in executar(sv).items():
        print(f"  {chave}: {valor}")


if __name__ == "__main__":
    main()
