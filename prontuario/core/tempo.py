from __future__ import annotations

from datetime import date, datetime, timezone


def agora() -> datetime:
    """Instante atual com fuso (UTC). Todo timestamp do sistema é UTC e tz-aware."""
    return datetime.now(timezone.utc)


def idade_em_anos(nascimento: datetime | date, referencia: datetime | None = None) -> int:
    ref = referencia or agora()
    anos = ref.year - nascimento.year
    if (ref.month, ref.day) < (nascimento.month, nascimento.day):
        anos -= 1
    return anos
