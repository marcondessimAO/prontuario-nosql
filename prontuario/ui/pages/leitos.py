"""Leitos e internações: ocupação em tempo real (Redis) com histórico no MongoDB."""
from __future__ import annotations

import streamlit as st

from ..tema import FUNDO_LEITO
from ..common import capturar_erros, exigir, formatar_data, sessao_atual, seletor_paciente, servicos, tabela


def render() -> None:
    sessao = sessao_atual()
    exigir(sessao, "leito:ver")
    sv = servicos()
    st.title("Leitos e internações")

    with capturar_erros():
        ocupacao = sv.leitos.ocupacao_por_ala()
        colunas = st.columns(max(len(ocupacao), 1))
        for coluna, ala in zip(colunas, ocupacao):
            coluna.metric(ala["ala"], f"{ala['ocupados']}/{ala['total']}", f"{ala['taxa']}% de ocupação", delta_color="off")

        estado = sv.leitos.estado()
        st.subheader("Mapa de leitos")
        tabela([
            {"leito": e["leito"], "ala": e["ala"], "status": "Ocupado" if e["ocupado"] else "Livre",
             "paciente": e["paciente"]}
            for e in estado
        ], cores=("status", FUNDO_LEITO))

        if not sessao.pode("leito:operar"):
            return
        interna, alta = st.columns(2)
        with interna:
            st.subheader("Internar")
            paciente_id = seletor_paciente(sessao, "leito_paciente")
            livres = [e["leito"] for e in estado if not e["ocupado"]]
            leito = st.selectbox("Leito livre", livres) if livres else None
            motivo = st.text_input("Motivo da internação")
            if st.button("Internar", type="primary", disabled=not (paciente_id and leito)):
                with capturar_erros():
                    sv.leitos.internar(sessao, paciente_id, leito, motivo)
                    st.success("Internação registrada (Redis reservou o leito; MongoDB gravou; Neo4j projetou).")
                    st.rerun()
        with alta:
            st.subheader("Dar alta")
            ativas = sv.leitos.internacoes_ativas()
            rotulos = {i["paciente_id"]: f"{i['paciente']} — {i['leito_id']} (desde {formatar_data(i['entrada'].isoformat())})"
                       for i in ativas}
            escolhido = st.selectbox("Internação ativa", list(rotulos), format_func=rotulos.get) if rotulos else None
            if st.button("Registrar alta", disabled=escolhido is None):
                with capturar_erros():
                    sv.leitos.dar_alta(sessao, escolhido)
                    st.success("Alta registrada e leito liberado.")
                    st.rerun()
