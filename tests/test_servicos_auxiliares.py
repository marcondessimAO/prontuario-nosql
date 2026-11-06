import pytest

from prontuario.core.errors import PermissaoNegada, ValidacaoErro
from prontuario.services.eventos import NOTIF_MAX


def test_eventos_ficam_em_ordem_do_mais_recente_e_aceitam_campo_tipo(sv):
    sv.eventos.publicar("a", tipo="consulta")
    sv.eventos.publicar("b")
    recentes = sv.eventos.recentes(5)
    assert [e["evento"] for e in recentes] == ["b", "a"]
    assert recentes[1]["tipo"] == "consulta"


def test_notificacoes_contam_listam_limitam_e_zeram(sv):
    for n in range(NOTIF_MAX + 5):
        sv.notificacoes.enviar("prof-001", f"t{n}", "corpo")
    assert sv.notificacoes.nao_lidas("prof-001") == NOTIF_MAX + 5
    assert len(sv.redis.lrange("notif:lista:prof-001", 0, -1)) == NOTIF_MAX      # LTRIM mantém só as mais novas
    assert sv.notificacoes.listar("prof-001", 3)[0]["titulo"] == f"t{NOTIF_MAX + 4}"
    sv.notificacoes.marcar_lidas("prof-001")
    assert sv.notificacoes.nao_lidas("prof-001") == 0
    assert sv.notificacoes.nao_lidas("") == 0


def test_catalogo_so_consulta_o_mongo_uma_vez(sv):
    primeira = sv.catalogos.medicamentos()
    antes = sv.cache.metricas()["hits"]
    assert sv.catalogos.medicamentos() == primeira
    assert sv.cache.metricas()["hits"] == antes + 1
    assert any(m["_id"] == "med-001" for m in primeira)


def test_verificacao_ordena_por_gravidade_e_inclui_alergia(sv, grafo_falso):
    grafo_falso.respostas = {
        "ALERGICO_A]->(alvo)": [{"medicamento": "Amoxicilina", "tipo": "Classe", "alvo": "Penicilinas"}],
        "(atual:Medicamento)": [{"em_uso": "X", "novo": "Y", "gravidade": "leve", "efeito": "e1"}],
        "a.id < b.id": [{"a": "A", "b": "B", "gravidade": "moderada", "efeito": "e2"}],
    }
    resultado = sv.grafo.verificar_prescricao("pac-0001", ["med-007", "med-002"])
    assert [a["gravidade"] for a in resultado["alertas"]] == ["grave", "moderada", "leve"]
    assert resultado["alertas"][0]["tipo"] == "alergia"
    assert sv.grafo.verificar_prescricao("pac-0001", []) == {"verificado": True, "alertas": []}


def test_atualizar_alergias_invalida_cache_e_valida_gravidade(sv, medico):
    sv.prontuario.resumo(medico, "pac-0002")
    sv.pacientes.atualizar_alergias(
        medico, "pac-0002", [{"substancia": "Látex", "reacao": "urticária", "gravidade": "moderada"}])
    assert sv.redis.get("cache:prontuario:pac-0002") is None
    assert sv.db.pacientes.find_one({"_id": "pac-0002"})["alergias"][0]["substancia"] == "Látex"
    with pytest.raises(ValidacaoErro):
        sv.pacientes.atualizar_alergias(medico, "pac-0002", [{"substancia": "X", "gravidade": "terrível"}])


def test_registrar_exame_notifica_quem_atendeu_e_invalida_cache(sv, medico, enfermeiro):
    atendimento = sv.db.atendimentos.find_one({"paciente_id": "pac-0002"})
    sv.prontuario.resumo(medico, "pac-0002")
    sv.prontuario.registrar_exame(enfermeiro, {
        "paciente_id": "pac-0002", "atendimento_id": atendimento["_id"], "tipo": "laboratorial",
        "nome": "Glicemia", "resultados": [{"analito": "Glicose", "valor": 98, "unidade": "mg/dL"}],
    })
    assert sv.notificacoes.nao_lidas(atendimento["profissional_id"]) == 1
    assert sv.redis.get("cache:prontuario:pac-0002") is None
    with pytest.raises(ValidacaoErro):
        sv.prontuario.registrar_exame(enfermeiro, {"paciente_id": "pac-0002", "tipo": "xyz", "nome": "x"})


def test_painel_agrega_no_mongo_e_serve_do_cache_na_segunda_vez(sv):
    admin = sv.auth.login("admin", "Senha12345")
    primeiro = sv.indicadores.painel(admin)
    segundo = sv.indicadores.painel(admin)
    assert primeiro["origem_mongo"] == "mongodb" and segundo["origem_mongo"] == "redis"
    assert primeiro["mongo"]["total_pacientes"] == 30
    assert primeiro["ocupacao"] and "taxa_acerto" in primeiro["cache"]


def test_painel_exige_permissao(sv, recepcao):
    with pytest.raises(PermissaoNegada):
        sv.indicadores.painel(recepcao)


def test_auditoria_filtra_por_usuario_e_acao(sv, medico):
    sv.prontuario.resumo(medico, "pac-0001")
    sv.prontuario.resumo(medico, "pac-0002")
    leituras = sv.auditoria.listar(usuario="dr.carlos", acao="prontuario:ler")
    assert len(leituras) == 2
    assert {r["paciente_id"] for r in leituras} == {"pac-0001", "pac-0002"}
    assert any(c["acao"] == "auth:login" for c in sv.auditoria.contagem_por_acao())
