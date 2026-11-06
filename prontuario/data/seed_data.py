"""Dataset SINTÉTICO para demonstração. Nenhum dado aqui é de pessoa real.

Gerado de forma determinística (seed fixa) e relativa à data atual, para que os
gráficos de "últimos 30 dias" e as prescrições vigentes façam sentido a qualquer
momento. Os catálogos (CID-10, medicamentos, interações) são DIDÁTICOS e não
substituem bases oficiais de farmacovigilância.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from ..core.tempo import agora as _agora
from ..core.validators import calcular_dv_cpf, normalizar_texto

# --------------------------------------------------------------------------- #
# Catálogos
# --------------------------------------------------------------------------- #
CIDS = {
    "I10": "Hipertensão essencial (primária)",
    "E11": "Diabetes mellitus não-insulino-dependente",
    "E78": "Distúrbios do metabolismo de lipoproteínas e outras lipidemias",
    "E66": "Obesidade",
    "I48": "Flutter e fibrilação atrial",
    "I50": "Insuficiência cardíaca",
    "I21": "Infarto agudo do miocárdio",
    "I63": "Infarto cerebral",
    "J45": "Asma",
    "J18": "Pneumonia por microrganismo não especificado",
    "J06": "Infecções agudas das vias aéreas superiores",
    "F32": "Episódios depressivos",
    "M54": "Dorsalgia",
    "K29": "Gastrite e duodenite",
    "A90": "Dengue [dengue clássico]",
    "U07.1": "COVID-19, vírus identificado",
    "N39": "Outros transtornos do trato urinário",
    "N18": "Doença renal crônica",
    "G43": "Enxaqueca",
    "R50": "Febre de origem desconhecida e outras",
}

# id, nome, classe, controlado, (dose, via, frequência)
_MEDS = [
    ("med-001", "Varfarina", "Anticoagulantes", False, ("5 mg", "VO", "1x ao dia")),
    ("med-002", "Ácido acetilsalicílico (AAS)", "Antiagregantes plaquetários", False, ("100 mg", "VO", "1x ao dia")),
    ("med-003", "Diclofenaco", "AINEs", False, ("50 mg", "VO", "8/8h")),
    ("med-004", "Ibuprofeno", "AINEs", False, ("600 mg", "VO", "8/8h")),
    ("med-005", "Paracetamol", "Analgésicos", False, ("750 mg", "VO", "6/6h")),
    ("med-006", "Dipirona", "Analgésicos", False, ("500 mg", "VO", "6/6h")),
    ("med-007", "Amoxicilina", "Penicilinas", False, ("500 mg", "VO", "8/8h")),
    ("med-008", "Azitromicina", "Macrolídeos", False, ("500 mg", "VO", "1x ao dia")),
    ("med-009", "Claritromicina", "Macrolídeos", False, ("500 mg", "VO", "12/12h")),
    ("med-010", "Ciprofloxacino", "Quinolonas", False, ("500 mg", "VO", "12/12h")),
    ("med-011", "Losartana", "Antagonistas da angiotensina II", False, ("50 mg", "VO", "12/12h")),
    ("med-012", "Enalapril", "IECA", False, ("10 mg", "VO", "12/12h")),
    ("med-013", "Hidroclorotiazida", "Diuréticos", False, ("25 mg", "VO", "1x ao dia")),
    ("med-014", "Furosemida", "Diuréticos", False, ("40 mg", "VO", "1x ao dia")),
    ("med-015", "Espironolactona", "Diuréticos poupadores de potássio", False, ("25 mg", "VO", "1x ao dia")),
    ("med-016", "Anlodipino", "Bloqueadores de canal de cálcio", False, ("5 mg", "VO", "1x ao dia")),
    ("med-017", "Metformina", "Biguanidas", False, ("850 mg", "VO", "12/12h")),
    ("med-018", "Glibenclamida", "Sulfonilureias", False, ("5 mg", "VO", "1x ao dia")),
    ("med-019", "Sinvastatina", "Estatinas", False, ("20 mg", "VO", "à noite")),
    ("med-020", "Atorvastatina", "Estatinas", False, ("40 mg", "VO", "à noite")),
    ("med-021", "Omeprazol", "Inibidores da bomba de prótons", False, ("20 mg", "VO", "em jejum")),
    ("med-022", "Clopidogrel", "Antiagregantes plaquetários", False, ("75 mg", "VO", "1x ao dia")),
    ("med-023", "Fluoxetina", "ISRS", True, ("20 mg", "VO", "pela manhã")),
    ("med-024", "Tramadol", "Opioides", True, ("50 mg", "VO", "8/8h")),
    ("med-025", "Salbutamol", "Broncodilatadores", False, ("100 mcg", "inalatória", "se necessário")),
    ("med-026", "Budesonida", "Corticoides inalatórios", False, ("200 mcg", "inalatória", "12/12h")),
    ("med-027", "Prednisona", "Corticoides", False, ("20 mg", "VO", "1x ao dia")),
    ("med-028", "Insulina NPH", "Insulinas", False, ("10 UI", "SC", "à noite")),
]

# a, b, gravidade, efeito (catálogo didático)
_INTERACOES = [
    ("med-001", "med-002", "grave", "risco aumentado de sangramento"),
    ("med-001", "med-003", "grave", "risco aumentado de sangramento (AINE + anticoagulante)"),
    ("med-001", "med-004", "grave", "risco aumentado de sangramento (AINE + anticoagulante)"),
    ("med-001", "med-010", "moderada", "pode elevar o INR; monitorar coagulação"),
    ("med-001", "med-008", "moderada", "pode elevar o INR; monitorar coagulação"),
    ("med-019", "med-009", "grave", "risco de rabdomiólise (aumento do nível da estatina)"),
    ("med-012", "med-015", "grave", "risco de hipercalemia"),
    ("med-011", "med-015", "moderada", "risco de hipercalemia"),
    ("med-012", "med-003", "moderada", "redução do efeito anti-hipertensivo e risco renal"),
    ("med-022", "med-021", "moderada", "omeprazol pode reduzir a eficácia do clopidogrel"),
    ("med-023", "med-024", "grave", "risco de síndrome serotoninérgica e convulsões"),
    ("med-002", "med-004", "moderada", "ibuprofeno pode antagonizar o efeito antiagregante do AAS"),
    ("med-002", "med-022", "moderada", "dupla antiagregação: maior risco de sangramento"),
    ("med-018", "med-010", "moderada", "risco de hipoglicemia"),
    ("med-027", "med-003", "moderada", "risco aumentado de sangramento gastrointestinal"),
]

_PROFISSIONAIS = [
    ("prof-001", "Dr. Carlos Eduardo Menezes", "Cardiologia", "CRM", "100001", "SP"),
    ("prof-002", "Dra. Helena Duarte", "Clínica Médica", "CRM", "100002", "SP"),
    ("prof-003", "Dr. Rafael Nogueira", "Endocrinologia", "CRM", "100003", "SP"),
    ("prof-004", "Dra. Patrícia Lima", "Pneumologia", "CRM", "100004", "SP"),
    ("prof-005", "Dr. André Barros", "Neurologia", "CRM", "100005", "SP"),
    ("prof-006", "Dra. Juliana Prado", "Nefrologia", "CRM", "100006", "SP"),
    ("prof-007", "Dr. Marcos Tavares", "Emergência", "CRM", "100007", "SP"),
    ("prof-008", "Enf. Luciana Ferreira", "Enfermagem", "COREN", "200001", "SP"),
    ("prof-009", "Enf. Roberto Cunha", "Enfermagem", "COREN", "200002", "SP"),
    ("prof-010", "Dra. Beatriz Sampaio", "Psiquiatria", "CRM", "100010", "SP"),
]

USUARIOS = [
    ("dr.carlos", "Dr. Carlos Eduardo Menezes", "medico", "prof-001"),
    ("dra.helena", "Dra. Helena Duarte", "medico", "prof-002"),
    ("dr.marcos", "Dr. Marcos Tavares", "medico", "prof-007"),
    ("enf.luciana", "Enf. Luciana Ferreira", "enfermeiro", "prof-008"),
    ("recepcao", "Recepção Central", "recepcao", ""),
    ("admin", "Administrador do Sistema", "admin", ""),
]

# Perfis crônicos: CID, medicamentos, profissionais que acompanham, queixa típica
PERFIS: dict[str, dict[str, Any]] = {
    "has": {"cid": "I10", "meds": ["med-011", "med-016"], "prof": ["prof-002", "prof-001"],
            "queixa": "Cefaleia e controle de pressão arterial", "pa": (150, 95)},
    "dm2": {"cid": "E11", "meds": ["med-017"], "prof": ["prof-003", "prof-002"],
            "queixa": "Poliúria, sede e controle glicêmico", "pa": (130, 85)},
    "dislip": {"cid": "E78", "meds": ["med-019"], "prof": ["prof-001"],
               "queixa": "Controle de colesterol", "pa": (125, 80)},
    "fa": {"cid": "I48", "meds": ["med-001"], "prof": ["prof-001"],
           "queixa": "Palpitações e controle de anticoagulação", "pa": (135, 85)},
    "icc": {"cid": "I50", "meds": ["med-012", "med-014", "med-015"], "prof": ["prof-001"],
            "queixa": "Dispneia aos esforços e edema de membros inferiores", "pa": (120, 75)},
    "asma": {"cid": "J45", "meds": ["med-025", "med-026"], "prof": ["prof-004"],
             "queixa": "Chiado no peito e falta de ar noturna", "pa": (118, 76)},
    "dep": {"cid": "F32", "meds": ["med-023"], "prof": ["prof-010"],
            "queixa": "Humor deprimido e insônia", "pa": (115, 72)},
    "gastrite": {"cid": "K29", "meds": ["med-021"], "prof": ["prof-002"],
                 "queixa": "Dor epigástrica e queimação", "pa": (118, 76)},
    "lombalgia": {"cid": "M54", "meds": ["med-005"], "prof": ["prof-002"],
                  "queixa": "Dor lombar persistente", "pa": (122, 78)},
    "drc": {"cid": "N18", "meds": ["med-012"], "prof": ["prof-006"],
            "queixa": "Acompanhamento de doença renal crônica", "pa": (140, 88)},
}

# episódios agudos: CID, queixa, medicamentos, dias de tratamento
_AGUDOS = [
    ("J06", "Dor de garganta, coriza e febre baixa", ["med-005"], 5),
    ("J18", "Tosse produtiva, febre e dispneia", ["med-007", "med-005"], 7),
    ("A90", "Febre alta, mialgia e dor retroorbitária", ["med-005"], 5),
    ("N39", "Disúria e polaciúria", ["med-010"], 7),
]

# (de, para): arestas da rede de encaminhamento
_REDE = [
    ("prof-007", "prof-002"), ("prof-002", "prof-001"), ("prof-002", "prof-003"),
    ("prof-002", "prof-004"), ("prof-002", "prof-005"), ("prof-002", "prof-010"),
    ("prof-001", "prof-006"), ("prof-003", "prof-006"), ("prof-005", "prof-010"),
]

_ALERGIAS = {
    "penicilina": {"substancia": "Penicilina", "classe": "Penicilinas", "reacao": "anafilaxia", "gravidade": "grave"},
    "dipirona": {"substancia": "Dipirona", "medicamento_id": "med-006", "reacao": "exantema", "gravidade": "leve"},
    "aine": {"substancia": "AINEs", "classe": "AINEs", "reacao": "broncoespasmo", "gravidade": "grave"},
}

# Pacientes fixos de demonstração: id, nome, sexo, ano, perfis, alergias, sangue
_DEMO = [
    ("pac-0001", "Maria das Graças Oliveira", "F", 1951, ["fa", "has"], ["penicilina"], "O+"),
    ("pac-0002", "José Antônio Ferreira", "M", 1958, ["dm2", "has", "dislip"], [], "A+"),
    ("pac-0003", "Ana Paula Ferreira", "F", 1984, ["dm2"], [], "A+"),
    ("pac-0004", "Pedro Henrique Ferreira", "M", 1988, ["has"], [], "A-"),
    ("pac-0005", "Lucas Martins Barbosa", "M", 1990, [], [], "B+"),
    ("pac-0006", "Fernanda Souza Lima", "F", 1975, ["asma"], [], "O+"),
    ("pac-0007", "Roberto Lima Nascimento", "M", 1962, ["icc", "drc"], [], "AB+"),
    ("pac-0008", "Camila Rocha Andrade", "F", 1995, ["dep"], ["dipirona"], "O-"),
]
# (paciente, parente, grau do parente em relação ao paciente)
_FAMILIA = [("pac-0003", "pac-0002", "pai"), ("pac-0004", "pac-0002", "pai"), ("pac-0003", "pac-0004", "irmão(ã)")]
_GRAU_INVERSO = {"pai": "filho(a)", "irmão(ã)": "irmão(ã)"}

_FEM = ["Maria", "Ana", "Juliana", "Patrícia", "Fernanda", "Camila", "Beatriz", "Larissa", "Aline", "Renata", "Carla", "Priscila"]
_MASC = ["João", "Carlos", "Rafael", "Marcos", "Felipe", "Gustavo", "Bruno", "Eduardo", "Rodrigo", "Thiago", "Leandro", "Diego"]
_SOBRENOMES = ["Silva", "Santos", "Oliveira", "Souza", "Pereira", "Costa", "Rodrigues", "Almeida", "Nascimento",
               "Lima", "Araújo", "Carvalho", "Gomes", "Ribeiro", "Martins", "Rocha", "Barbosa", "Dias", "Cardoso"]
_N_ALEATORIOS = 22


def _conflita(alergias: list[dict], med: dict) -> bool:
    return any(a.get("classe") == med["classe"] or a.get("medicamento_id") == med["_id"] for a in alergias)


def _cpf(rng: random.Random, usados: set[str]) -> str:
    while True:
        base = "".join(str(rng.randint(0, 9)) for _ in range(9))
        cpf = base + calcular_dv_cpf(base)
        if len(set(cpf)) > 1 and cpf not in usados:
            usados.add(cpf)
            return cpf


def _sinais(rng: random.Random, pa: tuple[int, int]) -> dict[str, float]:
    return {
        "pa_sistolica": float(pa[0] + rng.randint(-8, 10)), "pa_diastolica": float(pa[1] + rng.randint(-5, 6)),
        "fc": float(rng.randint(58, 96)), "fr": float(rng.randint(12, 20)),
        "temperatura": round(rng.uniform(36.0, 37.2), 1), "spo2": float(rng.randint(95, 99)),
        "peso_kg": round(rng.uniform(55, 98), 1), "altura_cm": float(rng.randint(152, 188)),
    }


def build_dataset(agora: datetime | None = None, seed: int = 42) -> dict[str, list[dict]]:
    now = agora or _agora()
    rng = random.Random(seed)
    meds = {m[0]: {"_id": m[0], "nome": m[1], "classe": m[2], "controlado": m[3],
                   "posologia_padrao": {"dose": m[4][0], "via": m[4][1], "frequencia": m[4][2]}} for m in _MEDS}

    def prescricao(med_id: str, dias: int) -> dict:
        m = meds[med_id]
        p = m["posologia_padrao"]
        return {"medicamento_id": med_id, "nome": m["nome"], "dose": p["dose"], "via": p["via"],
                "frequencia": p["frequencia"], "duracao_dias": dias}

    # ------------------------- pacientes ------------------------------- #
    especificacoes = list(_DEMO)
    usados_nomes = {e[1] for e in especificacoes}
    for n in range(len(_DEMO) + 1, len(_DEMO) + _N_ALEATORIOS + 1):
        sexo = rng.choice(["F", "M"])
        while True:
            nome = f"{rng.choice(_FEM if sexo == 'F' else _MASC)} {rng.choice(_SOBRENOMES)} {rng.choice(_SOBRENOMES)}"
            if nome not in usados_nomes:
                usados_nomes.add(nome)
                break
        perfis = rng.sample(list(PERFIS), k=rng.choice([1, 1, 2, 2, 3]))
        alergias = [rng.choice(list(_ALERGIAS))] if rng.random() < 0.2 else []
        especificacoes.append((f"pac-{n:04d}", nome, sexo, rng.randint(1945, 2005), perfis, alergias,
                               rng.choice(["A+", "A-", "B+", "O+", "O-", "AB+"])))

    usados_cpf: set[str] = set()
    parentes: dict[str, list[dict]] = {e[0]: [] for e in especificacoes}
    for pac, parente, grau in _FAMILIA:
        parentes[pac].append({"paciente_id": parente, "grau": grau})
        parentes[parente].append({"paciente_id": pac, "grau": _GRAU_INVERSO.get(grau, grau)})

    pacientes, perfis_por_paciente = [], {}
    for pid, nome, sexo, ano, perfis, alerg, sangue in especificacoes:
        perfis_por_paciente[pid] = perfis
        pacientes.append({
            "_id": pid, "cpf": _cpf(rng, usados_cpf), "nome": nome, "nome_busca": normalizar_texto(nome),
            "data_nascimento": datetime(ano, rng.randint(1, 12), rng.randint(1, 28), tzinfo=now.tzinfo),
            "sexo": sexo, "tipo_sanguineo": sangue,
            "contato": {"telefone": f"(11) 9{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}",
                        "email": f"{normalizar_texto(nome).split()[0]}.{pid[-4:]}@exemplo.invalid"},
            "convenio": rng.choice([None, {"nome": "Plano Saúde Exemplo", "numero": f"{rng.randint(10**8, 10**9 - 1)}"}]),
            "alergias": [dict(_ALERGIAS[a]) for a in alerg],
            "familiares": parentes[pid],
            "consentimento_lgpd": {"aceito": True, "data": now - timedelta(days=400)},
            "criado_em": now - timedelta(days=400), "atualizado_em": now - timedelta(days=30),
            "sync_grafo": False,
        })
    por_id = {p["_id"]: p for p in pacientes}

    # ------------------------- atendimentos ---------------------------- #
    atendimentos: list[dict] = []
    contador = 0

    def novo_atendimento(pid: str, prof: str, tipo: str, quando: datetime, queixa: str, cid: str,
                         prescricoes: list[dict], desfecho: str, evolucao: str, pa: tuple[int, int] = (122, 78),
                         destino: str | None = None) -> None:
        nonlocal contador
        contador += 1
        atendimentos.append({
            "_id": f"at-{contador:05d}", "paciente_id": pid, "profissional_id": prof, "tipo": tipo,
            "data_hora": quando, "queixa_principal": queixa,
            "anamnese": {"historia_doenca_atual": f"Paciente relata {queixa.lower()}."},
            "sinais_vitais": _sinais(rng, pa), "exame_fisico": "Bom estado geral, corado, hidratado.",
            "diagnosticos": [{"cid": cid, "descricao": CIDS[cid], "tipo": "principal"}],
            "prescricoes": prescricoes, "exames_solicitados": [], "evolucao": evolucao, "desfecho": desfecho,
            "encaminhado_para": destino, "adendos": [],
            "assinatura": {"login": "seed", "data_hora": quando}, "criado_em": quando, "sync_grafo": False,
        })

    for pid, perfis in perfis_por_paciente.items():
        alergias = por_id[pid]["alergias"]
        for perfil in perfis:
            cfg = PERFIS[perfil]
            ultima = rng.randint(3, 25)
            for k in range(rng.randint(2, 4)):
                quando = now - timedelta(days=ultima + 60 * k + rng.randint(-5, 5), hours=rng.randint(0, 8))
                rx = [prescricao(m, 90) for m in cfg["meds"] if not _conflita(alergias, meds[m])]
                novo_atendimento(
                    pid, rng.choice(cfg["prof"]), "retorno" if k else "consulta", quando, cfg["queixa"],
                    cfg["cid"], rx, "retorno",
                    f"Acompanhamento de {CIDS[cfg['cid']].lower()}. Mantida conduta, reforçada adesão; retorno em 90 dias.",
                    cfg["pa"],
                )
        if rng.random() < 0.4:  # episódio agudo na emergência
            cid, queixa, mids, dias = rng.choice(_AGUDOS)
            ok = [m for m in mids if not _conflita(alergias, meds[m])] or ["med-008"]
            novo_atendimento(pid, "prof-007", "urgencia", now - timedelta(days=rng.randint(2, 60)), queixa,
                             cid, [prescricao(m, dias) for m in ok], "alta", "Orientado repouso, hidratação e retorno se piora.")

    # Caso-índice de contágio (COVID-19) para o rastreio de contatos
    novo_atendimento("pac-0005", "prof-007", "urgencia", now - timedelta(days=6, hours=2),
                     "Febre, tosse seca e anosmia", "U07.1", [prescricao("med-005", 5)], "internacao",
                     "Teste positivo para SARS-CoV-2. Internação para observação e isolamento.")

    # Rede de encaminhamento: um atendimento por aresta
    elegiveis = [p["_id"] for p in pacientes if p["_id"] not in {"pac-0001", "pac-0005"}]
    for i, (de, para) in enumerate(_REDE):
        pid = elegiveis[(i * 3) % len(elegiveis)]
        destino = next(p for p in _PROFISSIONAIS if p[0] == para)
        cid = PERFIS[perfis_por_paciente[pid][0]]["cid"] if perfis_por_paciente[pid] else "R50"
        novo_atendimento(pid, de, "consulta", now - timedelta(days=rng.randint(10, 120)),
                         f"Encaminhamento para {destino[2]}", cid, [], "encaminhamento",
                         f"Encaminhado a {destino[1]} para avaliação especializada.", destino=para)

    # ------------------------- exames ---------------------------------- #
    exames: list[dict] = []

    def exame(pid: str, tipo: str, nome: str, dias: int, **extra: Any) -> None:
        exames.append({"_id": f"ex-{len(exames) + 1:05d}", "paciente_id": pid, "tipo": tipo, "nome": nome,
                       "data_coleta": now - timedelta(days=dias), "status": "concluido",
                       "criado_em": now - timedelta(days=dias), **extra})

    for pid, perfis in perfis_por_paciente.items():
        if "dm2" in perfis:
            valor = round(rng.uniform(6.8, 9.2), 1)
            exame(pid, "laboratorial", "Hemoglobina glicada", rng.randint(5, 40), resultados=[
                {"analito": "HbA1c", "valor": valor, "unidade": "%", "ref_min": 4.0, "ref_max": 5.6, "alterado": valor > 5.6}])
        if {"has", "icc", "drc"} & set(perfis):
            valor = round(rng.uniform(0.8, 2.4), 2)
            exame(pid, "laboratorial", "Creatinina sérica", rng.randint(5, 40), resultados=[
                {"analito": "Creatinina", "valor": valor, "unidade": "mg/dL", "ref_min": 0.6, "ref_max": 1.3, "alterado": valor > 1.3}])
        if "asma" in perfis or pid == "pac-0005":
            exame(pid, "imagem", "Radiografia de tórax", rng.randint(2, 30), modalidade="RX",
                  laudo="Sem consolidações. Seios costofrênicos livres.",
                  anexos=[{"nome": "rx_torax.jpg", "mime": "image/jpeg", "storage_ref": f"s3://exemplo/{pid}/rx_torax.jpg"}])
    exame("pac-0001", "laboratorial", "INR", 7, resultados=[
        {"analito": "INR", "valor": 2.4, "unidade": "", "ref_min": 2.0, "ref_max": 3.0, "alterado": False}])

    # ------------------------- internações ----------------------------- #
    def internacao(num: int, pid: str, leito: str, ala: str, ini: int, fim: int | None, motivo: str) -> dict:
        return {"_id": f"int-seed{num:03d}", "paciente_id": pid, "leito_id": leito, "ala": ala,
                "entrada": now - timedelta(days=ini), "saida": (now - timedelta(days=fim)) if fim is not None else None,
                "ativa": fim is None, "motivo": motivo, "registrado_por": "seed", "sync_grafo": False}

    internacoes = [
        internacao(1, "pac-0005", "ENF-03", "Enfermaria", 6, 2, "COVID-19 — isolamento e observação"),
        internacao(2, "pac-0006", "ENF-04", "Enfermaria", 5, 1, "Crise asmática"),
        internacao(3, "pac-0007", "ENF-05", "Enfermaria", 3, None, "Descompensação de insuficiência cardíaca"),
        internacao(4, "pac-0009", "UTI-01", "UTI", 4, None, "Choque séptico"),
        internacao(5, "pac-0010", "ENF-01", "Enfermaria", 10, 8, "Pneumonia"),
    ]

    leitos = ([{"_id": f"UTI-{n:02d}", "ala": "UTI", "tipo": "UTI"} for n in range(1, 5)]
              + [{"_id": f"ENF-{n:02d}", "ala": "Enfermaria", "tipo": "Enfermaria"} for n in range(1, 9)]
              + [{"_id": f"PED-{n:02d}", "ala": "Pediatria", "tipo": "Pediatria"} for n in range(1, 5)])

    return {
        "cid10": [{"_id": c, "descricao": d} for c, d in CIDS.items()],
        "medicamentos": list(meds.values()),
        "interacoes": [{"_id": f"{a}|{b}", "a": a, "b": b, "gravidade": g, "efeito": e} for a, b, g, e in _INTERACOES],
        "profissionais": [{"_id": i, "nome": n, "especialidade": esp, "registro": {"tipo": t, "numero": num, "uf": uf},
                           "ativo": True} for i, n, esp, t, num, uf in _PROFISSIONAIS],
        "leitos": leitos,
        "pacientes": pacientes,
        "atendimentos": atendimentos,
        "exames": exames,
        "internacoes": internacoes,
    }
