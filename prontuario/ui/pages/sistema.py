"""Saúde dos três bancos, reconciliação do grafo e console poliglota."""
from __future__ import annotations

import streamlit as st

from ...core import trace
from ..common import capturar_erros, exigir, sessao_atual, servicos, tabela

COLECOES = ("pacientes", "atendimentos", "exames", "internacoes", "usuarios", "auditoria",
            "medicamentos", "interacoes", "cid10", "profissionais", "leitos")


def render() -> None:
    sessao = sessao_atual()
    exigir(sessao, "sistema:administrar")
    sv = servicos()
    st.title("Sistema")

    mongo_col, redis_col, neo_col = st.columns(3)
    with mongo_col:
        st.subheader("MongoDB")
        with capturar_erros():
            sv.db.command("ping")
            st.success("online")
            tabela([{"coleção": c, "documentos": sv.db[c].estimated_document_count()} for c in COLECOES])
    with redis_col:
        st.subheader("Redis")
        with capturar_erros():
            sv.redis.ping()
            st.success("online")
            st.metric("Chaves", sv.redis.dbsize())
            st.metric("Memória", sv.redis.info("memory")["used_memory_human"])
            cache = sv.cache.metricas()
            st.metric("Taxa de acerto do cache", f"{cache['taxa_acerto']:.0%}")
    with neo_col:
        st.subheader("Neo4j")
        if sv.grafo.disponivel():
            st.success("online")
            with capturar_erros():
                estat = sv.grafo.estatisticas()
                tabela(estat["nos"])
                tabela(estat["relacionamentos"])
        else:
            st.error("offline — escritas clínicas seguem no MongoDB e ficam pendentes para reconciliação")

    st.divider()
    with capturar_erros():
        pendentes = sv.grafo.pendencias()
        st.metric("Documentos pendentes de projeção no grafo", pendentes)
        a, b = st.columns(2)
        if a.button("Reconciliar pendentes", disabled=pendentes == 0):
            st.success(f"Resultado: {sv.grafo.reconciliar()}")
        if b.button("Reconstruir grafo completo a partir do MongoDB"):
            st.success(f"Resultado: {sv.grafo.projetar_tudo()}")

    st.subheader("Console poliglota (últimas operações)")
    tabela(trace.recentes(40))
