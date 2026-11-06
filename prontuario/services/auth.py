"""Autenticação: usuários no MongoDB, sessões e proteção contra força bruta no Redis."""
from __future__ import annotations

import hashlib
import hmac
import secrets

from pymongo.database import Database
from redis import Redis

from ..core import trace
from ..core.config import Settings
from ..core.errors import AutenticacaoErro, ValidacaoErro
from ..core.rbac import PERFIS, Sessao
from ..core.tempo import agora
from .auditoria import AuditoriaService


def hash_senha(senha: str, salt_hex: str | None = None, iteracoes: int = 600_000) -> tuple[str, str]:
    """PBKDF2-HMAC-SHA256 com salt aleatório por usuário (somente stdlib)."""
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    derivado = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, iteracoes)
    return derivado.hex(), salt.hex()


def _chave_sessao(token: str) -> str:
    return f"sessao:{token}"


class AuthService:
    def __init__(self, db: Database, redis: Redis, auditoria: AuditoriaService, settings: Settings) -> None:
        self._users = db["usuarios"]
        self._r = redis
        self._audit = auditoria
        self._s = settings

    def criar_usuario(
        self, login: str, nome: str, perfil: str, senha: str, profissional_id: str = ""
    ) -> None:
        if perfil not in PERFIS:
            raise ValidacaoErro(f"Perfil inválido: {perfil}")
        if len(senha) < 8:
            raise ValidacaoErro("A senha deve ter ao menos 8 caracteres.")
        senha_hash, salt = hash_senha(senha, iteracoes=self._s.pbkdf2_iteracoes)
        login = login.strip().lower()
        self._users.replace_one(
            {"_id": f"usr-{login}"},
            {
                "_id": f"usr-{login}", "login": login, "nome": nome, "perfil": perfil,
                "profissional_id": profissional_id, "senha_hash": senha_hash, "salt": salt,
                "iteracoes": self._s.pbkdf2_iteracoes, "ativo": True, "criado_em": agora(),
            },
            upsert=True,
        )

    def login(self, login: str, senha: str) -> Sessao:
        chave = (login or "").strip().lower()
        if not chave or not senha:
            raise AutenticacaoErro("Informe usuário e senha.")

        k_falhas = f"login:falhas:{chave}"
        if int(self._r.get(k_falhas) or 0) >= self._s.login_max_falhas:
            espera = max(self._r.ttl(k_falhas), 1) // 60 + 1
            trace.registrar("redis", "GET", f"{k_falhas} (bloqueado)")
            raise AutenticacaoErro(f"Muitas tentativas inválidas. Tente novamente em ~{espera} min.")

        usuario = self._users.find_one({"login": chave, "ativo": {"$ne": False}})
        if usuario:
            calculado, _ = hash_senha(senha, usuario["salt"], usuario["iteracoes"])
            valido = hmac.compare_digest(calculado, usuario["senha_hash"])
        else:
            hash_senha(senha, iteracoes=self._s.pbkdf2_iteracoes)  # iguala o tempo de resposta
            valido = False

        if not valido:
            pipe = self._r.pipeline()
            pipe.incr(k_falhas)
            pipe.expire(k_falhas, self._s.login_janela_bloqueio)
            pipe.execute()
            trace.registrar("redis", "INCR+EXPIRE", f"{k_falhas} (falha de login)")
            self._audit.registrar(usuario=chave, perfil="-", acao="auth:falha", recurso="sessao")
            raise AutenticacaoErro("Usuário ou senha inválidos.")

        self._r.delete(k_falhas)
        token = secrets.token_urlsafe(32)
        dados = {
            "login": usuario["login"], "nome": usuario["nome"], "perfil": usuario["perfil"],
            "profissional_id": usuario.get("profissional_id", ""),
            "criada_em": agora().isoformat(timespec="seconds"),
        }
        pipe = self._r.pipeline()
        pipe.hset(_chave_sessao(token), mapping=dados)
        pipe.expire(_chave_sessao(token), self._s.session_ttl)
        pipe.execute()
        trace.registrar("redis", "HSET+EXPIRE", f"sessao:*** ttl={self._s.session_ttl}s")
        self._audit.registrar(usuario=chave, perfil=usuario["perfil"], acao="auth:login", recurso="sessao")
        return Sessao(token, dados["login"], dados["nome"], dados["perfil"], dados["profissional_id"])

    def validar(self, token: str | None) -> Sessao | None:
        """Valida o token e renova o TTL (sessão deslizante)."""
        if not token:
            return None
        dados = self._r.hgetall(_chave_sessao(token))
        if not dados:
            return None
        self._r.expire(_chave_sessao(token), self._s.session_ttl)
        return Sessao(token, dados["login"], dados["nome"], dados["perfil"], dados.get("profissional_id", ""))

    def logout(self, token: str) -> None:
        sessao = self.validar(token)
        self._r.delete(_chave_sessao(token))
        trace.registrar("redis", "DEL", "sessao:*** (logout)")
        if sessao:
            self._audit.registrar(usuario=sessao.login, perfil=sessao.perfil, acao="auth:logout", recurso="sessao")
