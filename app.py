"""
Aplicação Web em Streamlit para Preenchimento da Guia Médica Unimed Porto Alegre
("Nota de Procedimento em Hospital - Procedimentos sem Autorização Prévia" / Guia dos Quadradinhos)

Características desta versão:
- Coordenadas remapeadas e calibradas para a nova guia de alta resolução (Quadrados.pdf).
- Fonte de preenchimento na cor PRETA.
- Layout 100% na página principal (sem barra lateral / sidebar).
- Qualificações no ato de 1 a 7 (1 - Médico Assistente até 7 - Outros).
- Inclusão dinâmica de múltiplos profissionais e múltiplos procedimentos.
- Preenchimento automático da "Matrícula do Médico" no cabeçalho exclusivamente quando o
  "1 - Médico Assistente" estiver incluído na guia (caso contrário, permanece em branco).
"""

import io
import textwrap
import unicodedata
from datetime import date, time
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import streamlit as st
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# ==============================================================================
# DIRETÓRIOS E ARQUIVOS PADRÃO
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_PDF_PATH = BASE_DIR / "Quadrados.pdf"
FALLBACK_PDF_PATH = BASE_DIR / "guia dos quadradinhos.pdf"
CBHPM_CSV_PATH = BASE_DIR / "cbhpm.csv"

A4_WIDTH, A4_HEIGHT = A4  # (595.2756, 841.8898)

OPCOES_QUALIFICACAO: Dict[str, str] = {
    "1": "1 - Médico Assistente",
    "2": "2 - Primeiro Auxílio",
    "3": "3 - Segundo Auxílio",
    "4": "4 - Terceiro Auxílio",
    "5": "5 - Anestesiologista",
    "6": "6 - Acompanhamento ou Avaliação",
    "7": "7 - Outros",
}


# ==============================================================================
# DICIONÁRIO DE COORDENADAS CALIBRADAS PARA A NOVA GUIA (REPORTLAB)
# ==============================================================================
OFFSET_GLOBAL_X = 0.0
OFFSET_GLOBAL_Y = 0.0

COORDENADAS: Dict[str, Any] = {
    # --------------------------------------------------------------------------
    # 1. CABEÇALHO DO FORMULÁRIO (Repetido em todas as páginas geradas)
    # --------------------------------------------------------------------------
    "CABECALHO": {
        # Matrícula do Médico (Preenchida apenas se houver 1 - Médico Assistente na guia)
        "matricula_medico_boxes_x": [63.2, 79.9, 96.6, 113.4, 139.5],
        "matricula_medico_y": 691.5,

        # Data do Procedimento (DD / MM / AAAA)
        "data_dia": (191.5, 689.5),
        "data_mes": (223.5, 689.5),
        "data_ano": (256.5, 689.5),

        # Hora Inicial (HH : MM)
        "hora_inicial_hh": (382.0, 696.5),
        "hora_inicial_mm": (415.0, 696.5),

        # Hora Final (HH : MM)
        "hora_final_hh": (382.0, 679.0),
        "hora_final_mm": (415.0, 679.0),

        # Hospital
        "hospital": (98.0, 658.0),

        # Matrícula do Paciente / Beneficiário (Grade de 17 quadradinhos)
        "matricula_paciente_x_inicial": 108.34,
        "matricula_paciente_y": 636.8,
        "matricula_paciente_passo_x": 16.676,

        # Nome do Beneficiário (Paciente)
        "beneficiario": (116.0, 619.0),
    },

    # --------------------------------------------------------------------------
    # 2. COLUNAS HORIZONTAIS (EIXO X) DAS TABELAS DE PROCEDIMENTOS
    # --------------------------------------------------------------------------
    "COLUNAS_TABELA_X": {
        "descricao_x": 60.0,
        "amb_centro_x": 240.0,
        "quant_centro_x": 293.0,
        "perc_centro_x": 340.0,
        "data_hora_1_x": 141.0,
        "data_hora_2_x": 352.0,
        "carimbo_centro_x": 451.5,
    },

    # --------------------------------------------------------------------------
    # 3. COORDENADAS DE CADA UM DOS 4 BLOCOS DE TABELA POR PÁGINA
    # --------------------------------------------------------------------------
    "BLOCOS_TABELA": [
        # --- BLOCO 1 (1ª Tabela - Topo) ---
        {
            "qualificacao_x": 163.0,
            "matricula_exec_boxes_x": [272.8, 289.5, 306.2, 322.9, 348.5],
            "qualificacao_y": 556.5,
            "linha_1_y": 515.0,
            "linha_2_y": 496.0,
            "data_hora_y": 474.0,
            "carimbo_y": 521.0,
        },
        # --- BLOCO 2 (2ª Tabela) ---
        {
            "qualificacao_x": 163.0,
            "matricula_exec_boxes_x": [272.8, 289.5, 306.2, 322.9, 348.5],
            "qualificacao_y": 424.5,
            "linha_1_y": 383.0,
            "linha_2_y": 364.0,
            "data_hora_y": 342.0,
            "carimbo_y": 389.0,
        },
        # --- BLOCO 3 (3ª Tabela) ---
        {
            "qualificacao_x": 163.0,
            "matricula_exec_boxes_x": [272.8, 289.5, 306.2, 322.9, 348.5],
            "qualificacao_y": 290.0,
            "linha_1_y": 248.5,
            "linha_2_y": 229.5,
            "data_hora_y": 207.5,
            "carimbo_y": 254.5,
        },
        # --- BLOCO 4 (4ª Tabela - Rodapé) ---
        {
            "qualificacao_x": 163.0,
            "matricula_exec_boxes_x": [272.8, 289.5, 306.2, 322.9, 348.5],
            "qualificacao_y": 157.0,
            "linha_1_y": 115.5,
            "linha_2_y": 96.5,
            "data_hora_y": 74.5,
            "carimbo_y": 121.5,
        },
    ],
}


