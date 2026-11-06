"""Cadastro e busca de pacientes (MongoDB) com projeção no grafo."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from uuid import uuid4

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from ..core import trace
from ..core.errors import ConflitoErro, NaoEncontrado, ValidacaoErro
from ..core.rbac import Sessao
from ..core.tempo import agora, idade_em_anos
from ..core.validators import cpf_valido, formatar_cpf, mascarar_cpf, normalizar_texto, somente_digitos
from .auditoria import AuditoriaService
from .cache import CacheClinico
from .eventos import EventoService
from .grafo import GrafoService

SEXOS = ("F", "M", "I")
TIPOS_SANGUINEOS = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "N/I")
LIMITE_BUSCA = 20


def _para_datetime(valor: date | datetime) -> datetime:
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    return datetime(valor.year, valor.month, valor.day, tzinfo=timezone.utc)


class PacienteService:
    def __init__(
        self, db: Database, auditoria: AuditoriaService, cache: CacheClinico,
        grafo: GrafoService, eventos: EventoService,
    ) -> None:
        self._db = db
        self._col = db["pacientes"]
        self._audit = auditoria
        self._cache = cache
        self._grafo = grafo
        self._eventos = eventos

    def cadastrar(self, sessao: Sessao, dados: dict) -> str:
        sessao.exigir("paciente:cadastrar")
        nome = (dados.get("nome") or "").strip()
        if len(nome) < 3:
            raise ValidacaoErro("Informe o nome completo do paciente.")
        cpf = somente_digitos(dados.get("cpf", ""))
        if not cpf_valido(cpf):
            raise ValidacaoErro("CPF inválido.")
        nascimento = dados.get("data_nascimento")
        if not nascimento:
            raise ValidacaoErro("Informe a data de nascimento.")
        nascimento = _para_datetime(nascimento)
        if nascimento > agora():
            raise ValidacaoErro("A data de nascimento não pode estar no futuro.")
        sexo = dados.get("sexo", "I")
        if sexo not in SEXOS:
            raise ValidacaoErro("Sexo inválido.")
        tipo = dados.get("tipo_sanguineo", "N/I")
        if tipo not in TIPOS_SANGUINEOS:
            raise ValidacaoErro("Tipo sanguíneo inválido.")

        documento = {
            "_id": f"pac-{uuid4().hex[:8]}",
            "cpf": cpf,
            "nome": nome,
            "nome_busca": normalizar_texto(nome),
            "data_nascimento": nascimento,
            "sexo": sexo,
            "tipo_sanguineo": tipo,
            "contato": {"telefone": dados.get("telefone", ""), "email": dados.get("email", "")},
            "convenio": dados.get("convenio") or None,
            "alergias": [],
            "familiares": [],
            "consentimento_lgpd": {"aceito": bool(dados.get("consentimento", True)), "data": agora()},
            "criado_em": agora(),
            "atualizado_em": agora(),
            "sync_grafo": False,
        }
        try:
            self._col.insert_one(documento)
        except DuplicateKeyError as exc:
            raise ConflitoErro("Já existe paciente cadastrado com este CPF.") from exc
        trace.registrar("mongo", "INSERT pacientes", documento["_id"])

        self._grafo.sincronizar_paciente(documento)
        self._eventos.publicar("paciente_cadastrado", paciente=documento["_id"])
        self._audit.registrar(
            usuario=sessao.login, perfil=sessao.perfil, acao="paciente:cadastrar",
            recurso="paciente", recurso_id=documento["_id"], paciente_id=documento["_id"],
        )
        return documento["_id"]

    def buscar(self, sessao: Sessao, termo: str) -> list[dict]:
        sessao.exigir("paciente:ver")
        termo = (termo or "").strip()
        if len(termo) < 3:
            raise ValidacaoErro("Digite ao menos 3 caracteres para buscar.")
        digitos = somente_digitos(termo)
        so_numerico = len(digitos) >= 3 and not re.search(r"[^\d.\-\s]", termo)
        if so_numerico:
            filtro = {"cpf": {"$regex": f"^{re.escape(digitos)}"}}
            tipo_busca = "cpf"
        else:
            filtro = {"nome_busca": {"$regex": f"^{re.escape(normalizar_texto(termo))}"}}
            tipo_busca = "nome"
        trace.registrar("mongo", "FIND pacientes", f"índice por {tipo_busca} (prefixo)")
        achados = list(self._col.find(filtro).sort("nome_busca", 1).limit(LIMITE_BUSCA))
        # O termo pode conter CPF: grava-se apenas o TIPO da busca, nunca o termo.
        self._audit.registrar(
            usuario=sessao.login, perfil=sessao.perfil, acao="paciente:buscar", recurso="paciente",
            detalhes={"tipo_busca": tipo_busca, "resultados": len(achados)},
        )
        return [self._visao(sessao, p) for p in achados]

    def obter(self, sessao: Sessao, paciente_id: str) -> dict:
        sessao.exigir("paciente:ver")
        paciente = self._col.find_one({"_id": paciente_id})
        if not paciente:
            raise NaoEncontrado("Paciente não encontrado.")
        self._audit.registrar(
            usuario=sessao.login, perfil=sessao.perfil, acao="paciente:ver", recurso="paciente",
            recurso_id=paciente_id, paciente_id=paciente_id,
        )
        return self._visao(sessao, paciente)

    def atualizar_alergias(self, sessao: Sessao, paciente_id: str, alergias: list[dict]) -> None:
        sessao.exigir("prontuario:escrever")
        for a in alergias:
            if not a.get("substancia") or a.get("gravidade") not in ("leve", "moderada", "grave"):
                raise ValidacaoErro("Cada alergia exige substância e gravidade (leve, moderada ou grave).")
        resultado = self._col.update_one(
            {"_id": paciente_id}, {"$set": {"alergias": alergias, "atualizado_em": agora()}}
        )
        if resultado.matched_count == 0:
            raise NaoEncontrado("Paciente não encontrado.")
        trace.registrar("mongo", "UPDATE pacientes", f"{paciente_id} alergias")
        self._cache.invalidar_paciente(paciente_id)
        self._grafo.sincronizar_paciente(self._col.find_one({"_id": paciente_id}))
        self._audit.registrar(
            usuario=sessao.login, perfil=sessao.perfil, acao="paciente:alergias", recurso="paciente",
            recurso_id=paciente_id, paciente_id=paciente_id, detalhes={"total": len(alergias)},
        )

    @staticmethod
    def _visao(sessao: Sessao, p: dict) -> dict:
        """Projeção de saída: o CPF completo só é exposto a quem tem a permissão."""
        return {
            "_id": p["_id"],
            "nome": p["nome"],
            "idade": idade_em_anos(p["data_nascimento"]),
            "sexo": p["sexo"],
            "tipo_sanguineo": p.get("tipo_sanguineo", "N/I"),
            "cpf": formatar_cpf(p["cpf"]) if sessao.pode("paciente:cpf") else mascarar_cpf(p["cpf"]),
            "contato": p.get("contato", {}),
            "convenio": p.get("convenio"),
            "alergias": p.get("alergias", []),
        }
