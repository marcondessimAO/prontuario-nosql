"""Grafo clínico no Neo4j.

O MongoDB é a fonte da verdade; este serviço PROJETA os dados no grafo (MERGE =
idempotente) e executa as consultas que só fazem sentido em grafo:

  * segurança da prescrição (alergia por classe + interação medicamentosa);
  * condutas usadas em pacientes similares (filtragem colaborativa);
  * risco hereditário por parentesco (travessia variável);
  * comorbidades mais frequentes (co-ocorrência de diagnósticos);
  * caminho mais curto na rede de encaminhamento (shortestPath);
  * rastreamento de contatos hospitalares (sobreposição de internações).

Minimização de dados (LGPD): o grafo guarda só ids e atributos mínimos do
paciente; nomes são resolvidos no MongoDB quando a UI precisa exibir.

Consistência eventual: se o Neo4j estiver fora do ar a escrita clínica NÃO falha;
o documento é marcado `sync_grafo=False` e `reconciliar()` o reprocessa depois.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from neo4j.exceptions import DriverError, Neo4jError
from pymongo.database import Database

from ..core import trace
from ..infra.neo4j_client import GraphClient

log = logging.getLogger(__name__)
ERROS_GRAFO = (Neo4jError, DriverError)
_ORDEM_GRAVIDADE = {"grave": 0, "moderada": 1, "leve": 2}

# --------------------------------------------------------------------------- #
# Cypher de PROJEÇÃO (escrita idempotente)
# --------------------------------------------------------------------------- #
Q_MEDICAMENTOS = """
UNWIND $itens AS m
MERGE (x:Medicamento {id: m.id}) SET x.nome = m.nome
MERGE (c:Classe {nome: m.classe})
MERGE (x)-[:PERTENCE_A_CLASSE]->(c)
"""
Q_INTERACOES = """
UNWIND $itens AS i
MATCH (a:Medicamento {id: i.a}), (b:Medicamento {id: i.b})
MERGE (a)-[r:INTERAGE_COM]->(b)
SET r.gravidade = i.gravidade, r.efeito = i.efeito
"""
Q_DIAGNOSTICOS = """
UNWIND $itens AS d
MERGE (x:Diagnostico {cid: d.cid}) SET x.descricao = d.descricao
"""
Q_PROFISSIONAIS = """
UNWIND $itens AS p
MERGE (x:Profissional {id: p.id}) SET x.nome = p.nome
MERGE (e:Especialidade {nome: p.especialidade})
MERGE (x)-[:ESPECIALISTA_EM]->(e)
"""
Q_LEITOS = """
UNWIND $itens AS l
MERGE (x:Leito {id: l.id})
MERGE (a:Ala {nome: l.ala})
MERGE (x)-[:NA_ALA]->(a)
"""
Q_PACIENTE = "MERGE (p:Paciente {id: $id}) SET p.sexo = $sexo, p.ano_nascimento = $ano"
Q_ALERGIAS_LIMPAR = "MATCH (:Paciente {id: $id})-[r:ALERGICO_A]->() DELETE r"
Q_ALERGIA_CLASSE = """
MATCH (p:Paciente {id: $id})
UNWIND $classes AS c
MERGE (x:Classe {nome: c})
MERGE (p)-[:ALERGICO_A]->(x)
"""
Q_ALERGIA_MED = """
MATCH (p:Paciente {id: $id})
UNWIND $meds AS mid
MATCH (m:Medicamento {id: mid})
MERGE (p)-[:ALERGICO_A]->(m)
"""
Q_FAMILIARES = """
MATCH (p:Paciente {id: $id})
UNWIND $fam AS f
MERGE (q:Paciente {id: f.paciente_id})
MERGE (p)-[r:PARENTE_DE]-(q)
SET r.grau = f.grau
"""
Q_ATENDIMENTO = """
MERGE (p:Paciente {id: $pid})
MERGE (m:Profissional {id: $prof})
MERGE (p)-[r:ATENDIDO_POR {atendimento_id: $aid}]->(m)
SET r.data = $data
"""
Q_DIAGNOSTICADO = """
MATCH (p:Paciente {id: $pid})
UNWIND $dx AS d
MERGE (x:Diagnostico {cid: d.cid}) ON CREATE SET x.descricao = d.descricao
MERGE (p)-[r:DIAGNOSTICADO_COM {atendimento_id: $aid}]->(x)
SET r.data = $data, r.principal = d.principal
"""
Q_PRESCRITO = """
MATCH (p:Paciente {id: $pid})
UNWIND $rx AS i
MATCH (m:Medicamento {id: i.mid})
MERGE (p)-[r:PRESCRITO {atendimento_id: $aid}]->(m)
SET r.data = $data, r.dose = i.dose, r.fim = i.fim
"""
Q_ENCAMINHOU = """
MERGE (a:Profissional {id: $de})
MERGE (b:Profissional {id: $para})
MERGE (a)-[r:ENCAMINHOU_PARA {atendimento_id: $aid}]->(b)
SET r.data = $data
"""
Q_INTERNADO = """
MERGE (p:Paciente {id: $pid})
MERGE (l:Leito {id: $leito})
MERGE (p)-[r:INTERNADO_EM {internacao_id: $iid}]->(l)
SET r.entrada = $entrada, r.saida = $saida
"""

# --------------------------------------------------------------------------- #
# Cypher de CONSULTA
# --------------------------------------------------------------------------- #
Q_ALERGIA_CONFLITO = """
MATCH (p:Paciente {id: $pid})-[:ALERGICO_A]->(alvo)
MATCH (m:Medicamento)
WHERE m.id IN $mids AND (alvo = m OR (m)-[:PERTENCE_A_CLASSE]->(alvo))
RETURN DISTINCT m.nome AS medicamento, labels(alvo)[0] AS tipo, alvo.nome AS alvo
"""
Q_INTERACAO_EM_USO = """
MATCH (p:Paciente {id: $pid})-[r:PRESCRITO]->(atual:Medicamento)
WHERE r.fim IS NULL OR r.fim >= datetime()
MATCH (novo:Medicamento)
WHERE novo.id IN $mids AND novo <> atual
MATCH (atual)-[i:INTERAGE_COM]-(novo)
RETURN DISTINCT atual.nome AS em_uso, novo.nome AS novo, i.gravidade AS gravidade, i.efeito AS efeito
"""
Q_INTERACAO_ENTRE_SI = """
MATCH (a:Medicamento)-[i:INTERAGE_COM]-(b:Medicamento)
WHERE a.id IN $mids AND b.id IN $mids AND a.id < b.id
RETURN a.nome AS a, b.nome AS b, i.gravidade AS gravidade, i.efeito AS efeito
"""
Q_SUGESTAO_CONDUTA = """
MATCH (p:Paciente {id: $pid})-[:DIAGNOSTICADO_COM]->(d:Diagnostico)<-[:DIAGNOSTICADO_COM]-(s:Paciente)
WHERE s <> p
WITH p, s, count(DISTINCT d) AS dx_comuns
ORDER BY dx_comuns DESC
LIMIT 25
MATCH (s)-[:PRESCRITO]->(m:Medicamento)
WHERE NOT (p)-[:PRESCRITO]->(m)
  AND NOT EXISTS {
    MATCH (p)-[:ALERGICO_A]->(a)
    WHERE a = m OR (m)-[:PERTENCE_A_CLASSE]->(a)
  }
