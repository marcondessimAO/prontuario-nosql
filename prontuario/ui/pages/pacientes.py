"""Busca e cadastro de pacientes."""
from __future__ import annotations

from datetime import date

import streamlit as st

from ...services.pacientes import SEXOS, TIPOS_SANGUINEOS
from ..common import capturar_erros, exigir, sessao_atual, seletor_paciente, servicos, tabela


def render() -> None:
    sessao = sessao_atual()
    exigir(sessao, "paciente:ver")
    st.title("Pacientes")
    aba_busca, aba_cadastro = st.tabs(["Buscar", "Cadastrar novo"])

    with aba_busca:
        paciente_id = seletor_paciente(sessao)
        if paciente_id:
            with capturar_erros():
                p = servicos().pacientes.obter(sessao, paciente_id)
                st.subheader(p["nome"])
                c1, c2, c3 = st.columns(3)
                c1.metric("Idade", f"{p['idade']} anos")
                c2.metric("Tipo sanguíneo", p["tipo_sanguineo"])
                c3.metric("CPF", p["cpf"])
                st.write("**Contato:**", p["contato"].get("telefone") or "—")
                st.write("**Convênio:**", (p["convenio"] or {}).get("nome", "Particular / SUS"))
                if p["alergias"]:
                    st.error("Alergias: " + "; ".join(f"{a['substancia']} ({a['gravidade']})" for a in p["alergias"]))
                st.caption("Para ver o histórico clínico, abra **Prontuário** no menu.")

    with aba_cadastro:
        if not sessao.pode("paciente:cadastrar"):
            st.info("Apenas a recepção pode cadastrar pacientes.")
            return
        with st.form("cadastro_paciente", clear_on_submit=True):
            nome = st.text_input("Nome completo *")
            c1, c2 = st.columns(2)
            cpf = c1.text_input("CPF *")
            nascimento = c2.date_input("Data de nascimento *", value=date(1990, 1, 1),
                                       min_value=date(1900, 1, 1), max_value=date.today())
            c3, c4, c5 = st.columns(3)
            sexo = c3.selectbox("Sexo", SEXOS, format_func={"F": "Feminino", "M": "Masculino", "I": "Indefinido"}.get)
            sangue = c4.selectbox("Tipo sanguíneo", TIPOS_SANGUINEOS, index=len(TIPOS_SANGUINEOS) - 1)
            telefone = c5.text_input("Telefone")
            consentimento = st.checkbox("Paciente informado sobre o tratamento de dados de saúde (LGPD, art. 11)", value=True)
            enviado = st.form_submit_button("Cadastrar", type="primary")
        if enviado:
            with capturar_erros():
                novo_id = servicos().pacientes.cadastrar(sessao, {
                    "nome": nome, "cpf": cpf, "data_nascimento": nascimento, "sexo": sexo,
                    "tipo_sanguineo": sangue, "telefone": telefone, "consentimento": consentimento,
                })
                st.success(f"Paciente cadastrado: {novo_id}")
