"""Triagem (Manchester) e fila em tempo real no Redis (Sorted Set)."""
from __future__ import annotations

import streamlit as st

from ...services.triagem import RISCOS, TEMPO_ALVO_MIN
from ..tema import FUNDO_RISCO
from ..common import ROTULO_RISCO, capturar_erros, exigir, sessao_atual, seletor_paciente, servicos, tabela


@st.fragment(run_every=5)
def _fila_ao_vivo(sessao) -> None:
    """Re-renderiza sozinho a cada 5 s — apenas este bloco, não a página inteira."""
    with capturar_erros():
        fila = servicos().triagem.fila(sessao)
        st.subheader(f"Fila ao vivo ({len(fila)})")
        tabela([
            {"#": f["posicao"], "senha": f["senha"], "risco": ROTULO_RISCO[f["risco"]],
             "paciente": f["paciente"], "queixa": f["queixa"], "espera (min)": f["espera_min"],
             "meta": "Excedida" if f["acima_do_alvo"] else "Dentro do alvo"}
            for f in fila
        ], cores=("risco", FUNDO_RISCO))


def render() -> None:
    sessao = sessao_atual()
    exigir(sessao, "triagem:ver")
    st.title("Triagem e fila de atendimento")
    st.caption("Redis Sorted Set: `score = prioridade × 10¹³ + chegada_ms` → prioridade clínica, depois ordem de chegada.")

    if sessao.pode("triagem:operar"):
        with st.expander("Registrar chegada e classificação de risco", expanded=True):
            paciente_id = seletor_paciente(sessao, "triagem_paciente")
            risco = st.selectbox("Classificação (Manchester)", list(RISCOS),
                                 format_func=lambda r: f"{ROTULO_RISCO[r]} (meta de {TEMPO_ALVO_MIN[r]} min)")
            queixa = st.text_input("Queixa principal da triagem")
            if st.button("Entrar na fila", type="primary", disabled=not paciente_id):
                with capturar_erros():
                    ficha = servicos().triagem.entrar_na_fila(sessao, paciente_id, risco, queixa)
                    st.success(f"Senha **{ficha['senha']}** gerada ({risco}).")
        if st.button("Chamar próximo"):
            with capturar_erros():
                chamado = servicos().triagem.chamar_proximo(sessao)
                if chamado:
                    st.success(f"Chamando **{chamado['senha']}** — {chamado['paciente']} ({chamado['risco']})")
                else:
                    st.info("Fila vazia.")
    _fila_ao_vivo(sessao)
