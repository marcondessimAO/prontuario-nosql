"""Análises em grafo (Neo4j): condutas similares, comorbidades, encaminhamentos e contatos."""
from __future__ import annotations

import streamlit as st

from ...services import grafo as cypher
from ..common import capturar_erros, exigir, formatar_data, sessao_atual, seletor_paciente, servicos, tabela


def _ver_cypher(consulta: str) -> None:
    with st.expander("Ver consulta Cypher"):
        st.code(consulta.strip(), language="cypher")


def render() -> None:
    sessao = sessao_atual()
    exigir(sessao, "grafo:consultar")
    sv = servicos()
    st.title("Rede clínica (Neo4j)")
    aba_cond, aba_comorb, aba_rede, aba_contato = st.tabs(
        ["Condutas em pacientes similares", "Comorbidades", "Rede de encaminhamento", "Rastreio de contatos"]
    )

    with aba_cond:
        st.caption("Filtragem colaborativa: medicamentos usados por pacientes com diagnósticos em comum, "
                   "excluindo os já usados e os que conflitam com as alergias do paciente. **Apoio à decisão, não prescrição.**")
        paciente_id = seletor_paciente(sessao, "rede_paciente")
        if paciente_id:
            with capturar_erros():
                sugestoes = sv.grafo.sugerir_condutas(paciente_id)
                tabela(sugestoes) if sugestoes else st.info("Sem pacientes similares com prescrições.")
        _ver_cypher(cypher.Q_SUGESTAO_CONDUTA)

    with aba_comorb:
        with capturar_erros():
            tabela(sv.grafo.comorbidades(15))
        _ver_cypher(cypher.Q_COMORBIDADES)

    with aba_rede:
        profs = {p["_id"]: p for p in sv.catalogos.profissionais() if p["especialidade"] != "Enfermagem"}
        rotulo = lambda i: f"{profs[i]['nome']} ({profs[i]['especialidade']})"  # noqa: E731
        ids = list(profs)
        c1, c2 = st.columns(2)
        # Padrões da demonstração: Emergência -> Nefrologia (3 saltos pela rede de encaminhamento)
        origem = c1.selectbox("De", ids, index=ids.index("prof-007") if "prof-007" in ids else 0,
                              format_func=rotulo, key="rede_de")
        destino = c2.selectbox("Para", ids, index=ids.index("prof-006") if "prof-006" in ids else len(ids) - 1,
                               format_func=rotulo, key="rede_para")
        with capturar_erros():
            caminho = sv.grafo.caminho_encaminhamento(origem, destino)
            if caminho:
                st.success(f"Caminho mais curto: {caminho['saltos']} salto(s)")
                aresta = " -> ".join(f'"{nome}"' for nome in caminho["caminho"])
                st.graphviz_chart(f"digraph {{ rankdir=LR; node [shape=box, style=rounded]; {aresta}; }}")
            else:
                st.info("Sem caminho de encaminhamento entre esses profissionais.")
        _ver_cypher(cypher.Q_CAMINHO)
        st.divider()
        esp = st.selectbox("Especialidade desejada", sorted({p["especialidade"] for p in profs.values()}))
        with capturar_erros():
            tabela(sv.grafo.especialistas_proximos(origem, esp))
        _ver_cypher(cypher.Q_ESPECIALISTAS)

    with aba_contato:
        st.caption("Pacientes que dividiram a MESMA ala com o paciente-índice em períodos sobrepostos (ex.: infecção).")
        indice = seletor_paciente(sessao, "contato_paciente")
        if indice:
            with capturar_erros():
                contatos = sv.grafo.rastrear_contatos(indice)
                tabela([
                    {"paciente": c["nome"], "ala": c["ala"], "entrada": formatar_data(c["entrada"].isoformat()),
                     "saída": formatar_data(c["saida"].isoformat()) if c["saida"] else "ainda internado"}
                    for c in contatos
                ]) if contatos else st.info("Nenhum contato hospitalar identificado.")
        _ver_cypher(cypher.Q_CONTATOS)