# ==============================================================================
# CARREGAMENTO E BUSCA INTELIGENTE DA TABELA CBHPM
# ==============================================================================

def remover_acentos(texto: str) -> str:
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


@st.cache_data
def carregar_cbhpm(caminho_csv: Path) -> pd.DataFrame:
    if caminho_csv.exists():
        df = pd.read_csv(caminho_csv, dtype=str)
        if {"codigo", "descricao"}.issubset(df.columns):
            df = df.fillna("")
            df["label"] = df["codigo"] + " - " + df["descricao"]
            df["busca_norm"] = (
                df["codigo"].str.replace(".", "", regex=False).str.replace("-", "", regex=False)
                + " "
                + df["label"].map(remover_acentos)
            )
            return df

    return pd.DataFrame(columns=["codigo", "descricao", "label", "busca_norm"])


def filtrar_cbhpm(df_cbhpm: pd.DataFrame, termo_busca: str, capitulo: str = "Todos") -> pd.DataFrame:
    df_filtrado = df_cbhpm
    if capitulo != "Todos":
        prefixo = capitulo[0] + "."
        df_filtrado = df_filtrado[df_filtrado["codigo"].str.startswith(prefixo)]

    termo_limpo = remover_acentos(termo_busca).strip()
    if not termo_limpo:
        return df_filtrado

    palavras = [p for p in termo_limpo.split() if p]
    mask = pd.Series(True, index=df_filtrado.index)
    for palavra in palavras:
        mask = mask & df_filtrado["busca_norm"].str.contains(palavra, regex=False, na=False)

    return df_filtrado[mask]


# ==============================================================================
# LÓGICA DE NEGÓCIO E PAGINAÇÃO POR PROFISSIONAL E PROCEDIMENTO
# ==============================================================================

def formatar_percentual(base_calculo: str, urgencia: bool) -> str:
    base_limpa = base_calculo.strip()
    if urgencia:
        return f"{base_limpa}+30%"
    return base_limpa


def dividir_em_chunks(lista: List[Any], tamanho: int) -> List[List[Any]]:
    return [lista[i : i + tamanho] for i in range(0, len(lista), tamanho)]


