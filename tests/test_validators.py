import pytest

from prontuario.core.validators import (
    calcular_dv_cpf, cpf_valido, formatar_cpf, mascarar_cpf, normalizar_texto, somente_digitos,
)


def test_cpf_conhecido_e_valido():
    assert cpf_valido("529.982.247-25")


@pytest.mark.parametrize("cpf", ["111.111.111-11", "123.456.789-00", "123", "", "abcdefghijk"])
def test_cpf_invalido(cpf):
    assert not cpf_valido(cpf)


def test_dv_calculado_fecha_com_validacao():
    base = "123456789"
    assert cpf_valido(base + calcular_dv_cpf(base))


def test_mascara_expoe_apenas_o_miolo():
    assert mascarar_cpf("52998224725") == "***.982.247-**"
    assert mascarar_cpf("curto") == "***"


def test_formatacao_e_digitos():
    assert formatar_cpf("52998224725") == "529.982.247-25"
    assert somente_digitos("529.982.247-25") == "52998224725"


def test_normalizar_remove_acentos_e_caixa():
    assert normalizar_texto("  José  AntÔnio ") == "jose antonio"
