import pytest

from prontuario.core.errors import ConflitoErro, ValidacaoErro
from prontuario.core.tempo import agora

PACIENTE = "pac-0001"


def _dados(**extra):
    base = {
        "paciente_id": PACIENTE, "tipo": "consulta", "queixa_principal": "Dor de cabeça há 2 dias",
        "sinais_vitais": {"pa_sistolica": 130, "pa_diastolica": 85, "fc": 0},
        "diagnosticos": [{"cid": "I10", "tipo": "principal"}],
        "prescricoes": [], "desfecho": "alta",
    }
    return {**base, **extra}


def _iniciar(sv, sessao):
    assert sv.bloqueio.adquirir(PACIENTE, sessao.login)


def test_primeira_leitura_vem_do_mongo_e_segunda_do_redis(sv, medico):
    assert sv.prontuario.resumo(medico, PACIENTE)["origem"] == "mongodb"
    assert sv.prontuario.resumo(medico, PACIENTE)["origem"] == "redis"
    assert sv.redis.ttl(f"cache:prontuario:{PACIENTE}") > 0


def test_cache_hit_e_miss_devolvem_o_mesmo_formato(sv, medico):
    miss = sv.prontuario.resumo(medico, PACIENTE)
    hit = sv.prontuario.resumo(medico, PACIENTE)
    assert {k: v for k, v in miss.items() if k != "origem"} == {k: v for k, v in hit.items() if k != "origem"}


def test_cpf_nunca_vai_para_o_cache(sv, medico):
    sv.prontuario.resumo(medico, PACIENTE)
    assert "cpf" not in sv.redis.get(f"cache:prontuario:{PACIENTE}")


def test_leitura_com_cache_hit_tambem_e_auditada(sv, medico):
    sv.prontuario.resumo(medico, PACIENTE)
    sv.prontuario.resumo(medico, PACIENTE)
    acessos = sv.db.auditoria.count_documents({"acao": "prontuario:ler", "paciente_id": PACIENTE})
    assert acessos == 2


def test_escrever_exige_lock_do_proprio_usuario(sv, medico, enfermeiro):
    with pytest.raises(ConflitoErro, match="não está bloqueado"):
        sv.prontuario.registrar_atendimento(medico, _dados())
    _iniciar(sv, enfermeiro)
    with pytest.raises(ConflitoErro, match="em edição por"):
        sv.prontuario.registrar_atendimento(medico, _dados())


def test_registrar_atendimento_invalida_cache_libera_lock_e_projeta_no_grafo(sv, medico, grafo_falso):
    sv.prontuario.resumo(medico, PACIENTE)
    _iniciar(sv, medico)
    resultado = sv.prontuario.registrar_atendimento(medico, _dados())

    assert resultado["sync_grafo"] is True and grafo_falso.escritas
    assert sv.redis.get(f"cache:prontuario:{PACIENTE}") is None          # invalidado
    assert sv.bloqueio.dono(PACIENTE) is None                            # lock liberado
    salvo = sv.db.atendimentos.find_one({"_id": resultado["id"]})
    assert salvo["sinais_vitais"] == {"pa_sistolica": 130.0, "pa_diastolica": 85.0}  # 0 = não aferido
    assert sv.prontuario.resumo(medico, PACIENTE)["origem"] == "mongodb"


def test_neo4j_fora_do_ar_nao_impede_o_registro_clinico(sv, medico, grafo_falso):
    grafo_falso.falhar = True
    _iniciar(sv, medico)
    resultado = sv.prontuario.registrar_atendimento(medico, _dados())
    assert resultado["sync_grafo"] is False
    assert sv.db.atendimentos.find_one({"_id": resultado["id"]})["sync_grafo"] is False
    assert sv.grafo.pendencias() >= 1

    grafo_falso.falhar = False   # grafo volta: reconciliação reprocessa as pendências
    assert sv.grafo.reconciliar()["falhas"] == 0
    assert sv.db.atendimentos.find_one({"_id": resultado["id"]})["sync_grafo"] is True


