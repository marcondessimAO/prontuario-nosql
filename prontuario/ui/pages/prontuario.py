"""Prontuário do paciente: linha do tempo, exames, busca textual, adendos e risco familiar."""
from __future__ import annotations

import streamlit as st

from ..common import capturar_erros, exigir, formatar_data, sessao_atual, seletor_paciente, servicos, tabela

ROTULO_VITAIS = {
    "pa_sistolica": "PA sist.", "pa_diastolica": "PA diast.", "fc": "FC", "fr": "FR",
    "temperatura": "Temp. °C", "spo2": "SpO₂ %", "peso_kg": "Peso kg", "altura_cm": "Altura cm",
}


def _atendimento(sessao, a: dict) -> None:
    titulo = f"{formatar_data(a['data_hora'])} · {a['tipo'].upper()} · {a['profissional'].get('nome', '')}"
    with st.expander(titulo):
        st.write("**Queixa:**", a["queixa_principal"])
        if hist := a.get("anamnese", {}).get("historia_doenca_atual"):
            st.write("**HDA:**", hist)
        if vitais := a.get("sinais_vitais"):
            st.write("**Sinais vitais:** " + " · ".join(f"{ROTULO_VITAIS[k]} {v:g}" for k, v in vitais.items()))
        if a.get("diagnosticos"):
            st.write("**Diagnósticos:** " + "; ".join(f"{d['cid']} — {d['descricao']}" for d in a["diagnosticos"]))
        if a.get("prescricoes"):
            tabela([{k: p.get(k) for k in ("nome", "dose", "via", "frequencia", "duracao_dias")} for p in a["prescricoes"]])
        if a.get("alertas_reconhecidos"):
            st.warning("Alertas reconhecidos: " + a["alertas_reconhecidos"]["justificativa"])
        if a.get("evolucao"):
            st.write("**Evolução:**", a["evolucao"])
        st.caption(f"Desfecho: {a.get('desfecho', '—')} · ID {a['_id']}")
        for ad in a.get("adendos", []):
            st.info(f"Adendo de {ad['nome']} em {formatar_data(ad['data_hora'])}: {ad['texto']}")
        if sessao.pode("prontuario:adendo"):
            with st.form(f"adendo_{a['_id']}", clear_on_submit=True):
                texto = st.text_area("Novo adendo (o registro original não é alterado)", key=f"t_{a['_id']}")
                if st.form_submit_button("Adicionar adendo"):
                    with capturar_erros():
                        servicos().prontuario.adicionar_adendo(sessao, a["_id"], texto)
                        st.success("Adendo registrado.")
                        st.rerun()


def render() -> None:
    sessao = sessao_atual()
    exigir(sessao, "prontuario:ler")
    st.title("Prontuário")
    paciente_id = seletor_paciente(sessao)
    if not paciente_id:
        st.info("Busque e selecione um paciente.")
        return

    with capturar_erros():
        dados = servicos().prontuario.resumo(sessao, paciente_id)
        p = dados["paciente"]
        origem = "Redis (cache hit)" if dados["origem"] == "redis" else "MongoDB (cache miss; resultado gravado no Redis, TTL 120 s)"
        st.caption(f"Fonte desta leitura: **{origem}** · o acesso foi registrado na auditoria")

        st.header(p["nome"])
        nasc = formatar_data(p["data_nascimento"])[:10]
        st.write(f"Nascimento {nasc} · Sexo {p['sexo']} · Tipo sanguíneo {p.get('tipo_sanguineo', 'N/I')}")
        if p.get("alergias"):
            st.error("**ALERGIAS:** " + "; ".join(f"{a['substancia']} — {a.get('reacao', '')} ({a['gravidade']})" for a in p["alergias"]))
        if dados["em_uso"]:
            st.success("**Em uso:** " + "; ".join(f"{m['medicamento']} {m['dose']} {m['frequencia']}" for m in dados["em_uso"]))

        aba_linha, aba_exames, aba_busca, aba_familia = st.tabs(
            ["Linha do tempo", "Exames", "Buscar no histórico", "Risco familiar (grafo)"]
        )
        with aba_linha:
            if not dados["atendimentos"]:
                st.caption("Sem atendimentos registrados.")
            for a in dados["atendimentos"]:
                _atendimento(sessao, a)
        with aba_exames:
            for e in dados["exames"]:
                with st.expander(f"{formatar_data(e['data_coleta'])} · {e['nome']} ({e['tipo']})"):
                    if e["tipo"] == "laboratorial":
                        tabela(e.get("resultados", []))
                    else:
                        st.write(e.get("laudo", ""))
                        for anexo in e.get("anexos", []):
                            st.caption(f"Anexo: {anexo['nome']} ({anexo['mime']})")
        with aba_busca:
            termo = st.text_input("Texto livre (queixa/evolução) — índice de texto do MongoDB, português")
            if termo:
                with capturar_erros():
                    tabela([
                        {"data": formatar_data(r["data_hora"]), "queixa": r["queixa_principal"], "evolução": r.get("evolucao", "")}
                        for r in servicos().prontuario.buscar_texto(sessao, paciente_id, termo)
                    ])
        with aba_familia:
            if not sessao.pode("grafo:consultar"):
                st.info("Seu perfil não consulta o grafo.")
            else:
                st.caption("Diagnósticos de parentes de até 2º grau — travessia `PARENTE_DE*1..2` no Neo4j.")
                risco = servicos().grafo.risco_familiar(paciente_id)
                tabela(risco) if risco else st.caption("Sem diagnósticos relevantes em parentes registrados.")
