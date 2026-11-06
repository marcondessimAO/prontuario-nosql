"""Painel: indicadores (MongoDB agregado + cache Redis), ocupação e fila em tempo real."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ..common import capturar_erros, exigir, formatar_data, sessao_atual, servicos, tabela


def render() -> None:
    sessao = sessao_atual()
    exigir(sessao, "indicadores:ver")
    st.title("Painel assistencial")

    with capturar_erros():
        dados = servicos().indicadores.painel(sessao)
        mongo = dados["mongo"]
        origem = "Redis (cache de 30 s)" if dados["origem_mongo"] == "redis" else "MongoDB (agregação)"
        st.caption(f"Agregados lidos de: **{origem}** · estado em tempo real: **Redis** · comorbidades: **Neo4j**")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Pacientes cadastrados", mongo["total_pacientes"])
        c2.metric(f"Atendimentos ({dados['janela_dias']} dias)", mongo["atendimentos_janela"])
        c3.metric("Fila de triagem agora", dados["fila"])
        c4.metric("Chamados hoje", dados["chamados_hoje"])

        esquerda, direita = st.columns(2)
        with esquerda:
            st.subheader("Atendimentos por dia")
            if mongo["por_dia"]:
                st.bar_chart(pd.DataFrame(mongo["por_dia"]).set_index("dia")["total"])
            st.subheader("Atendimentos por especialidade")
            if mongo["por_especialidade"]:
                st.bar_chart(pd.DataFrame(mongo["por_especialidade"]).set_index("especialidade")["total"])
        with direita:
            st.subheader("Diagnósticos mais frequentes (CID-10)")
            tabela(mongo["top_cids"])
            st.subheader("Ocupação de leitos (Redis)")
            tabela(dados["ocupacao"])

        st.subheader("Comorbidades mais comuns (Neo4j)")
        tabela(dados["comorbidades"])

        meio, fim = st.columns(2)
        with meio:
            st.subheader("Eficiência do cache")
            cache = dados["cache"]
            st.metric("Taxa de acerto", f"{cache['taxa_acerto']:.0%}", f"{cache['hits']} hits / {cache['misses']} misses")
        with fim:
            st.subheader("Eventos recentes (Redis Streams)")
            tabela([{"hora": formatar_data(e.get("ts")), "evento": e.get("evento")} for e in dados["eventos"]])