def test_alerta_grave_exige_justificativa(sv, medico, grafo_falso):
    grafo_falso.respostas["(atual:Medicamento)"] = [
        {"em_uso": "Varfarina", "novo": "AAS", "gravidade": "grave", "efeito": "sangramento"}
    ]
    prescricao = [{"medicamento_id": "med-002", "dose": "100 mg", "via": "VO", "frequencia": "1x", "duracao_dias": 30}]
    _iniciar(sv, medico)
    with pytest.raises(ValidacaoErro, match="alertas GRAVES"):
        sv.prontuario.registrar_atendimento(medico, _dados(prescricoes=prescricao))

    resultado = sv.prontuario.registrar_atendimento(
        medico, _dados(prescricoes=prescricao, justificativa_alertas="Benefício supera o risco; INR monitorado."))
    salvo = sv.db.atendimentos.find_one({"_id": resultado["id"]})
    assert salvo["alertas_reconhecidos"]["justificativa"].startswith("Benefício")


def test_verificacao_indisponivel_tambem_exige_justificativa(sv, medico, grafo_falso):
    grafo_falso.falhar = True
    prescricao = [{"medicamento_id": "med-005", "dose": "750 mg", "duracao_dias": 5}]
    _iniciar(sv, medico)
    with pytest.raises(ValidacaoErro, match="indisponível"):
        sv.prontuario.registrar_atendimento(medico, _dados(prescricoes=prescricao))


def test_enfermeiro_nao_prescreve(sv, enfermeiro):
    from prontuario.core.errors import PermissaoNegada
    sv.bloqueio.adquirir(PACIENTE, enfermeiro.login)
    prescricao = [{"medicamento_id": "med-005", "dose": "750 mg"}]
    with pytest.raises(PermissaoNegada):
        sv.prontuario.registrar_atendimento(enfermeiro, _dados(prescricoes=prescricao))


def test_validacoes_de_entrada(sv, medico):
    _iniciar(sv, medico)
    with pytest.raises(ValidacaoErro, match="queixa"):
        sv.prontuario.registrar_atendimento(medico, _dados(queixa_principal=" "))
    with pytest.raises(ValidacaoErro, match="CID-10 desconhecido"):
        sv.prontuario.registrar_atendimento(medico, _dados(diagnosticos=[{"cid": "ZZZ"}]))
    with pytest.raises(ValidacaoErro, match="faixa plausível"):
        sv.prontuario.registrar_atendimento(medico, _dados(sinais_vitais={"spo2": 140}))


def test_adendo_preserva_o_registro_original(sv, medico):
    _iniciar(sv, medico)
    atendimento_id = sv.prontuario.registrar_atendimento(medico, _dados())["id"]
    original = sv.db.atendimentos.find_one({"_id": atendimento_id})["queixa_principal"]

    sv.prontuario.adicionar_adendo(medico, atendimento_id, "Correção: dor iniciou há 3 dias.")
    salvo = sv.db.atendimentos.find_one({"_id": atendimento_id})
    assert salvo["queixa_principal"] == original
    assert salvo["adendos"][0]["texto"].startswith("Correção")
    assert salvo["adendos"][0]["login"] == "dr.carlos"


def test_cadastro_recepcao_cpf_duplicado_e_mascara(sv, recepcao, medico):
    from prontuario.core.errors import ConflitoErro as Conflito
    existente = sv.db.pacientes.find_one({"_id": PACIENTE})
    dados = {"nome": "Paciente Duplicado", "cpf": existente["cpf"], "data_nascimento": agora().date(), "sexo": "F"}
    with pytest.raises(Conflito, match="CPF"):
        sv.pacientes.cadastrar(recepcao, dados)
    achado = sv.pacientes.buscar(recepcao, "maria das")
    assert achado and achado[0]["cpf"].startswith("***")          # recepção não vê o CPF completo
    visto_pelo_medico = sv.pacientes.buscar(medico, "maria das")[0]["cpf"]
    assert visto_pelo_medico.replace(".", "").replace("-", "") == existente["cpf"]   # formatado: 000.000.000-00


def test_busca_nao_registra_o_termo_na_auditoria(sv, medico):
    sv.pacientes.buscar(medico, "maria das")
    registro = sv.db.auditoria.find_one({"acao": "paciente:buscar"})
    assert "maria" not in str(registro).lower()
