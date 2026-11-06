import pytest

from prontuario.core.errors import AutenticacaoErro, PermissaoNegada, ValidacaoErro
from tests.conftest import SENHA


def test_login_valido_cria_sessao_no_redis_com_ttl(sv):
    sessao = sv.auth.login("dr.carlos", SENHA)
    assert sessao.perfil == "medico"
    assert 0 < sv.redis.ttl(f"sessao:{sessao.token}") <= sv.settings.session_ttl


def test_login_invalido_nao_revela_qual_campo_errou(sv):
    with pytest.raises(AutenticacaoErro, match="inválidos"):
        sv.auth.login("dr.carlos", "senha-errada")
    with pytest.raises(AutenticacaoErro, match="inválidos"):
        sv.auth.login("inexistente", SENHA)


def test_bloqueio_apos_excesso_de_tentativas_mesmo_com_senha_correta(sv):
    for _ in range(sv.settings.login_max_falhas):
        with pytest.raises(AutenticacaoErro):
            sv.auth.login("dr.carlos", "errada")
    with pytest.raises(AutenticacaoErro, match="Muitas tentativas"):
        sv.auth.login("dr.carlos", SENHA)


def test_login_com_sucesso_zera_contador_de_falhas(sv):
    with pytest.raises(AutenticacaoErro):
        sv.auth.login("dr.carlos", "errada")
    sv.auth.login("dr.carlos", SENHA)
    assert sv.redis.get("login:falhas:dr.carlos") is None


def test_validar_renova_ttl_da_sessao(sv, medico):
    sv.redis.expire(f"sessao:{medico.token}", 5)
    assert sv.auth.validar(medico.token) is not None
    assert sv.redis.ttl(f"sessao:{medico.token}") > 5


def test_logout_invalida_token(sv, medico):
    sv.auth.logout(medico.token)
    assert sv.auth.validar(medico.token) is None


def test_token_inexistente_ou_vazio_e_rejeitado(sv):
    assert sv.auth.validar("token-falso") is None
    assert sv.auth.validar(None) is None


def test_senha_nao_e_armazenada_em_texto_puro(sv):
    usuario = sv.db.usuarios.find_one({"login": "dr.carlos"})
    assert SENHA not in str(usuario)
    assert len(usuario["senha_hash"]) == 64 and usuario["salt"]


def test_senha_curta_e_perfil_invalido_sao_recusados(sv):
    with pytest.raises(ValidacaoErro):
        sv.auth.criar_usuario("x", "X", "medico", "curta")
    with pytest.raises(ValidacaoErro):
        sv.auth.criar_usuario("x", "X", "hacker", "SenhaLonga123")


def test_rbac_recepcao_nao_le_prontuario(sv, recepcao):
    with pytest.raises(PermissaoNegada):
        sv.prontuario.resumo(recepcao, "pac-0001")
