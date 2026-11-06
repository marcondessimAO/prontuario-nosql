"""Prontuário eletrônico: atendimentos, adendos, exames e leitura com cache.

Decisões de modelagem (MongoDB):
  * Um documento por ATENDIMENTO, referenciando o paciente (não um documento
    gigante por paciente): evita o limite de 16 MB e o crescimento ilimitado.
  * Registros clínicos são IMUTÁVEIS: correções entram como `adendos` ($push),
    nunca como edição do texto original (rastreabilidade — CFM 1.821/2007).
  * Exames têm estrutura polimórfica (laboratorial x imagem) no mesmo coleção.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from pymongo.database import Database

from ..core import trace
from ..core.config import Settings
from ..core.errors import NaoEncontrado, ValidacaoErro
from ..core.rbac import Sessao
from ..core.serialization import normalizar
from ..core.tempo import agora
from .auditoria import AuditoriaService
from .bloqueio import BloqueioProntuario
from .cache import CacheClinico, chave_prontuario
from .eventos import EventoService, NotificacaoService
from .grafo import GrafoService

LIMITE_RESUMO = 30
TIPOS_ATENDIMENTO = ("consulta", "retorno", "urgencia", "internacao", "enfermagem")
DESFECHOS = ("alta", "retorno", "internacao", "encaminhamento", "obito", "em_andamento")
FAIXAS_VITAIS = {
    "pa_sistolica": (40, 300), "pa_diastolica": (20, 200), "fc": (20, 260), "fr": (4, 80),
    "temperatura": (30, 45), "spo2": (40, 100), "peso_kg": (0.3, 500), "altura_cm": (30, 260),
}


def _limpar_sinais(sinais: dict | None) -> dict[str, float]:
    """Ignora campos vazios/zero (= não aferido) e valida faixas fisiológicas plausíveis."""
    limpos: dict[str, float] = {}
    for campo, valor in (sinais or {}).items():
        if campo not in FAIXAS_VITAIS or valor in (None, "", 0):
            continue
        try:
            numero = float(valor)
        except (TypeError, ValueError) as exc:
            raise ValidacaoErro(f"Valor inválido para {campo}.") from exc
        minimo, maximo = FAIXAS_VITAIS[campo]
        if not minimo <= numero <= maximo:
            raise ValidacaoErro(f"{campo} fora da faixa plausível ({minimo}–{maximo}).")
        limpos[campo] = numero
    return limpos


def medicamentos_em_uso(atendimentos: list[dict], referencia: datetime) -> list[dict]:
    """Prescrições vigentes (data + duração >= hoje), a mais recente por medicamento."""
    ativos: dict[str, dict] = {}
    for a in sorted(atendimentos, key=lambda x: x["data_hora"], reverse=True):
        for p in a.get("prescricoes", []):
            dias = p.get("duracao_dias")
            fim = a["data_hora"] + timedelta(days=dias) if dias else None
            if (fim is None or fim >= referencia) and p["medicamento_id"] not in ativos:
                ativos[p["medicamento_id"]] = {
                    "medicamento": p["nome"], "dose": p.get("dose", ""), "frequencia": p.get("frequencia", ""),
                    "desde": a["data_hora"], "ate": fim,
                }
    return list(ativos.values())


class ProntuarioService:
    def __init__(
        self, db: Database, auditoria: AuditoriaService, cache: CacheClinico, grafo: GrafoService,
        bloqueio: BloqueioProntuario, eventos: EventoService, notificacoes: NotificacaoService,
        settings: Settings,
    ) -> None:
        self._db = db
        self._audit = auditoria
        self._cache = cache
        self._grafo = grafo
        self._lock = bloqueio
        self._eventos = eventos
        self._notif = notificacoes
        self._ttl = settings.cache_prontuario_ttl

    # ------------------------------------------------------------------ #
    # Leitura (cache-aside)
    # ------------------------------------------------------------------ #
    def resumo(self, sessao: Sessao, paciente_id: str) -> dict[str, Any]:
        sessao.exigir("prontuario:ler")
        # Auditoria ANTES do cache: um cache hit não pode esconder um acesso.
        self._audit.registrar(
            usuario=sessao.login, perfil=sessao.perfil, acao="prontuario:ler", recurso="prontuario",
            recurso_id=paciente_id, paciente_id=paciente_id,
        )
        chave = chave_prontuario(paciente_id)
        em_cache = self._cache.obter(chave)
        if em_cache is not None:
            return {**em_cache, "origem": "redis"}

        trace.registrar("mongo", "FIND prontuário", f"paciente={paciente_id} (cache miss)")
        paciente = self._db.pacientes.find_one({"_id": paciente_id}, {"cpf": 0, "nome_busca": 0})
        if not paciente:
            raise NaoEncontrado("Paciente não encontrado.")
        atendimentos = list(
            self._db.atendimentos.find({"paciente_id": paciente_id}).sort("data_hora", -1).limit(LIMITE_RESUMO)
        )
        exames = list(
            self._db.exames.find({"paciente_id": paciente_id}).sort("data_coleta", -1).limit(LIMITE_RESUMO)
        )
        ids = {a["profissional_id"] for a in atendimentos}
        profs = {
            p["_id"]: p for p in self._db.profissionais.find(
                {"_id": {"$in": list(ids)}}, {"nome": 1, "especialidade": 1}
            )
        }
        for a in atendimentos:
            a["profissional"] = profs.get(a["profissional_id"], {"nome": a["profissional_id"]})
        # normalizar(): datas -> ISO; garante o MESMO formato em cache hit e miss
        resultado = normalizar({
            "paciente": paciente,
            "atendimentos": atendimentos,
            "exames": exames,
            "em_uso": medicamentos_em_uso(atendimentos, agora()),
        })
        self._cache.gravar(chave, resultado, self._ttl)
        return {**resultado, "origem": "mongodb"}

    def buscar_texto(self, sessao: Sessao, paciente_id: str, termo: str) -> list[dict]:
        sessao.exigir("prontuario:ler")
        if len(termo.strip()) < 3:
            raise ValidacaoErro("Digite ao menos 3 caracteres.")
        trace.registrar("mongo", "FIND $text", "índice de texto (português)")
        self._audit.registrar(
            usuario=sessao.login, perfil=sessao.perfil, acao="prontuario:buscar_texto", recurso="prontuario",
            recurso_id=paciente_id, paciente_id=paciente_id,
        )
        cursor = self._db.atendimentos.find(
            {"paciente_id": paciente_id, "$text": {"$search": termo}},
            {"score": {"$meta": "textScore"}, "data_hora": 1, "queixa_principal": 1, "evolucao": 1},
        ).sort([("score", {"$meta": "textScore"})]).limit(20)
        return normalizar(list(cursor))

    # ------------------------------------------------------------------ #
    # Escrita
    # ------------------------------------------------------------------ #
    def registrar_atendimento(self, sessao: Sessao, dados: dict) -> dict[str, Any]:
        sessao.exigir("prontuario:escrever")
        paciente_id = dados.get("paciente_id", "")
        if not sessao.profissional_id:
            raise ValidacaoErro("Seu usuário não está vinculado a um profissional de saúde.")
        if not self._db.pacientes.count_documents({"_id": paciente_id}, limit=1):
            raise NaoEncontrado("Paciente não encontrado.")
        self._lock.exigir_posse(paciente_id, sessao.login)

        tipo = dados.get("tipo", "consulta")
        if tipo not in TIPOS_ATENDIMENTO:
            raise ValidacaoErro("Tipo de atendimento inválido.")
        queixa = (dados.get("queixa_principal") or "").strip()
        if len(queixa) < 3:
            raise ValidacaoErro("Informe a queixa principal.")
        desfecho = dados.get("desfecho", "alta")
        if desfecho not in DESFECHOS:
            raise ValidacaoErro("Desfecho inválido.")

        diagnosticos = self._resolver_diagnosticos(dados.get("diagnosticos", []))
        prescricoes = self._resolver_prescricoes(sessao, dados.get("prescricoes", []))
        destino = dados.get("encaminhado_para") or None
        if destino and not self._db.profissionais.count_documents({"_id": destino}, limit=1):
            raise ValidacaoErro("Profissional de destino do encaminhamento não existe.")

        # Apoio à decisão no grafo: alertas graves exigem justificativa registrada.
        verificacao = self._grafo.verificar_prescricao(paciente_id, [p["medicamento_id"] for p in prescricoes])
        graves = [a for a in verificacao["alertas"] if a["gravidade"] == "grave"]
        justificativa = (dados.get("justificativa_alertas") or "").strip()
        if prescricoes and (graves or not verificacao["verificado"]) and len(justificativa) < 10:
            motivo = "há alertas GRAVES" if graves else "a verificação de segurança está indisponível"
            raise ValidacaoErro(
                f"Não é possível salvar: {motivo}. Registre uma justificativa clínica (mín. 10 caracteres)."
            )

        agora_ = agora()
        documento = {
            "_id": f"at-{uuid4().hex[:10]}",
            "paciente_id": paciente_id,
            "profissional_id": sessao.profissional_id,
            "tipo": tipo,
            "data_hora": agora_,
            "queixa_principal": queixa,
            "anamnese": {"historia_doenca_atual": (dados.get("historia") or "").strip()},
            "sinais_vitais": _limpar_sinais(dados.get("sinais_vitais")),
            "exame_fisico": (dados.get("exame_fisico") or "").strip(),
            "diagnosticos": diagnosticos,
            "prescricoes": prescricoes,
            "exames_solicitados": list(dados.get("exames_solicitados", [])),
            "evolucao": (dados.get("evolucao") or "").strip(),
            "desfecho": desfecho,
            "encaminhado_para": destino,
            "alertas_reconhecidos": {"justificativa": justificativa, "alertas": [a["mensagem"] for a in verificacao["alertas"]]}
            if verificacao["alertas"] or not verificacao["verificado"] else None,
            "adendos": [],
            "assinatura": {"login": sessao.login, "data_hora": agora_},
            "criado_em": agora_,
            "sync_grafo": False,
        }
        self._db.atendimentos.insert_one(documento)
        trace.registrar("mongo", "INSERT atendimentos", documento["_id"])

        sincronizado = self._grafo.sincronizar_atendimento(documento)
        self._cache.invalidar_paciente(paciente_id)
        self._eventos.publicar("atendimento_registrado", atendimento=documento["_id"], tipo=tipo)
        if destino:
            self._notif.enviar(destino, "Novo encaminhamento", f"Atendimento {documento['_id']} encaminhado a você.")
        self._audit.registrar(
            usuario=sessao.login, perfil=sessao.perfil, acao="prontuario:escrever", recurso="atendimento",
            recurso_id=documento["_id"], paciente_id=paciente_id,
            detalhes={"prescricoes": len(prescricoes), "alertas": len(verificacao["alertas"]),
                      "verificado": verificacao["verificado"]},
        )
        self._lock.liberar(paciente_id, sessao.login)
        return {"id": documento["_id"], "alertas": verificacao["alertas"], "sync_grafo": sincronizado}

    def adicionar_adendo(self, sessao: Sessao, atendimento_id: str, texto: str) -> None:
        sessao.exigir("prontuario:adendo")
        texto = (texto or "").strip()
        if len(texto) < 5:
            raise ValidacaoErro("O adendo deve ter ao menos 5 caracteres.")
        atendimento = self._db.atendimentos.find_one({"_id": atendimento_id}, {"paciente_id": 1})
        if not atendimento:
            raise NaoEncontrado("Atendimento não encontrado.")
        self._db.atendimentos.update_one({"_id": atendimento_id}, {"$push": {"adendos": {
            "texto": texto, "login": sessao.login, "nome": sessao.nome, "data_hora": agora(),
        }}})
        trace.registrar("mongo", "UPDATE $push adendos", atendimento_id)
        paciente_id = atendimento["paciente_id"]
        self._cache.invalidar_paciente(paciente_id)
        self._audit.registrar(
            usuario=sessao.login, perfil=sessao.perfil, acao="prontuario:adendo", recurso="atendimento",
            recurso_id=atendimento_id, paciente_id=paciente_id,
        )

    def registrar_exame(self, sessao: Sessao, dados: dict) -> str:
        sessao.exigir("prontuario:escrever")
        if dados.get("tipo") not in ("laboratorial", "imagem"):
            raise ValidacaoErro("Tipo de exame inválido.")
        if not dados.get("nome"):
            raise ValidacaoErro("Informe o nome do exame.")
        if not self._db.pacientes.count_documents({"_id": dados["paciente_id"]}, limit=1):
            raise NaoEncontrado("Paciente não encontrado.")
        documento = {
            "_id": f"ex-{uuid4().hex[:10]}",
            "paciente_id": dados["paciente_id"],
            "atendimento_id": dados.get("atendimento_id"),
            "tipo": dados["tipo"],
            "nome": dados["nome"],
            "data_coleta": dados.get("data_coleta") or agora(),
            "status": "concluido",
            "resultados": dados.get("resultados", []),   # laboratorial: lista de analitos
            "laudo": dados.get("laudo", ""),             # imagem: texto do laudo
            "anexos": dados.get("anexos", []),           # referência a arquivos (GridFS/S3)
            "criado_em": agora(),
        }
        self._db.exames.insert_one(documento)
        trace.registrar("mongo", "INSERT exames", documento["_id"])
        self._cache.invalidar_paciente(dados["paciente_id"])
        if dados.get("atendimento_id"):
            origem = self._db.atendimentos.find_one({"_id": dados["atendimento_id"]}, {"profissional_id": 1})
            if origem:
                self._notif.enviar(origem["profissional_id"], "Resultado de exame", f"{documento['nome']} disponível.")
        self._audit.registrar(
            usuario=sessao.login, perfil=sessao.perfil, acao="exame:registrar", recurso="exame",
            recurso_id=documento["_id"], paciente_id=dados["paciente_id"],
        )
        return documento["_id"]

    # ------------------------------------------------------------------ #
    # Auxiliares de validação contra os catálogos
    # ------------------------------------------------------------------ #
    def _resolver_diagnosticos(self, itens: list[dict]) -> list[dict]:
        if not itens:
            return []
        codigos = [i["cid"] for i in itens]
        catalogo = {c["_id"]: c["descricao"] for c in self._db.cid10.find({"_id": {"$in": codigos}})}
        faltando = [c for c in codigos if c not in catalogo]
        if faltando:
            raise ValidacaoErro(f"CID-10 desconhecido: {', '.join(faltando)}")
        return [
            {"cid": i["cid"], "descricao": catalogo[i["cid"]], "tipo": i.get("tipo", "secundario")}
            for i in itens
        ]

    def _resolver_prescricoes(self, sessao: Sessao, itens: list[dict]) -> list[dict]:
        if not itens:
            return []
        sessao.exigir("prescricao:criar")
        ids = [i["medicamento_id"] for i in itens]
        if len(set(ids)) != len(ids):
            raise ValidacaoErro("Medicamento repetido na mesma prescrição.")
        catalogo = {m["_id"]: m for m in self._db.medicamentos.find({"_id": {"$in": ids}})}
        faltando = [i for i in ids if i not in catalogo]
        if faltando:
            raise ValidacaoErro(f"Medicamento não cadastrado: {', '.join(faltando)}")
        prescricoes = []
        for i in itens:
            dias = int(i.get("duracao_dias") or 0)
            if dias < 0 or dias > 365:
                raise ValidacaoErro("Duração do tratamento deve estar entre 0 e 365 dias.")
            if not (i.get("dose") or "").strip():
                raise ValidacaoErro(f"Informe a dose de {catalogo[i['medicamento_id']]['nome']}.")
            prescricoes.append({
                "medicamento_id": i["medicamento_id"],
                "nome": catalogo[i["medicamento_id"]]["nome"],
                "dose": i["dose"].strip(),
                "via": i.get("via", "VO"),
                "frequencia": i.get("frequencia", ""),
                "duracao_dias": dias or None,
            })
        return prescricoes
