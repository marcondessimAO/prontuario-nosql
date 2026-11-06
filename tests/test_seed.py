"""Invariantes do dataset sintético (garantem que o seed respeita as regras do schema)."""
from collections import Counter

from prontuario.core.validators import cpf_valido
from prontuario.data.seed_data import build_dataset


def test_dataset_e_deterministico_para_mesma_seed():
    a, b = build_dataset(seed=1), build_dataset(seed=1)
    assert [p["nome"] for p in a["pacientes"]] == [p["nome"] for p in b["pacientes"]]


def test_ids_e_cpfs_sao_unicos_e_validos():
    d = build_dataset()
    for colecao, docs in d.items():
        ids = [x["_id"] for x in docs]
        assert len(ids) == len(set(ids)), colecao
    cpfs = [p["cpf"] for p in d["pacientes"]]
    assert len(set(cpfs)) == len(cpfs) and all(cpf_valido(c) for c in cpfs)


def test_referencias_entre_colecoes_sao_consistentes():
    d = build_dataset()
    pacientes = {p["_id"] for p in d["pacientes"]}
    profs = {p["_id"] for p in d["profissionais"]}
    meds = {m["_id"] for m in d["medicamentos"]}
    cids = {c["_id"] for c in d["cid10"]}
    for a in d["atendimentos"]:
        assert a["paciente_id"] in pacientes and a["profissional_id"] in profs
        assert a["encaminhado_para"] is None or a["encaminhado_para"] in profs
        assert {x["cid"] for x in a["diagnosticos"]} <= cids
        assert {x["medicamento_id"] for x in a["prescricoes"]} <= meds
    for i in d["interacoes"]:
        assert i["a"] in meds and i["b"] in meds and i["gravidade"] in {"leve", "moderada", "grave"}
    for e in d["exames"]:
        assert e["paciente_id"] in pacientes


def test_internacoes_ativas_respeitam_indices_unicos_parciais():
    ativas = [i for i in build_dataset()["internacoes"] if i["ativa"]]
    assert all(c == 1 for c in Counter(i["paciente_id"] for i in ativas).values())
    assert all(c == 1 for c in Counter(i["leito_id"] for i in ativas).values())


def test_seed_nao_prescreve_medicamento_que_conflita_com_alergia():
    d = build_dataset()
    meds = {m["_id"]: m for m in d["medicamentos"]}
    alergias = {p["_id"]: p["alergias"] for p in d["pacientes"]}
    for a in d["atendimentos"]:
        for rx in a["prescricoes"]:
            for al in alergias[a["paciente_id"]]:
                assert al.get("classe") != meds[rx["medicamento_id"]]["classe"]
                assert al.get("medicamento_id") != rx["medicamento_id"]


def test_rede_de_encaminhamento_conecta_emergencia_a_nefrologia():
    d = build_dataset()
    arestas = {(a["profissional_id"], a["encaminhado_para"]) for a in d["atendimentos"] if a["encaminhado_para"]}
    assert ("prof-007", "prof-002") in arestas and ("prof-001", "prof-006") in arestas
