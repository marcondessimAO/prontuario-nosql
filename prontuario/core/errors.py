"""Exceções de domínio. A UI converte todas em mensagens amigáveis."""


class DominioErro(Exception):
    """Base de todos os erros esperados do domínio."""


class ValidacaoErro(DominioErro):
    """Dado de entrada inválido."""


class NaoEncontrado(DominioErro):
    """Recurso inexistente."""


class ConflitoErro(DominioErro):
    """Conflito de concorrência (lock, leito ocupado, CPF duplicado...)."""


class AutenticacaoErro(DominioErro):
    """Credenciais inválidas, sessão expirada ou conta bloqueada."""


class PermissaoNegada(DominioErro):
    """Perfil sem permissão para a operação."""
