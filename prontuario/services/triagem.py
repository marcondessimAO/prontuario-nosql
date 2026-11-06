"""Triagem e fila de atendimento em tempo real (Redis Sorted Set).

Score = prioridade (Manchester) * 10^13 + epoch_ms de chegada:
  * menor score sai primeiro;
  * dentro da mesma cor, vale a ordem de chegada (FIFO);
  * ZPOPMIN é atômico: dois atendentes nunca chamam o mesmo paciente.
"""
from __future__ import annotations

from pymongo.database import Database
from redis import Redis

from ..core import trace
from ..core.errors import NaoEncontrado, ValidacaoErro
from ..core.rbac import Sessao
from ..core.tempo import agora
from .auditoria import AuditoriaService
from .eventos import EventoService

RISCOS = {"vermelho": 0, "laranja": 1, "amarelo": 2, "verde": 3, "azul": 4}
TEMPO_ALVO_MIN = {"vermelho": 0, "laranja": 10, "amarelo": 60, "verde": 120, "azul": 240}
FILA = "triagem:fila"
SEQUENCIA = "triagem:seq"
PESO_RISCO = 10**13
TTL_FICHA_S = 86_400


def _chave_ficha(senha: str) -> str:
    return f"ficha:{senha}"


class TriagemService:
    def __init__(self, db: Database, redis: Redis, auditoria: AuditoriaService, eventos: EventoService) -> None:
        self._db = db
        self._r = redis
        self._audit = auditoria
        self._eventos = eventos

    def entrar_na_fila(self, sessao: Sessao, paciente_id: str, risco: str, queixa: str) -> dict:
        sessao.exigir("triagem:operar")
        if risco not in RISCOS:
            raise ValidacaoErro("Classificação de risco inválida.")
        if not (queixa or "").strip():
            raise ValidacaoErro("Informe a queixa principal da triagem.")
        if not self._db.pacientes.count_documents({"_id": paciente_id}, limit=1):
            raise NaoEncontrado("Paciente não encontrado.")

        senha = f"S{self._r.incr(SEQUENCIA):04d}"
        chegada_ms = int(agora().timestamp() * 1000)
        ficha = {
            "senha": senha, "paciente_id": paciente_id, "risco": risco, "queixa": queixa.strip(),
            "chegada_ms": chegada_ms, "status": "aguardando", "registrado_por": sessao.login,
        }
        pipe = self._r.pipeline()
        pipe.hset(_chave_ficha(senha), mapping=ficha)
        pipe.expire(_chave_ficha(senha), TTL_FICHA_S)
        pipe.zadd(FILA, {senha: RISCOS[risco] * PESO_RISCO + chegada_ms})
        pipe.execute()
        trace.registrar("redis", "ZADD", f"{FILA} {senha} ({risco})")
        self._eventos.publicar("triagem_entrada", senha=senha, risco=risco)
        self._audit.registrar(
            usuario=sessao.login, perfil=sessao.perfil, acao="triagem:entrada", recurso="triagem",
            recurso_id=senha, paciente_id=paciente_id, detalhes={"risco": risco},
        )
        return ficha

    def fila(self, sessao: Sessao) -> list[dict]:
        sessao.exigir("triagem:ver")
        senhas = self._r.zrange(FILA, 0, -1)
        if not senhas:
            return []
        pipe = self._r.pipeline()
        for senha in senhas:
            pipe.hgetall(_chave_ficha(senha))
        fichas = pipe.execute()
        validas = []
        for senha, ficha in zip(senhas, fichas):
            if ficha:
                validas.append(ficha)
            else:  # ficha expirou: limpa a entrada órfã do sorted set
                self._r.zrem(FILA, senha)
        nomes = {
            p["_id"]: p["nome"]
            for p in self._db.pacientes.find({"_id": {"$in": [f["paciente_id"] for f in validas]}}, {"nome": 1})
        }
        agora_ms = int(agora().timestamp() * 1000)
        resultado = []
        for posicao, f in enumerate(validas, start=1):
            espera = (agora_ms - int(f["chegada_ms"])) / 60_000
            resultado.append({
                "posicao": posicao, "senha": f["senha"], "risco": f["risco"],
                "paciente": nomes.get(f["paciente_id"], f["paciente_id"]), "paciente_id": f["paciente_id"],
                "queixa": f["queixa"], "espera_min": round(espera, 1),
                "acima_do_alvo": espera > TEMPO_ALVO_MIN[f["risco"]],
            })
        return resultado

    def chamar_proximo(self, sessao: Sessao) -> dict | None:
        sessao.exigir("triagem:operar")
        while True:
            itens = self._r.zpopmin(FILA, 1)  # remoção atômica do menor score
            if not itens:
                return None
            senha, _ = itens[0]
            ficha = self._r.hgetall(_chave_ficha(senha))
            if ficha:
                break
        trace.registrar("redis", "ZPOPMIN", f"{FILA} -> {senha}")
        self._r.hset(_chave_ficha(senha), mapping={"status": "chamado", "chamado_em": agora().isoformat()})
        contador = f"triagem:chamados:{agora():%Y%m%d}"
        pipe = self._r.pipeline()
        pipe.incr(contador)
        pipe.expire(contador, 172_800)
        pipe.execute()
        self._eventos.publicar("triagem_chamada", senha=senha)
        self._audit.registrar(
            usuario=sessao.login, perfil=sessao.perfil, acao="triagem:chamar", recurso="triagem",
            recurso_id=senha, paciente_id=ficha["paciente_id"],
        )
        nome = self._db.pacientes.find_one({"_id": ficha["paciente_id"]}, {"nome": 1})
        return {**ficha, "paciente": nome["nome"] if nome else ficha["paciente_id"]}

    def tamanho_fila(self) -> int:
        return int(self._r.zcard(FILA))

    def chamados_hoje(self) -> int:
        return int(self._r.get(f"triagem:chamados:{agora():%Y%m%d}") or 0)
