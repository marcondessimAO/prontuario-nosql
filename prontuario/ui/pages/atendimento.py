"""Registro de novo atendimento: lock no Redis + checagem de segurança da prescrição no Neo4j."""
from __future__ import annotations

import streamlit as st

from ...services.prontuario import DESFECHOS, TIPOS_ATENDIMENTO
from ..common import capturar_erros, exigir, sessao_atual, seletor_paciente, servicos

EXAMES_COMUNS = ["Hemograma", "Glicemia de jejum", "HbA1c", "Creatinina", "Ureia", "Colesterol total e frações",
                 "TSH", "Urina tipo I", "Eletrocardiograma", "Radiografia de tórax", "INR"]
VITAIS = [("pa_sistolica", "PA sistólica"), ("pa_diastolica", "PA diastólica"), ("fc", "FC (bpm)"),
          ("fr", "FR (irpm)"), ("temperatura", "Temp. (°C)"), ("spo2", "SpO₂ (%)"),
          ("peso_kg", "Peso (kg)"), ("altura_cm", "Altura (cm)")]


def render() -> None:
    sessao = sessao_atual()
    exigir(sessao, "prontuario:escrever")
    sv = servicos()
    st.title("Novo atendimento")
    paciente_id = seletor_paciente(sessao, "atend_paciente")
    if not paciente_id:
        st.info("Busque e selecione um paciente para iniciar.")
        return

    dono = sv.bloqueio.dono(paciente_id)
    if dono and dono != sessao.login:
        st.warning(f"Este prontuário está sendo editado por **{dono}**. Aguarde a liberação (o bloqueio expira sozinho).")
        return
    if not dono:
        st.info("Para registrar um atendimento é preciso bloquear o prontuário (evita edição concorrente).")
        if st.button("Iniciar atendimento", type="primary"):
            with capturar_erros():
                if sv.bloqueio.adquirir(paciente_id, sessao.login):
                    st.rerun()
                st.warning("Outro profissional acabou de bloquear este prontuário.")
        return
    sv.bloqueio.renovar(paciente_id, sessao.login)
    st.success("Prontuário bloqueado para você (Redis `SET NX EX 120`, renovado a cada interação).")

    nonce = st.session_state.setdefault("at_nonce", 0)
    k = lambda nome: f"at_{nonce}_{nome}"  # noqa: E731 — chaves únicas por atendimento

    with capturar_erros():
        paciente = sv.pacientes.obter(sessao, paciente_id)
    st.subheader(paciente["nome"])
    if paciente["alergias"]:
        st.error("Alergias: " + "; ".join(f"{a['substancia']} ({a['gravidade']})" for a in paciente["alergias"]))

    tipo = st.selectbox("Tipo", TIPOS_ATENDIMENTO, key=k("tipo"))
    queixa = st.text_input("Queixa principal *", key=k("queixa"))
    historia = st.text_area("História da doença atual", key=k("historia"))

    st.markdown("**Sinais vitais** (deixe 0 se não aferido)")
    colunas = st.columns(4)
    vitais = {
        campo: colunas[i % 4].number_input(rotulo, min_value=0.0, value=0.0, step=1.0, key=k(campo))
        for i, (campo, rotulo) in enumerate(VITAIS)
    }
    exame_fisico = st.text_area("Exame físico", key=k("exame_fisico"))

    cids = {c["_id"]: c["descricao"] for c in sv.catalogos.cids()}
    escolhidos = st.multiselect("Diagnósticos (CID-10) — o primeiro é o principal", list(cids),
                                format_func=lambda c: f"{c} — {cids[c]}", key=k("cids"))
    meds = {m["_id"]: m for m in sv.catalogos.medicamentos()}
    med_ids = st.multiselect("Prescrição", list(meds), format_func=lambda m: f"{meds[m]['nome']} ({meds[m]['classe']})",
                             key=k("meds"))

    prescricoes = []
    for mid in med_ids:
        pad = meds[mid].get("posologia_padrao", {})
        a, b, c, d = st.columns([2, 1, 2, 1])
        prescricoes.append({
            "medicamento_id": mid,
            "dose": a.text_input(f"Dose — {meds[mid]['nome']}", value=pad.get("dose", ""), key=k(f"dose_{mid}")),
            "via": b.text_input("Via", value=pad.get("via", "VO"), key=k(f"via_{mid}")),
            "frequencia": c.text_input("Frequência", value=pad.get("frequencia", ""), key=k(f"freq_{mid}")),
            "duracao_dias": d.number_input("Dias", min_value=0, max_value=365, value=30, key=k(f"dias_{mid}")),
        })

    # Verificação automática no grafo a cada interação (consulta Cypher de leitura)
    verificacao = {"verificado": True, "alertas": []}
    if prescricoes:
        verificacao = sv.grafo.verificar_prescricao(paciente_id, med_ids)
        if not verificacao["verificado"]:
            st.warning("Verificação de segurança indisponível (Neo4j). Revise manualmente e justifique.")
        for alerta in verificacao["alertas"]:
            exibir = st.error if alerta["gravidade"] == "grave" else st.warning
            exibir(f"**{alerta['gravidade'].upper()}** — {alerta['mensagem']}")
        if not verificacao["alertas"] and verificacao["verificado"]:
            st.success("Sem alergias ou interações conhecidas no catálogo (não substitui o julgamento clínico).")

    exigir_justificativa = any(a["gravidade"] == "grave" for a in verificacao["alertas"]) or (
        bool(prescricoes) and not verificacao["verificado"])
    justificativa = ""
    if exigir_justificativa:
        justificativa = st.text_area("Justificativa clínica para prosseguir com alertas graves *", key=k("justificativa"))

    exames = st.multiselect("Exames solicitados", EXAMES_COMUNS, key=k("exames"))
    evolucao = st.text_area("Evolução / conduta", key=k("evolucao"))
    c1, c2 = st.columns(2)
    desfecho = c1.selectbox("Desfecho", DESFECHOS, key=k("desfecho"))
    profissionais = {p["_id"]: p for p in sv.catalogos.profissionais() if p["_id"] != sessao.profissional_id}
    destino = c2.selectbox("Encaminhar para", [""] + list(profissionais), key=k("destino"),
                           format_func=lambda i: "— ninguém —" if not i else f"{profissionais[i]['nome']} ({profissionais[i]['especialidade']})")

    salvar, cancelar = st.columns(2)
    if salvar.button("Salvar atendimento", type="primary"):
        with capturar_erros():
            resultado = sv.prontuario.registrar_atendimento(sessao, {
                "paciente_id": paciente_id, "tipo": tipo, "queixa_principal": queixa, "historia": historia,
                "sinais_vitais": vitais, "exame_fisico": exame_fisico,
                "diagnosticos": [{"cid": c, "tipo": "principal" if i == 0 else "secundario"} for i, c in enumerate(escolhidos)],
                "prescricoes": prescricoes, "exames_solicitados": exames, "evolucao": evolucao,
                "desfecho": desfecho, "encaminhado_para": destino or None, "justificativa_alertas": justificativa,
            })
            st.session_state["at_nonce"] = nonce + 1
            st.session_state["at_ultimo"] = resultado
            st.rerun()
    if cancelar.button("Cancelar e liberar bloqueio"):
        sv.bloqueio.liberar(paciente_id, sessao.login)
        st.rerun()


def mostrar_ultimo_salvo() -> None:
    """Chamado após o rerun para confirmar o salvamento."""
    if resultado := st.session_state.pop("at_ultimo", None):
        st.success(f"Atendimento {resultado['id']} salvo no MongoDB. "
                   f"Grafo {'sincronizado' if resultado['sync_grafo'] else 'PENDENTE de reconciliação'}.")