RETURN m.id AS id, m.nome AS medicamento,
       count(DISTINCT s) AS pacientes_similares, sum(dx_comuns) AS score
ORDER BY pacientes_similares DESC, score DESC
LIMIT 10
"""
Q_RISCO_FAMILIAR = """
MATCH path = (p:Paciente {id: $pid})-[:PARENTE_DE*1..2]-(f:Paciente)
WHERE f <> p
WITH f, min(length(path)) AS distancia
MATCH (f)-[:DIAGNOSTICADO_COM]->(d:Diagnostico)
RETURN d.cid AS cid, d.descricao AS descricao,
       count(DISTINCT f) AS parentes, min(distancia) AS grau_mais_proximo
ORDER BY parentes DESC, grau_mais_proximo ASC
"""
Q_COMORBIDADES = """
MATCH (d1:Diagnostico)<-[:DIAGNOSTICADO_COM]-(p:Paciente)-[:DIAGNOSTICADO_COM]->(d2:Diagnostico)
WHERE d1.cid < d2.cid
RETURN d1.cid AS cid_a, d1.descricao AS descricao_a, d2.cid AS cid_b, d2.descricao AS descricao_b,
       count(DISTINCT p) AS pacientes
ORDER BY pacientes DESC
LIMIT $limite
"""
Q_CAMINHO = """
MATCH (a:Profissional {id: $de}), (b:Profissional {id: $para})
WHERE a <> b
MATCH p = shortestPath((a)-[:ENCAMINHOU_PARA*..6]->(b))
RETURN [n IN nodes(p) | n.nome] AS caminho, length(p) AS saltos
"""
Q_ESPECIALISTAS = """
MATCH (origem:Profissional {id: $de}), (alvo:Profissional)-[:ESPECIALISTA_EM]->(:Especialidade {nome: $esp})
WHERE origem <> alvo
MATCH p = shortestPath((origem)-[:ENCAMINHOU_PARA*..6]->(alvo))
RETURN alvo.id AS id, alvo.nome AS nome, length(p) AS saltos
ORDER BY saltos ASC
LIMIT 5
"""
Q_CONTATOS = """
MATCH (idx:Paciente {id: $pid})-[a:INTERNADO_EM]->(:Leito)-[:NA_ALA]->(ala:Ala)
      <-[:NA_ALA]-(:Leito)<-[b:INTERNADO_EM]-(outro:Paciente)
