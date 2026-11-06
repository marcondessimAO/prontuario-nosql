"""Identidade visual: tipografia, espaçamento e componentes sóbrios (sem emojis).

O tema de cores fica em .streamlit/config.toml; aqui apenas ajustes finos de CSS.
O HTML injetado é estático (nenhum dado de paciente é interpolado nele).
"""
from __future__ import annotations

import streamlit as st

PALETA = {
    "primaria": "#0B5CAD",
    "borda": "#DCE3EC",
    "texto_suave": "#5B6B7B",
}

# Cores de fundo por classificação de risco (Manchester) e por status de leito
FUNDO_RISCO = {
    "vermelho": "#F8D7DA", "laranja": "#FFE3CC", "amarelo": "#FFF3C4",
    "verde": "#D8F0DE", "azul": "#D6E4F5",
}
FUNDO_LEITO = {"ocupado": "#F8D7DA", "livre": "#D8F0DE"}

_CSS = f"""
<style>
.block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1280px; }}
h1 {{ font-size: 1.7rem; font-weight: 600; letter-spacing: -0.01em;
     padding-bottom: 0.6rem; margin-bottom: 1.1rem; border-bottom: 1px solid {PALETA['borda']}; }}
h2, h3 {{ font-weight: 600; letter-spacing: -0.005em; }}
[data-testid="stMetric"] {{ background: #FFFFFF; border: 1px solid {PALETA['borda']};
     border-radius: 6px; padding: 0.8rem 1rem; }}
[data-testid="stMetricLabel"] p {{ color: {PALETA['texto_suave']}; text-transform: uppercase;
     font-size: 0.7rem; letter-spacing: 0.04em; white-space: normal; line-height: 1.25; }}
[data-testid="stSidebar"] {{ border-right: 1px solid {PALETA['borda']}; }}
[data-testid="stExpander"] {{ border: 1px solid {PALETA['borda']}; border-radius: 6px; }}
.stButton > button {{ border-radius: 4px; font-weight: 500; }}
[data-testid="stDataFrame"] {{ border: 1px solid {PALETA['borda']}; border-radius: 6px; }}
#MainMenu, footer {{ visibility: hidden; }}
</style>
"""


def aplicar() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
