"""MongoDB: conexão, validação de schema ($jsonSchema) e índices.

MongoDB é a FONTE DA VERDADE do prontuário. Redis e Neo4j guardam apenas dados
derivados (cache, estado efêmero e projeção em grafo) e podem ser reconstruídos.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from pymongo import ASCENDING, DESCENDING, TEXT, MongoClient
from pymongo.database import Database

from ..core.config import get_settings


@lru_cache(maxsize=1)
def get_client() -> MongoClient:
    s = get_settings()
    # tz_aware=True: datas voltam como datetime UTC com fuso (nunca "naive")
    return MongoClient(s.mongo_uri, tz_aware=True, serverSelectionTimeoutMS=3000, appname="prontuario-app")


def get_db() -> Database:
    return get_client()[get_settings().mongo_db]


# --------------------------------------------------------------------------- #
# Validação de schema no próprio banco (defesa em profundidade)
# --------------------------------------------------------------------------- #
_ENUM_GRAVIDADE = ["leve", "moderada", "grave"]

_SINAIS_VITAIS = {
    "bsonType": "object",
    "properties": {
        "pa_sistolica": {"bsonType": "number", "minimum": 40, "maximum": 300},
        "pa_diastolica": {"bsonType": "number", "minimum": 20, "maximum": 200},
        "fc": {"bsonType": "number", "minimum": 20, "maximum": 260},
        "fr": {"bsonType": "number", "minimum": 4, "maximum": 80},
        "temperatura": {"bsonType": "number", "minimum": 30, "maximum": 45},
        "spo2": {"bsonType": "number", "minimum": 40, "maximum": 100},
        "peso_kg": {"bsonType": "number", "minimum": 0.3, "maximum": 500},
        "altura_cm": {"bsonType": "number", "minimum": 30, "maximum": 260},
    },
}

VALIDADORES: dict[str, dict[str, Any]] = {
    "pacientes": {"$jsonSchema": {
        "bsonType": "object",
        "required": ["_id", "cpf", "nome", "nome_busca", "data_nascimento", "sexo", "criado_em"],
        "properties": {
            "_id": {"bsonType": "string"},
            "cpf": {"bsonType": "string", "pattern": "^[0-9]{11}$"},
            "nome": {"bsonType": "string", "minLength": 3},
            "data_nascimento": {"bsonType": "date"},
            "sexo": {"enum": ["F", "M", "I"]},
            "tipo_sanguineo": {"enum": ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "N/I"]},
            "alergias": {"bsonType": "array", "items": {
                "bsonType": "object",
                "required": ["substancia", "gravidade"],
                "properties": {"gravidade": {"enum": _ENUM_GRAVIDADE}},
            }},
            "familiares": {"bsonType": "array", "items": {
                "bsonType": "object", "required": ["paciente_id", "grau"],
            }},
        },
    }},
    "atendimentos": {"$jsonSchema": {
        "bsonType": "object",
        "required": ["_id", "paciente_id", "profissional_id", "tipo", "data_hora",
                     "queixa_principal", "criado_em"],
        "properties": {
            "tipo": {"enum": ["consulta", "retorno", "urgencia", "internacao", "enfermagem"]},
            "data_hora": {"bsonType": "date"},
            "queixa_principal": {"bsonType": "string", "minLength": 3},
            "sinais_vitais": _SINAIS_VITAIS,
            "diagnosticos": {"bsonType": "array", "items": {
                "bsonType": "object", "required": ["cid"],
            }},
            "prescricoes": {"bsonType": "array", "items": {
                "bsonType": "object", "required": ["medicamento_id", "nome"],
            }},
            "desfecho": {"enum": ["alta", "retorno", "internacao", "encaminhamento", "obito", "em_andamento"]},
            "adendos": {"bsonType": "array"},
        },
    }},
    "exames": {"$jsonSchema": {
        "bsonType": "object",
        "required": ["_id", "paciente_id", "tipo", "nome", "data_coleta"],
        "properties": {"tipo": {"enum": ["laboratorial", "imagem"]}},
    }},
    "internacoes": {"$jsonSchema": {
        "bsonType": "object",
        "required": ["_id", "paciente_id", "leito_id", "ala", "entrada", "ativa"],
        "properties": {"ativa": {"bsonType": "bool"}, "entrada": {"bsonType": "date"}},
    }},
    "usuarios": {"$jsonSchema": {
        "bsonType": "object",
        "required": ["_id", "login", "nome", "perfil", "senha_hash", "salt", "iteracoes"],
        "properties": {"perfil": {"enum": ["medico", "enfermeiro", "recepcao", "admin"]}},
    }},
}

# (coleção, chaves, opções)
INDICES: list[tuple[str, list[tuple[str, Any]], dict[str, Any]]] = [
    ("pacientes", [("cpf", ASCENDING)], {"unique": True, "name": "uq_cpf"}),
    ("pacientes", [("nome_busca", ASCENDING)], {"name": "ix_nome_busca"}),
    ("atendimentos", [("paciente_id", ASCENDING), ("data_hora", DESCENDING)], {"name": "ix_paciente_data"}),
    ("atendimentos", [("profissional_id", ASCENDING), ("data_hora", DESCENDING)], {"name": "ix_prof_data"}),
    ("atendimentos", [("diagnosticos.cid", ASCENDING)], {"name": "ix_cid"}),
    ("atendimentos", [("sync_grafo", ASCENDING)], {"name": "ix_sync_grafo"}),
    ("atendimentos", [("queixa_principal", TEXT), ("evolucao", TEXT)],
     {"name": "tx_atendimento", "default_language": "portuguese"}),
    ("exames", [("paciente_id", ASCENDING), ("data_coleta", DESCENDING)], {"name": "ix_exame_paciente"}),
    ("internacoes", [("paciente_id", ASCENDING), ("entrada", DESCENDING)], {"name": "ix_internacao_paciente"}),
    # Um paciente só pode ter UMA internação ativa (índice único parcial)
    ("internacoes", [("paciente_id", ASCENDING)],
     {"unique": True, "name": "uq_internacao_ativa", "partialFilterExpression": {"ativa": True}}),
    ("internacoes", [("leito_id", ASCENDING)],
     {"unique": True, "name": "uq_leito_ativo", "partialFilterExpression": {"ativa": True}}),
    ("auditoria", [("paciente_id", ASCENDING), ("data_hora", DESCENDING)], {"name": "ix_audit_paciente"}),
    ("auditoria", [("usuario", ASCENDING), ("data_hora", DESCENDING)], {"name": "ix_audit_usuario"}),
    ("auditoria", [("data_hora", DESCENDING)], {"name": "ix_audit_data"}),
    ("usuarios", [("login", ASCENDING)], {"unique": True, "name": "uq_login"}),
    ("medicamentos", [("nome", ASCENDING)], {"name": "ix_med_nome"}),
    ("interacoes", [("a", ASCENDING), ("b", ASCENDING)], {"unique": True, "name": "uq_interacao"}),
    ("cid10", [("descricao", ASCENDING)], {"name": "ix_cid_descricao"}),
]


def criar_schema(db: Database) -> dict[str, int]:
    """Cria/atualiza coleções com validação e índices. Idempotente."""
    existentes = set(db.list_collection_names())
    for nome, validador in VALIDADORES.items():
        opcoes = {"validator": validador, "validationLevel": "strict", "validationAction": "error"}
        if nome in existentes:
            db.command("collMod", nome, **opcoes)
        else:
            db.create_collection(nome, **opcoes)
    for colecao, chaves, opcoes in INDICES:
        db[colecao].create_index(chaves, **opcoes)
    return {"colecoes_validadas": len(VALIDADORES), "indices": len(INDICES)}