def montar_tabelas_por_profissional(
    profissionais: List[Dict[str, Any]],
    procedimentos: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Para cada profissional incluído na guia, agrupa os procedimentos realizados de 2 em 2
    (pois cada tabela da guia comporta até 2 procedimentos de um mesmo profissional).
    Retorna a lista linear de tabelas que serão distribuídas de 4 em 4 por página.
    """
    procs_validos = [
        p for p in procedimentos if str(p.get("codigo", "")).strip() or str(p.get("descricao", "")).strip()
    ]

    tabelas: List[Dict[str, Any]] = []
    if not procs_validos or not profissionais:
        return tabelas

    for prof in profissionais:
        chunks_2 = dividir_em_chunks(procs_validos, 2)
        for chunk in chunks_2:
            tabelas.append(
                {
                    "qualificacao": str(prof.get("qualificacao", "1")).strip(),
                    "matricula_executante": str(prof.get("matricula", "")).strip(),
                    "nome_crm": str(prof.get("nome_crm", "")).strip(),
                    "procedimentos": chunk,
                }
            )

    return tabelas


def paginar_tabelas(tabelas: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Agrupa as tabelas de 4 em 4 por folha da guia."""
    if not tabelas:
        return [[]]
    return dividir_em_chunks(tabelas, 4)


def obter_matricula_medico_assistente(profissionais: List[Dict[str, Any]]) -> str:
    """
    Regra do Cabeçalho:
    Se houver um profissional com Qualificação '1' (1 - Médico Assistente) incluído na guia,
    retorna a matrícula dele para preencher o campo 'Matrícula do Médico' no cabeçalho.
    Caso contrário, retorna string vazia (deixa o campo em branco).
    """
    for prof in profissionais:
        if str(prof.get("qualificacao", "")).strip() == "1":
            mat = str(prof.get("matricula", "")).strip()
            if mat:
                return mat
    return ""


# ==============================================================================
# GERAÇÃO DO OVERLAY EM REPORTLAB (FONTE PRETA) E MESCLAGEM COM PYPDF
# ==============================================================================

def desenhar_caixas_matricula_5_digitos(
    c: canvas.Canvas,
    texto: str,
    boxes_x: List[float],
    y: float,
    dx: float,
    dy: float,
    tamanho_fonte: float = 9.5,
) -> None:
    digitos = "".join(ch for ch in str(texto) if ch.isalnum())
    if not digitos:
        return
    c.setFont("Helvetica-Bold", tamanho_fonte)
    digitos = digitos[:5]
    for idx, ch in enumerate(digitos):
        if idx < len(boxes_x):
            c.drawCentredString(boxes_x[idx] + dx, y + dy, ch)


def desenhar_descricao_ajustada(
    c: canvas.Canvas,
    descricao: str,
    x: float,
    y: float,
    dx: float,
    dy: float,
) -> None:
    texto_limpo = " ".join(str(descricao).split())
    if not texto_limpo:
        return
    if len(texto_limpo) <= 30:
        c.setFont("Helvetica", 6.8)
        c.drawString(x + dx, y + dy, texto_limpo)
    else:
        linhas = textwrap.wrap(texto_limpo, width=36)
        c.setFont("Helvetica", 5.8)
        primeira = linhas[0]
        segunda = linhas[1] if len(linhas) > 1 else ""
        if len(linhas) > 2:
            segunda = segunda[:33].rstrip() + "..."
        c.drawString(x + dx, y + dy + 3.2, primeira)
        if segunda:
            c.drawString(x + dx, y + dy - 3.2, segunda)


def criar_overlay_pagina(
    dados_cabecalho: Dict[str, str],
    tabelas_da_pagina: List[Dict[str, Any]],
    page_width: float,
    page_height: float,
    dx_ajuste: float = 0.0,
    dy_ajuste: float = 0.0,
) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(page_width, page_height))

    sx = page_width / A4_WIDTH
    sy = page_height / A4_HEIGHT
    c.scale(sx, sy)

    dx = OFFSET_GLOBAL_X + dx_ajuste
    dy = OFFSET_GLOBAL_Y + dy_ajuste

    # Cor da fonte: PRETO PURO conforme solicitado
    c.setFillColorRGB(0.0, 0.0, 0.0)

    cab_coords = COORDENADAS["CABECALHO"]

    # 1. Matrícula do Médico no Cabeçalho (somente se 1 - Médico Assistente estiver incluído)
    desenhar_caixas_matricula_5_digitos(
        c,
        dados_cabecalho.get("matricula_medico", ""),
        cab_coords["matricula_medico_boxes_x"],
        cab_coords["matricula_medico_y"],
        dx,
        dy,
        tamanho_fonte=9.5,
    )

    # 2. Data do Procedimento (DD / MM / AAAA)
    data_str = dados_cabecalho.get("data_procedimento", "")
    partes_data = data_str.split("/")
    c.setFont("Helvetica-Bold", 8.5)
    if len(partes_data) == 3:
        c.drawCentredString(cab_coords["data_dia"][0] + dx, cab_coords["data_dia"][1] + dy, partes_data[0])
        c.drawCentredString(cab_coords["data_mes"][0] + dx, cab_coords["data_mes"][1] + dy, partes_data[1])
        c.drawCentredString(cab_coords["data_ano"][0] + dx, cab_coords["data_ano"][1] + dy, partes_data[2])

    # 3. Hora Inicial e Hora Final
    hora_ini = dados_cabecalho.get("hora_inicial", "")
    if ":" in hora_ini:
        hh_i, mm_i = hora_ini.split(":", 1)
        c.drawCentredString(cab_coords["hora_inicial_hh"][0] + dx, cab_coords["hora_inicial_hh"][1] + dy, hh_i)
        c.drawCentredString(cab_coords["hora_inicial_mm"][0] + dx, cab_coords["hora_inicial_mm"][1] + dy, mm_i)

    hora_fim = dados_cabecalho.get("hora_final", "")
    if ":" in hora_fim:
        hh_f, mm_f = hora_fim.split(":", 1)
        c.drawCentredString(cab_coords["hora_final_hh"][0] + dx, cab_coords["hora_final_hh"][1] + dy, hh_f)
        c.drawCentredString(cab_coords["hora_final_mm"][0] + dx, cab_coords["hora_final_mm"][1] + dy, mm_f)

    # 4. Hospital
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(cab_coords["hospital"][0] + dx, cab_coords["hospital"][1] + dy, dados_cabecalho.get("hospital", ""))

    # 5. Matrícula do Paciente (17 quadradinhos)
    mat_pac = "".join(ch for ch in dados_cabecalho.get("matricula_paciente", "") if ch.isalnum())[:17]
    c.setFont("Helvetica-Bold", 9.5)
    x_ini_pac = cab_coords["matricula_paciente_x_inicial"]
    y_pac = cab_coords["matricula_paciente_y"]
    passo_pac = cab_coords["matricula_paciente_passo_x"]
    for idx, ch in enumerate(mat_pac):
        c.drawCentredString(x_ini_pac + (idx * passo_pac) + dx, y_pac + dy, ch)

    # 6. Beneficiário (Nome do Paciente)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(
        cab_coords["beneficiario"][0] + dx,
        cab_coords["beneficiario"][1] + dy,
        dados_cabecalho.get("beneficiario", ""),
    )

    # 7. Blocos de Tabela (até 4 tabelas por página)
    col_x = COORDENADAS["COLUNAS_TABELA_X"]
    blocos_coords = COORDENADAS["BLOCOS_TABELA"]
    data_hora_espelhada = f"{data_str} {hora_ini}".strip()

    for idx_bloco, dados_tabela in enumerate(tabelas_da_pagina):
        if idx_bloco >= len(blocos_coords) or not dados_tabela:
            continue

        procs_preenchidos = dados_tabela.get("procedimentos", [])
        if not procs_preenchidos:
            continue

        b_coord = blocos_coords[idx_bloco]

        # Qualificação no ato deste profissional
        qual_bloco = str(dados_tabela.get("qualificacao", ""))
        if qual_bloco:
            c.setFont("Helvetica-Bold", 9.5)
            c.drawCentredString(b_coord["qualificacao_x"] + dx, b_coord["qualificacao_y"] + dy, qual_bloco)

        # Matrícula do profissional executante desta tabela
        desenhar_caixas_matricula_5_digitos(
            c,
            dados_tabela.get("matricula_executante", ""),
            b_coord["matricula_exec_boxes_x"],
            b_coord["qualificacao_y"],
            dx,
            dy,
            tamanho_fonte=9.5,
        )

        # Até 2 procedimentos na tabela
        linhas_y = [b_coord["linha_1_y"], b_coord["linha_2_y"]]
        for idx_linha, proc in enumerate(procs_preenchidos[:2]):
            y_linha = linhas_y[idx_linha]

            desenhar_descricao_ajustada(
                c,
                proc.get("descricao", ""),
                col_x["descricao_x"],
                y_linha,
                dx,
                dy,
            )

            c.setFont("Helvetica", 6.8)
            c.drawCentredString(col_x["amb_centro_x"] + dx, y_linha + dy, str(proc.get("codigo", "")))

            c.setFont("Helvetica-Bold", 7.2)
            c.drawCentredString(col_x["quant_centro_x"] + dx, y_linha + dy, str(proc.get("quantidade", 1)))

            c.setFont("Helvetica-Bold", 6.5)
            c.drawCentredString(col_x["perc_centro_x"] + dx, y_linha + dy, str(proc.get("percentual", "100%")))

        # Data / Hora Inicial abaixo da tabela
        c.setFont("Helvetica", 7.0)
        c.drawString(col_x["data_hora_1_x"] + dx, b_coord["data_hora_y"] + dy, data_hora_espelhada)
        if len(procs_preenchidos) >= 2:
            c.drawString(col_x["data_hora_2_x"] + dx, b_coord["data_hora_y"] + dy, data_hora_espelhada)

        # Carimbo e Assinatura deste profissional
        texto_carimbo = dados_tabela.get("nome_crm", "").strip()
        if texto_carimbo:
            c.setFont("Helvetica-Bold", 6.8)
            if " - " in texto_carimbo:
                partes_carimbo = [p.strip() for p in texto_carimbo.split(" - ", 1)]
                c.drawCentredString(col_x["carimbo_centro_x"] + dx, b_coord["carimbo_y"] + 5.0 + dy, partes_carimbo[0])
                c.drawCentredString(col_x["carimbo_centro_x"] + dx, b_coord["carimbo_y"] - 4.5 + dy, partes_carimbo[1])
            else:
                linhas_carimbo = textwrap.wrap(texto_carimbo, width=32)
                for i_c, ln_c in enumerate(linhas_carimbo[:2]):
                    offset_l = 4.0 - (i_c * 8.5)
                    c.drawCentredString(col_x["carimbo_centro_x"] + dx, b_coord["carimbo_y"] + offset_l + dy, ln_c)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


