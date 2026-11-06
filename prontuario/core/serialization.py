"""Serialização JSON para o cache Redis (datas viram ISO-8601)."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def _padrao(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)  # ObjectId e outros tipos BSON


def para_json(obj: Any) -> str:
    return json.dumps(obj, default=_padrao, ensure_ascii=False)


def normalizar(obj: Any) -> Any:
    """Passa o objeto por um ciclo JSON para que cache hit e miss devolvam o MESMO formato."""
    return json.loads(para_json(obj))
