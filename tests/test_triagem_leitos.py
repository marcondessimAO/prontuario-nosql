import pytest

from prontuario.core.errors import ConflitoErro, NaoEncontrado, PermissaoNegada


def test_fila_ordena_por_risco_e_depois_por_chegada(sv, enfermeiro):
    sv.triagem.entrar_na_fila(enfermeiro, "pac-0001", "verde", "tosse")
    sv.triagem.entrar_na_fila(enfermeiro, "pac-0002", "azul", "dor leve")
    sv.triagem.entrar_na_fila(enfermeiro, "pac-0003", "vermelho", "parada")
    sv.triagem.entrar_na_fila(enfermeiro, "pac-0004", "verde", "febre")

    ordem = [f["senha"] for f in sv.triagem.fila(enfermeiro)]
    assert ordem == ["S0003", "S0001", "S0004", "S0002"]   # vermelho, verde(1º), verde(2º), azul


def test_chamar_proximo_remove_da_fila_e_conta(sv, enfermeiro):
    sv.triagem.entrar_na_fila(enfermeiro, "pac-0001", "amarelo", "dor torácica")
    sv.triagem.entrar_na_fila(enfermeiro, "pac-0002", "laranja", "dispneia")

    primeiro = sv.triagem.chamar_proximo(enfermeiro)
    assert primeiro["risco"] == "laranja" and primeiro["status"] == "aguardando"
    assert sv.triagem.tamanho_fila() == 1 and sv.triagem.chamados_hoje() == 1
    sv.triagem.chamar_proximo(enfermeiro)
    assert sv.triagem.chamar_proximo(enfermeiro) is None


def test_triagem_valida_risco_e_paciente(sv, enfermeiro, medico):
    from prontuario.core.errors import ValidacaoErro
    with pytest.raises(ValidacaoErro):
        sv.triagem.entrar_na_fila(enfermeiro, "pac-0001", "roxo", "x")
    with pytest.raises(NaoEncontrado):
        sv.triagem.entrar_na_fila(enfermeiro, "pac-9999", "verde", "x")
    with pytest.raises(PermissaoNegada):
        sv.triagem.entrar_na_fila(medico, "pac-0001", "verde", "x")


def test_ficha_expirada_e_removida_da_fila(sv, enfermeiro):
    ficha = sv.triagem.entrar_na_fila(enfermeiro, "pac-0001", "verde", "tosse")
    sv.redis.delete(f"ficha:{ficha['senha']}")
    assert sv.triagem.fila(enfermeiro) == []
    assert sv.triagem.tamanho_fila() == 0


def test_internar_reserva_leito_atomicamente(sv, enfermeiro):
    sv.leitos.internar(enfermeiro, "pac-0001", "UTI-02", "pós-operatório")
    with pytest.raises(ConflitoErro, match="ocupado"):
        sv.leitos.internar(enfermeiro, "pac-0002", "UTI-02", "outro")
    assert sv.redis.hget("leitos:ocupantes", "UTI-02") == "pac-0001"
    uti = next(a for a in sv.leitos.ocupacao_por_ala() if a["ala"] == "UTI")
    assert uti["ocupados"] >= 1 and uti["livres"] == uti["total"] - uti["ocupados"]


def test_alta_libera_leito_e_encerra_internacao(sv, enfermeiro):
    sv.leitos.internar(enfermeiro, "pac-0001", "PED-01", "teste")
    sv.leitos.dar_alta(enfermeiro, "pac-0001")
    assert sv.redis.hget("leitos:ocupantes", "PED-01") is None
    internacao = sv.db.internacoes.find_one({"paciente_id": "pac-0001", "leito_id": "PED-01"})
    assert internacao["ativa"] is False and internacao["saida"] is not None
    with pytest.raises(NaoEncontrado):
        sv.leitos.dar_alta(enfermeiro, "pac-0001")


def test_estado_do_redis_e_reconstruido_a_partir_do_mongo(sv):
    sv.redis.flushall()
    ativas = sv.db.internacoes.count_documents({"ativa": True})
    assert sv.leitos.reconstruir_estado() == ativas > 0
    assert sv.redis.hlen("leitos:ocupantes") == ativas


def test_medico_nao_opera_leitos(sv, medico):
    with pytest.raises(PermissaoNegada):
        sv.leitos.internar(medico, "pac-0001", "UTI-03", "x")
