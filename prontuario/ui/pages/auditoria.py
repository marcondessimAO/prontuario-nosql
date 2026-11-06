"""Trilha de auditoria (somente administrador)."""
from __future__ import annotations

import streamlit as st

from ..common import capturar_erros, exigir, formatar_data, sessao_atual, servicos, tabela


def render() -> None:
    sessao = sessao_atual()
    exigir(sessao, "auditoria:ler")
    sv = servicos()
    st.title("Auditoria de acessos")
    st.caption("Registro append-only no MongoDB: quem acessou qual prontuário, quando e para quê (LGPD art. 37).")

    with capturar_erros():
        resumo = sv.auditoria.contagem_por_acao()
        acoes = [""] + [r["acao"] for r in resumo]
        c1, c2, c3 = st.columns(3)
        usuario = c1.text_input("Usuário")
        acao = c2.selectbox("Ação", acoes)
        paciente = c3.text_input("ID do paciente (ex.: pac-0001)")
        registros = sv.auditoria.listar(paciente_id=paciente.strip() or None, usuario=usuario.strip() or None,
                                        acao=acao or None)
        tabela([
            {"quando": formatar_data(r["data_hora"].isoformat()), "usuário": r["usuario"], "perfil": r["perfil"],
             "ação": r["acao"], "paciente": r.get("paciente_id") or "", "detalhes": str(r.get("detalhes") or "")}
            for r in registros
        ])
        st.subheader("Volume por ação")
        tabela(resumo)