WHERE outro <> idx
  AND a.entrada <= coalesce(b.saida, datetime())
  AND b.entrada <= coalesce(a.saida, datetime())
RETURN DISTINCT outro.id AS paciente_id, ala.nome AS ala, b.entrada AS entrada, b.saida AS saida
ORDER BY entrada
"""
Q_CONTAGEM_NOS = "MATCH (n) RETURN labels(n)[0] AS rotulo, count(*) AS total ORDER BY total DESC"
Q_CONTAGEM_RELS = "MATCH ()-[r]->() RETURN type(r) AS tipo, count(*) AS total ORDER BY total DESC"


class GrafoService:
    def __init__(self, db: Database, graph: GraphClient) -> None:
        self._db = db
        self._g = graph

    # ------------------------------------------------------------------ #
    # Projeção MongoDB -> Neo4j
    # ------------------------------------------------------------------ #
    def projetar_catalogos(self) -> None:
        meds = [{"id": m["_id"], "nome": m["nome"], "classe": m["classe"]} for m in self._db.medicamentos.find()]
        inter = [{"a": i["a"], "b": i["b"], "gravidade": i["gravidade"], "efeito": i["efeito"]}
                 for i in self._db.interacoes.find()]
        cids = [{"cid": c["_id"], "descricao": c["descricao"]} for c in self._db.cid10.find()]
        profs = [{"id": p["_id"], "nome": p["nome"], "especialidade": p["especialidade"]}
                 for p in self._db.profissionais.find()]
        leitos = [{"id": l["_id"], "ala": l["ala"]} for l in self._db.leitos.find()]
        self._g.write_many([
            (Q_MEDICAMENTOS, {"itens": meds}),
            (Q_INTERACOES, {"itens": inter}),
            (Q_DIAGNOSTICOS, {"itens": cids}),
            (Q_PROFISSIONAIS, {"itens": profs}),
            (Q_LEITOS, {"itens": leitos}),
        ])

    @staticmethod
    def _comandos_paciente(p: dict) -> list[tuple[str, dict]]:
        alergias = p.get("alergias", [])
        classes = sorted({a["classe"] for a in alergias if a.get("classe")})
        meds = sorted({a["medicamento_id"] for a in alergias if a.get("medicamento_id")})
        return [
            (Q_PACIENTE, {"id": p["_id"], "sexo": p["sexo"], "ano": p["data_nascimento"].year}),
            (Q_ALERGIAS_LIMPAR, {"id": p["_id"]}),
            (Q_ALERGIA_CLASSE, {"id": p["_id"], "classes": classes}),
            (Q_ALERGIA_MED, {"id": p["_id"], "meds": meds}),
            (Q_FAMILIARES, {"id": p["_id"], "fam": p.get("familiares", [])}),
        ]

    @staticmethod
    def _comandos_atendimento(a: dict) -> list[tuple[str, dict]]:
        base = {"pid": a["paciente_id"], "aid": a["_id"], "data": a["data_hora"]}
        comandos: list[tuple[str, dict]] = [
            (Q_ATENDIMENTO, {**base, "prof": a["profissional_id"]}),
        ]
        dx = [
            {"cid": d["cid"], "descricao": d.get("descricao", ""), "principal": d.get("tipo") == "principal"}
            for d in a.get("diagnosticos", [])
        ]
        if dx:
            comandos.append((Q_DIAGNOSTICADO, {**base, "dx": dx}))
        rx = [
            {
                "mid": p["medicamento_id"],
                "dose": p.get("dose", ""),
                "fim": a["data_hora"] + timedelta(days=p["duracao_dias"]) if p.get("duracao_dias") else None,
            }
            for p in a.get("prescricoes", [])
        ]
        if rx:
            comandos.append((Q_PRESCRITO, {**base, "rx": rx}))
        if a.get("encaminhado_para"):
            comandos.append((Q_ENCAMINHOU, {
                "de": a["profissional_id"], "para": a["encaminhado_para"],
                "aid": a["_id"], "data": a["data_hora"],
            }))
        return comandos

    @staticmethod
    def _comandos_internacao(i: dict) -> list[tuple[str, dict]]:
        return [(Q_INTERNADO, {
            "pid": i["paciente_id"], "leito": i["leito_id"], "iid": i["_id"],
            "entrada": i["entrada"], "saida": i.get("saida"),
        })]

    def _tentar(self, colecao: str, doc_id: str, comandos: list[tuple[str, dict]]) -> bool:
        """Projeta no grafo e registra o resultado no documento de origem (outbox simples)."""
        try:
            self._g.write_many(comandos)
            ok = True
        except ERROS_GRAFO as exc:
            log.warning("Falha ao projetar %s/%s no Neo4j: %s", colecao, doc_id, exc)
            trace.registrar("neo4j", "FALHA", f"{colecao}/{doc_id} marcado p/ reconciliação")
            ok = False
        self._db[colecao].update_one({"_id": doc_id}, {"$set": {"sync_grafo": ok}})
        return ok

    def sincronizar_paciente(self, p: dict) -> bool:
        return self._tentar("pacientes", p["_id"], self._comandos_paciente(p))

    def sincronizar_atendimento(self, a: dict) -> bool:
        return self._tentar("atendimentos", a["_id"], self._comandos_atendimento(a))

    def sincronizar_internacao(self, i: dict) -> bool:
        return self._tentar("internacoes", i["_id"], self._comandos_internacao(i))

    def reconciliar(self, todos: bool = False) -> dict[str, int]:
        """Reprocessa documentos com sync_grafo != True (ou tudo, se `todos`)."""
        filtro: dict[str, Any] = {} if todos else {"sync_grafo": {"$ne": True}}
        contagem = {"pacientes": 0, "atendimentos": 0, "internacoes": 0, "falhas": 0}
        etapas = (
            ("pacientes", self.sincronizar_paciente),
            ("atendimentos", self.sincronizar_atendimento),
            ("internacoes", self.sincronizar_internacao),
        )
        for colecao, sincronizar in etapas:
            for doc in self._db[colecao].find(filtro):
                if sincronizar(doc):
                    contagem[colecao] += 1
                else:
                    contagem["falhas"] += 1
        return contagem

    def projetar_tudo(self) -> dict[str, int]:
        """Reconstrói o grafo inteiro a partir do MongoDB (catálogos + todos os documentos)."""
        self.projetar_catalogos()
        return self.reconciliar(todos=True)

    def pendencias(self) -> int:
        filtro = {"sync_grafo": {"$ne": True}}
        return sum(self._db[c].count_documents(filtro) for c in ("pacientes", "atendimentos", "internacoes"))

    # ------------------------------------------------------------------ #
    # Consultas
    # ------------------------------------------------------------------ #
    def disponivel(self) -> bool:
        return self._g.ping()

    def verificar_prescricao(self, paciente_id: str, med_ids: list[str]) -> dict[str, Any]:
        """Apoio à decisão: alergias (inclui classe) e interações. NÃO substitui o julgamento clínico."""
        if not med_ids:
            return {"verificado": True, "alertas": []}
        try:
            alergias = self._g.read(Q_ALERGIA_CONFLITO, pid=paciente_id, mids=med_ids)
            em_uso = self._g.read(Q_INTERACAO_EM_USO, pid=paciente_id, mids=med_ids)
            entre_si = self._g.read(Q_INTERACAO_ENTRE_SI, mids=med_ids)
        except ERROS_GRAFO as exc:
            log.warning("Verificação de prescrição indisponível: %s", exc)
            return {"verificado": False, "alertas": []}

        alertas: list[dict[str, str]] = []
        for a in alergias:
            alertas.append({
                "tipo": "alergia", "gravidade": "grave",
                "mensagem": f"ALERGIA: paciente alérgico a {a['alvo']} ({a['tipo'].lower()}) — conflito com {a['medicamento']}.",
            })
        for i in em_uso:
            alertas.append({
                "tipo": "interacao", "gravidade": i["gravidade"],
                "mensagem": f"{i['novo']} × {i['em_uso']} (já em uso): {i['efeito']}",
            })
        for i in entre_si:
            alertas.append({
                "tipo": "interacao", "gravidade": i["gravidade"],
                "mensagem": f"{i['a']} × {i['b']} (na mesma prescrição): {i['efeito']}",
            })
        alertas.sort(key=lambda x: _ORDEM_GRAVIDADE.get(x["gravidade"], 9))
        return {"verificado": True, "alertas": alertas}

    def sugerir_condutas(self, paciente_id: str) -> list[dict]:
        return self._g.read(Q_SUGESTAO_CONDUTA, pid=paciente_id)

    def risco_familiar(self, paciente_id: str) -> list[dict]:
        return self._g.read(Q_RISCO_FAMILIAR, pid=paciente_id)

    def comorbidades(self, limite: int = 10) -> list[dict]:
        return self._g.read(Q_COMORBIDADES, limite=limite)

    def caminho_encaminhamento(self, de: str, para: str) -> dict | None:
        linhas = self._g.read(Q_CAMINHO, de=de, para=para)
        return linhas[0] if linhas else None

    def especialistas_proximos(self, de: str, especialidade: str) -> list[dict]:
        return self._g.read(Q_ESPECIALISTAS, de=de, esp=especialidade)

    def rastrear_contatos(self, paciente_id: str) -> list[dict]:
        contatos = self._g.read(Q_CONTATOS, pid=paciente_id)
        nomes = {
            p["_id"]: p["nome"]
            for p in self._db.pacientes.find({"_id": {"$in": [c["paciente_id"] for c in contatos]}}, {"nome": 1})
        }
        for c in contatos:
            c["nome"] = nomes.get(c["paciente_id"], c["paciente_id"])
        return contatos

    def estatisticas(self) -> dict[str, list[dict]]:
        return {"nos": self._g.read(Q_CONTAGEM_NOS), "relacionamentos": self._g.read(Q_CONTAGEM_RELS)}