def gerar_pdf_final(
    caminho_template: Path,
    dados_cabecalho: Dict[str, str],
    profissionais: List[Dict[str, Any]],
    procedimentos: List[Dict[str, Any]],
    dx_ajuste: float = 0.0,
    dy_ajuste: float = 0.0,
    incluir_fundo: bool = True,
) -> bytes:
    todas_tabelas = montar_tabelas_por_profissional(profissionais, procedimentos)
    paginas_tabelas = paginar_tabelas(todas_tabelas)
    writer = PdfWriter()

    for tabelas_da_pagina in paginas_tabelas:
        reader_template = PdfReader(str(caminho_template))
        pagina_base = reader_template.pages[0]

        largura_real = float(pagina_base.mediabox.width)
        altura_real = float(pagina_base.mediabox.height)

        overlay_bytes = criar_overlay_pagina(
            dados_cabecalho=dados_cabecalho,
            tabelas_da_pagina=tabelas_da_pagina,
            page_width=largura_real,
            page_height=altura_real,
            dx_ajuste=dx_ajuste,
            dy_ajuste=dy_ajuste,
        )

        reader_overlay = PdfReader(io.BytesIO(overlay_bytes))
        if incluir_fundo:
            pagina_anexada = writer.add_page(pagina_base)
            pagina_anexada.merge_page(reader_overlay.pages[0])
        else:
            writer.add_page(reader_overlay.pages[0])

    output_buffer = io.BytesIO()
    writer.write(output_buffer)
    output_buffer.seek(0)
    return output_buffer.read()


