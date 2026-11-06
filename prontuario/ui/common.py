"""Utilitários compartilhados pelas páginas Streamlit."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import pandas as pd
import streamlit as st
from neo4j.exceptions import DriverError, Neo4jError
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

from ..core.errors import DominioErro
from ..core.rbac import Sessao
from ..services.container import Servicos, montar

log = logging.getLogger(__name__)
ROTULO_RISCO = {
    "vermelho": "Vermelho", "laranja": "Laranja", "amarelo": "Amarelo", "verde": "Verde", "azul": "Azul",
}


@st.cache_resource(show_spinner="Conectando aos bancos de dados…")
def servicos() -> Servicos:
    return montar()


def sessao_atual() -> Sessao | None:
    token = st.session_state.get("token")
    if not token:
        return None
    sessao = servicos().auth.validar(token)
    if sessao is None:
        st.session_state.pop("token", None)
        st.session_state["aviso"] = "Sua sessão expirou. Faça login novamente."
    return sessao


def exigir(sessao: Sessao, permissao: str) -> None:
    if not sessao.pode(permissao):
        st.error("Seu perfil não tem acesso a esta área.")
        st.stop()


@contextmanager
def capturar_erros() -> Iterator[None]:
    """Converte falhas em mensagens amigáveis; detalhes técnicos vão para o log do servidor."""
    try:
        yield
    except DominioErro as exc:
        st.error(str(exc))
    except PyMongoError:
        log.exception("Falha no MongoDB")
        st.error("MongoDB indisponível ou operação recusada. Tente novamente.")
    except RedisError:
        log.exception("Falha no Redis")
        st.error("Redis indisponível. Tente novamente.")
    except (Neo4jError, DriverError):
        log.exception("Falha no Neo4j")
        st.error("Neo4j indisponível. Recursos de grafo estão temporariamente fora do ar.")
    except Exception:  # noqa: BLE001 — última barreira: nunca exibir stack trace ao usuário
        log.exception("Erro inesperado")
        st.error("Erro inesperado. A equipe técnica foi notificada nos logs.")


def seletor_paciente(sessao: Sessao, chave: str = "paciente_id") -> str | None:
    """Busca por nome/CPF e guarda o paciente escolhido em st.session_state[chave]."""
    termo = st.text_input("Buscar paciente (nome ou CPF, mínimo de 3 caracteres)", key=f"{chave}_termo")
    if termo and len(termo.strip()) >= 3:
        with capturar_erros():
            achados = servicos().pacientes.buscar(sessao, termo)
            if not achados:
                st.info("Nenhum paciente encontrado.")
            else:
                opcoes = {p["_id"]: f"{p['nome']} · {p['cpf']} · {p['idade']} anos" for p in achados}
                atual = st.session_state.get(chave)
                indice = list(opcoes).index(atual) if atual in opcoes else 0
                st.session_state[chave] = st.selectbox(
                    "Resultados", list(opcoes), index=indice, format_func=opcoes.get, key=f"{chave}_sel"
                )
    return st.session_state.get(chave)


def tabela(linhas: list[dict], cores: tuple[str, dict[str, str]] | None = None, **kwargs) -> None:
    """Tabela padrão. `cores=(coluna, {valor_minusculo: cor_de_fundo})` colore uma coluna categórica."""
    if not linhas:
        st.caption("Sem registros.")
        return
    quadro = pd.DataFrame(linhas)
    if cores:
        coluna, mapa = cores
        quadro = quadro.style.map(
            lambda v: f"background-color: {mapa.get(str(v).lower(), '')}; color: #1B2733", subset=[coluna]
        )
    st.dataframe(quadro, use_container_width=True, hide_index=True, **kwargs)


def formatar_data(iso: str | None) -> str:
    if not iso:
        return "—"
    return pd.to_datetime(iso).strftime("%d/%m/%Y %H:%M")
