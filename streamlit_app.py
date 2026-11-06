"""Ponto de entrada do Streamlit: login, navegação por perfil e console poliglota."""
from __future__ import annotations

import logging

import streamlit as st

from prontuario.core import trace
from prontuario.ui import tema
from prontuario.ui.common import capturar_erros, sessao_atual, servicos
from prontuario.ui.pages import (
    atendimento, auditoria, leitos, login, pacientes, painel, rede_clinica, sistema, triagem,
)
from prontuario.ui.pages import prontuario as pagina_prontuario  # evita ofuscar o pacote `prontuario`

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

st.set_page_config(page_title="Prontuário Eletrônico", page_icon=":material/medical_services:", layout="wide")
tema.aplicar()

PAGINAS = [  # (permissão exigida, título, ícone Material, módulo, url)
    ("indicadores:ver", "Painel", ":material/dashboard:", painel, "painel"),
    ("paciente:ver", "Pacientes", ":material/group:", pacientes, "pacientes"),
    ("prontuario:ler", "Prontuário", ":material/description:", pagina_prontuario, "prontuario"),
    ("prontuario:escrever", "Novo atendimento", ":material/edit_note:", atendimento, "atendimento"),
    ("triagem:ver", "Triagem e fila", ":material/format_list_numbered:", triagem, "triagem"),
    ("leito:ver", "Leitos", ":material/bed:", leitos, "leitos"),
    ("grafo:consultar", "Rede clínica", ":material/hub:", rede_clinica, "rede"),
    ("auditoria:ler", "Auditoria", ":material/fact_check:", auditoria, "auditoria"),
    ("sistema:administrar", "Sistema", ":material/settings:", sistema, "sistema"),
]


def main() -> None:
    sessao = sessao_atual()
    if sessao is None:
        st.navigation([st.Page(login.render, title="Entrar", icon=":material/lock:", url_path="login")]).run()
        return

    atendimento.mostrar_ultimo_salvo()
    paginas = [st.Page(m.render, title=t, icon=i, url_path=u) for perm, t, i, m, u in PAGINAS if sessao.pode(perm)]
    pagina = st.navigation(paginas)

    with st.sidebar:
        st.markdown(f"**{sessao.nome}**  \n`{sessao.perfil}`")
        if sessao.profissional_id:
            with capturar_erros():
                nao_lidas = servicos().notificacoes.nao_lidas(sessao.profissional_id)
                if nao_lidas:
                    st.warning(f"{nao_lidas} notificação(ões) não lida(s)")
                    with st.expander("Ver notificações"):
                        for n in servicos().notificacoes.listar(sessao.profissional_id, 5):
                            st.caption(f"**{n['titulo']}** — {n['corpo']}")
                        if st.button("Marcar como lidas"):
                            servicos().notificacoes.marcar_lidas(sessao.profissional_id)
                            st.rerun()
        if st.button("Sair"):
            with capturar_erros():
                servicos().auth.logout(sessao.token)
            st.session_state.pop("token", None)
            st.rerun()
        with st.expander("Console poliglota"):
            st.caption("Últimas operações por banco (atualiza a cada interação).")
            for e in trace.recentes(12):
                banco = {"mongo": "MONGODB", "redis": "REDIS", "neo4j": "NEO4J"}.get(e["banco"], e["banco"].upper())
                st.caption(f"`{e['hora']}` **{banco}** · {e['operacao']} · {e['detalhe']}")

    pagina.run()


main()
