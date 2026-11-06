"""Tela de login: autentica no MongoDB e cria a sessão no Redis."""
from __future__ import annotations

import streamlit as st

from ...core.config import get_settings
from ...data.seed_data import USUARIOS
from ..common import capturar_erros, servicos


def render() -> None:
    st.title("Prontuário Eletrônico")
    st.caption("Persistência poliglota: MongoDB · Redis · Neo4j — acesso restrito a profissionais autorizados.")
    if aviso := st.session_state.pop("aviso", None):
        st.warning(aviso)

    with st.form("login"):
        login = st.text_input("Usuário", autocomplete="username")
        senha = st.text_input("Senha", type="password", autocomplete="current-password")
        enviado = st.form_submit_button("Entrar", type="primary")
    if enviado:
        with capturar_erros():
            sessao = servicos().auth.login(login, senha)
            st.session_state["token"] = sessao.token
            st.rerun()

    if get_settings().demo_mode:
        with st.expander("Usuários de demonstração (ambiente acadêmico)"):
            st.markdown(
                "A senha de todos é a definida em `SEED_SENHA_DEMO` (padrão no README).\n\n"
                + "\n".join(f"- `{u}` — {nome} (**{perfil}**)" for u, nome, perfil, _ in USUARIOS)
            )