# ==============================================================================
# INTERFACE WEB NO STREAMLIT (100% NA PÁGINA PRINCIPAL — SEM BARRA LATERAL)
# ==============================================================================

def main() -> None:
    st.set_page_config(
        page_title="Guia Médica Unimed - Preenchimento Digital",
        page_icon="🩺",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    st.title("🩺 Preenchimento de Guia Médica — Unimed Porto Alegre")
    st.caption(
        "**Nota de Procedimento em Hospital (Procedimentos sem Autorização Prévia)** • "
        "Base CBHPM 2014 integrada (4.498 procedimentos)"
    )

    caminho_template = TEMPLATE_PDF_PATH if TEMPLATE_PDF_PATH.exists() else FALLBACK_PDF_PATH
    if not caminho_template.exists():
        st.error(
            "Arquivo de template (`Quadrados.pdf` ou `guia dos quadradinhos.pdf`) não encontrado na pasta do projeto."
        )
        st.stop()

    df_cbhpm = carregar_cbhpm(CBHPM_CSV_PATH)

    # Inicializa lista dinâmica de profissionais no st.session_state
    if "profissionais" not in st.session_state:
        st.session_state.profissionais = [
            {
                "qualificacao": "1",
                "matricula": "",
                "nome_crm": "",
            }
        ]

    # Inicializa lista dinâmica de procedimentos no st.session_state
    if "procedimentos" not in st.session_state:
        st.session_state.procedimentos = [
            {
                "codigo": "",
                "descricao": "",
                "quantidade": 1,
                "base_calculo": "100%",
                "urgencia": False,
            }
        ]

    # --------------------------------------------------------------------------
    # SEÇÃO 1: DADOS DO CABEÇALHO (GERAL)
    # --------------------------------------------------------------------------
    st.subheader("1. Dados do Cabeçalho (Geral)")
    with st.container(border=True):
        col_h1, col_h2, col_h3 = st.columns([1.4, 1.6, 1.2])
        with col_h1:
            hospitais_poa = [
                "",
                "Hospital de Clínicas de Porto Alegre (HCPA)",
                "Hospital Moinhos de Vento",
                "Santa Casa de Misericórdia",
                "Hospital Mãe de Deus",
                "Hospital São Lucas da PUCRS",
                "Outros",
            ]
            hospital_selecionado = st.selectbox(
                "Hospital",
                options=hospitais_poa,
                format_func=lambda h: "Selecione o hospital..." if h == "" else h,
                index=0,
            )
            if hospital_selecionado == "Outros":
                hospital_final = st.text_input("Especifique o Hospital", value="")
            else:
                hospital_final = hospital_selecionado

        with col_h2:
            paciente_nome = st.text_input(
                "Beneficiário (Nome do Paciente)",
                value="",
                placeholder="Digite o nome completo do paciente",
            )
        with col_h3:
            paciente_matricula = st.text_input(
                "Matrícula do Paciente (17 dígitos)",
                value="",
                max_chars=17,
                placeholder="Até 17 dígitos",
            )

        col_c1, col_c2, col_c3, col_c4 = st.columns([1.1, 1.0, 1.0, 1.4])
        with col_c1:
            data_procedimento = st.date_input(
                "Data do Procedimento",
                value=date.today(),
                format="DD/MM/YYYY",
            )
        with col_c2:
            hora_inicial = st.time_input(
                "Hora Inicial",
                value=time(8, 0),
                step=300,
            )
        with col_c3:
            hora_final = st.time_input(
                "Hora Final",
                value=time(9, 0),
                step=300,
            )

        # A matrícula do médico no cabeçalho reflete automaticamente o 1 - Médico Assistente (se incluído)
        with col_c4:
            mat_cabecalho_preview = obter_matricula_medico_assistente(st.session_state.profissionais)
            st.text_input(
                "Matrícula do Médico no Cabeçalho (Automático)",
                value=mat_cabecalho_preview if mat_cabecalho_preview else "Em branco (sem Médico Assistente)",
                disabled=True,
                help="Preenchido automaticamente com a matrícula do '1 - Médico Assistente'. Caso não seja incluído na guia, fica em branco no PDF.",
            )

    data_formatada = data_procedimento.strftime("%d/%m/%Y")
    hora_ini_formatada = hora_inicial.strftime("%H:%M")
    hora_fim_formatada = hora_final.strftime("%H:%M")

    # --------------------------------------------------------------------------
    # SEÇÃO 2: PROFISSIONAIS EXECUTANTES (DINÂMICO NA PÁGINA PRINCIPAL)
    # --------------------------------------------------------------------------
    st.subheader("2. Profissionais Executantes (Qualificação, Matrícula e Carimbo)")

    col_p_add, col_p_rem, col_p_info = st.columns([1.3, 1.3, 2.4])
    with col_p_add:
        if st.button("➕ Adicionar Profissional", use_container_width=True, type="primary"):
            prox_qual = "2" if len(st.session_state.profissionais) == 1 else "5"
            st.session_state.profissionais.append(
                {
                    "qualificacao": prox_qual,
                    "matricula": "",
                    "nome_crm": "",
                }
            )
            st.rerun()
    with col_p_rem:
        if st.button(
            "🗑️ Remover Último Profissional",
            use_container_width=True,
            disabled=len(st.session_state.profissionais) <= 1,
        ):
            st.session_state.profissionais.pop()
            st.rerun()
    with col_p_info:
        st.caption(
            "ℹ️ Se o **1 - Médico Assistente** for incluído abaixo, sua matrícula preencherá automaticamente "
            "o campo *Matrícula do Médico* no topo da guia."
        )

    profissionais_processados: List[Dict[str, Any]] = []
    chaves_qual = list(OPCOES_QUALIFICACAO.keys())

    for idx_prof, prof_item in enumerate(st.session_state.profissionais):
        with st.container(border=True):
            st.markdown(f"**Profissional #{idx_prof + 1}**")
            cp_qual, cp_mat, cp_nome = st.columns([1.4, 1.0, 2.2])

            with cp_qual:
                qual_atual = str(prof_item.get("qualificacao", "1"))
                idx_q = chaves_qual.index(qual_atual) if qual_atual in chaves_qual else 0
                qual_sel = st.selectbox(
                    "Qualificação no Ato",
                    options=chaves_qual,
                    format_func=lambda k: OPCOES_QUALIFICACAO[k],
                    index=idx_q,
                    key=f"prof_qual_{idx_prof}",
                )
                st.session_state.profissionais[idx_prof]["qualificacao"] = qual_sel

            with cp_mat:
                mat_sel = st.text_input(
                    "Matrícula Unimed (5 dígitos)",
                    value=str(prof_item.get("matricula", "")),
                    max_chars=6,
                    placeholder="Ex: 0000-0",
                    key=f"prof_mat_{idx_prof}",
                )
                st.session_state.profissionais[idx_prof]["matricula"] = mat_sel

            with cp_nome:
                nome_crm_sel = st.text_input(
                    "Nome do Médico e CRM (Carimbo e Assinatura)",
                    value=str(prof_item.get("nome_crm", "")),
                    placeholder="Ex: Nome do Médico - CRM 00000",
                    help="Use ' - ' para separar a 1ª linha (Nome) da 2ª linha (CRM) no carimbo.",
                    key=f"prof_nome_{idx_prof}",
                )
                st.session_state.profissionais[idx_prof]["nome_crm"] = nome_crm_sel

            profissionais_processados.append(
                {
                    "qualificacao": qual_sel,
                    "matricula": mat_sel,
                    "nome_crm": nome_crm_sel,
                }
            )

    # --------------------------------------------------------------------------
    #SEÇÃO 3: PROCEDIMENTOS REALIZADOS (CBHPM)
    # --------------------------------------------------------------------------
    st.subheader("3. Procedimentos Realizados (CBHPM)")

    with st.expander("🔍 Localizar Procedimentos no Catálogo CBHPM (4.498 Procedimentos)", expanded=False):
        col_f1, col_f2 = st.columns([2.5, 1.5])
        with col_f1:
            termo_catalogo = st.text_input(
                "Pesquisar por nome (sem precisar de acento) ou código CBHPM",
                value="",
                placeholder="Ex: colecistectomia, hernia, bloqueio, cesariana, 3.10.05...",
                key="busca_catalogo_global",
            )
        with col_f2:
            capitulo_catalogo = st.selectbox(
                "Filtrar por Capítulo da CBHPM",
                options=[
                    "Todos",
                    "3 - Procedimentos Cirúrgicos e Invasivos",
                    "4 - Procedimentos Diagnósticos e Terapêuticos",
                    "2 - Procedimentos Clínicos",
                    "1 - Procedimentos Gerais (Consultas / Visitas / UTI)",
                ],
                index=0,
            )

        df_resultado_cat = filtrar_cbhpm(df_cbhpm, termo_catalogo, capitulo_catalogo)
        st.markdown(f"**{len(df_resultado_cat)}** procedimento(s) encontrado(s):")
        st.dataframe(
            df_resultado_cat[["codigo", "descricao"]].head(100),
            use_container_width=True,
            hide_index=True,
            column_config={
                "codigo": st.column_config.TextColumn("Código CBHPM (AMB)", width="small"),
                "descricao": st.column_config.TextColumn("Descrição Oficial CBHPM", width="large"),
            },
        )
        if not df_resultado_cat.empty:
            col_add_cat1, col_add_cat2 = st.columns([3.0, 1.0])
            with col_add_cat1:
                escolha_cat = st.selectbox(
                    "Selecione um resultado acima para incluir na guia:",
                    options=df_resultado_cat["label"].head(100).tolist(),
                    key="select_add_catalogo",
                )
            with col_add_cat2:
                st.write("")
                if st.button("➕ Incluir na Guia", use_container_width=True):
                    cod_escolhido, desc_escolhida = escolha_cat.split(" - ", 1)
                    if (
                        len(st.session_state.procedimentos) == 1
                        and not st.session_state.procedimentos[0].get("codigo")
                    ):
                        st.session_state.procedimentos[0]["codigo"] = cod_escolhido.strip()
                        st.session_state.procedimentos[0]["descricao"] = desc_escolhida.strip()
                    else:
                        st.session_state.procedimentos.append(
                            {
                                "codigo": cod_escolhido.strip(),
                                "descricao": desc_escolhida.strip(),
                                "quantidade": 1,
                                "base_calculo": "70%" if st.session_state.procedimentos else "100%",
                                "urgencia": st.session_state.procedimentos[-1]["urgencia"]
                                if st.session_state.procedimentos
                                else False,
                            }
                        )
                    st.rerun()

    col_btn_add, col_btn_rem, col_metric = st.columns([1.3, 1.3, 2.4])
    with col_btn_add:
        if st.button("➕ Adicionar Procedimento", use_container_width=True, type="primary"):
            st.session_state.procedimentos.append(
                {
                    "codigo": "",
                    "descricao": "",
                    "quantidade": 1,
                    "base_calculo": "70%",
                    "urgencia": st.session_state.procedimentos[-1]["urgencia"]
                    if st.session_state.procedimentos
                    else False,
                }
            )
            st.rerun()
    with col_btn_rem:
        if st.button(
            "🗑️ Remover Último Procedimento",
            use_container_width=True,
            disabled=len(st.session_state.procedimentos) <= 1,
        ):
            st.session_state.procedimentos.pop()
            st.rerun()

    opcoes_base = {
        "100%": "100% (Procedimento Principal)",
        "70%": "70% (Diferentes Vias)",
        "50%": "50% (Mesma Via)",
    }

    procedimentos_processados: List[Dict[str, Any]] = []

    for idx, item in enumerate(st.session_state.procedimentos):
        with st.container(border=True):
            st.markdown(f"**Procedimento #{idx + 1}**")

            c_filtro, c_proc = st.columns([1.5, 3.5])
            with c_filtro:
                filtro_item = st.text_input(
                    "🔎 Filtrar CBHPM (palavra ou código)",
                    value="",
                    placeholder="Digite nome ou código para buscar...",
                    key=f"proc_filtro_{idx}",
                )

            df_opcoes_item = filtrar_cbhpm(df_cbhpm, filtro_item)
            labels_filtrados = [""] + df_opcoes_item["label"].head(300).tolist()

            codigo_salvo = item.get("codigo", "")
            descricao_salva = item.get("descricao", "")
            label_salvo = f"{codigo_salvo} - {descricao_salva}" if codigo_salvo else ""

            if label_salvo and label_salvo not in labels_filtrados:
                labels_filtrados.insert(1, label_salvo)

            if filtro_item.strip() and len(labels_filtrados) > 1:
                idx_box = 1
            elif label_salvo in labels_filtrados:
                idx_box = labels_filtrados.index(label_salvo)
            else:
                idx_box = 0

            with c_proc:
                label_escolhido = st.selectbox(
                    "Selecionar Procedimento da CBHPM",
                    options=labels_filtrados,
                    format_func=lambda x: "Selecione ou pesquise um procedimento..." if x == "" else x,
                    index=idx_box,
                    key=f"proc_select_{idx}",
                )
                if label_escolhido and " - " in label_escolhido:
                    codigo_cbhpm, descricao_cbhpm = label_escolhido.split(" - ", 1)
                else:
                    codigo_cbhpm, descricao_cbhpm = "", ""

                st.session_state.procedimentos[idx]["codigo"] = codigo_cbhpm
                st.session_state.procedimentos[idx]["descricao"] = descricao_cbhpm

            c_qtd, c_base, c_urg, c_perc, c_dt = st.columns([0.9, 1.6, 1.1, 1.1, 1.5])

            with c_qtd:
                qtd = st.number_input(
                    "Quant.",
                    min_value=1,
                    max_value=99,
                    value=int(item.get("quantidade", 1)),
                    step=1,
                    key=f"proc_qtd_{idx}",
                )
                st.session_state.procedimentos[idx]["quantidade"] = qtd

            with c_base:
                lista_bases = list(opcoes_base.keys())
                base_atual = item.get("base_calculo", "100%")
                idx_base = lista_bases.index(base_atual) if base_atual in lista_bases else 0
                base_sel = st.selectbox(
                    "Base de Cálculo",
                    options=lista_bases,
                    format_func=lambda k: opcoes_base[k],
                    index=idx_base,
                    key=f"proc_base_{idx}",
                )
                st.session_state.procedimentos[idx]["base_calculo"] = base_sel

            with c_urg:
                st.write("")
                urg = st.checkbox(
                    "Urgência (+30%)",
                    value=bool(item.get("urgencia", False)),
                    key=f"proc_urg_{idx}",
                )
                st.session_state.procedimentos[idx]["urgencia"] = urg

            perc_final = formatar_percentual(base_sel, urg)

            with c_perc:
                st.text_input(
                    "Campo 'Perc.'",
                    value=perc_final,
                    disabled=True,
                    key=f"proc_perc_view_{idx}",
                )

            with c_dt:
                st.text_input(
                    "Data / Hora Inicial",
                    value=f"{data_formatada} {hora_ini_formatada}",
                    disabled=True,
                    key=f"proc_dt_view_{idx}",
                )

            procedimentos_processados.append(
                {
                    "codigo": codigo_cbhpm,
                    "descricao": descricao_cbhpm,
                    "quantidade": qtd,
                    "percentual": perc_final,
                }
            )

    tabelas_geradas = montar_tabelas_por_profissional(profissionais_processados, procedimentos_processados)
    total_tabelas = len(tabelas_geradas)
    total_paginas = max(1, (total_tabelas + 3) // 4)
    with col_metric:
        st.markdown(
            f"📄 **Paginação:** `{len(profissionais_processados)}` profissional(is) × "
            f"`{len(procedimentos_processados)}` proc(s) → `{total_tabelas}` tabela(s) → **`{total_paginas}` página(s)**"
        )

    # --------------------------------------------------------------------------
    # SEÇÃO 4: GERAÇÃO E DOWNLOAD DO PDF PREENCHIDO
    # --------------------------------------------------------------------------
    st.divider()
    st.subheader("4. Baixar Guia Preenchida (PDF)")

    with st.expander("⚙️ Opções Avançadas de Impressão e Ajuste Fino (Opcional)", expanded=False):
        c_opt1, c_opt2, c_opt3 = st.columns([1.6, 1.2, 1.2])
        with c_opt1:
            modo_fundo = st.radio(
                "Plano de fundo do PDF:",
                options=["COM_FUNDO", "SO_TEXTO"],
                format_func=lambda m: (
                    "Guia Original Quadrados.pdf + Dados (Folha Branca)"
                    if m == "COM_FUNDO"
                    else "Somente Textos (Imprimir sobre guia física)"
                ),
                index=0,
            )
        with c_opt2:
            dx_ajuste = st.slider("Deslocamento Horizontal (Eixo X)", -25.0, 25.0, 0.0, 0.5)
        with c_opt3:
            dy_ajuste = st.slider("Deslocamento Vertical (Eixo Y)", -25.0, 25.0, 0.0, 0.5)

    # Regra do Cabeçalho: Matrícula do Médico só é preenchida se houver 1 - Médico Assistente
    matricula_cabecalho_final = obter_matricula_medico_assistente(profissionais_processados)

    dados_cabecalho = {
        "matricula_medico": matricula_cabecalho_final,
        "data_procedimento": data_formatada,
        "hora_inicial": hora_ini_formatada,
        "hora_final": hora_fim_formatada,
        "hospital": hospital_final,
        "matricula_paciente": paciente_matricula,
        "beneficiario": paciente_nome,
    }

    pdf_bytes = gerar_pdf_final(
        caminho_template=caminho_template,
        dados_cabecalho=dados_cabecalho,
        profissionais=profissionais_processados,
        procedimentos=procedimentos_processados,
        dx_ajuste=dx_ajuste,
        dy_ajuste=dy_ajuste,
        incluir_fundo=(modo_fundo == "COM_FUNDO"),
    )

    primeiro_nome = paciente_nome.strip().split()[0].lower() if paciente_nome.strip() else "paciente"
    nome_arquivo_saida = f"guia_unimed_{primeiro_nome}_{data_procedimento.strftime('%Y%m%d')}.pdf"

    st.download_button(
        label="📥 Baixar Guia Preenchida (PDF)",
        data=pdf_bytes,
        file_name=nome_arquivo_saida,
        mime="application/pdf",
        type="primary",
        use_container_width=True,
    )


if __name__ == "__main__":
    main()
