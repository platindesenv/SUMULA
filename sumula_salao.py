# -*- coding: utf-8 -*-

import gc
import json
import re
import unicodedata

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions

from pathlib import Path

# =========================================================
# UTILITARIOS
# =========================================================

def find_team_blocks(items):
    """
    Localiza os blocos dos dois times procurando o cabecalho
    'Registro' da tabela de jogadores.

    Depois procura o nome do time imediatamente acima.

    Retorna:
    {
        "mandante": {
            "nome": "...",
            "titulo": item
        },
        "visitante": {
            "nome": "...",
            "titulo": item
        }
    }
    """

    headers_registro = []

    # =====================================================
    # LOCALIZA OS CABECALHOS "REGISTRO" DOS JOGADORES
    # =====================================================

    for item in items:

        texto_norm = normalize_key(item["text"])

        if texto_norm != "registro":
            continue

        # coluna esquerda onde fica "Registro"
        if not (10 <= item["x1"] <= 80):
            continue

        # evita o "Registro" de outras partes da sumula
        if item["y1"] < 150:
            continue

        headers_registro.append(item)

    # ordena de cima para baixo
    headers_registro = sorted(
        headers_registro,
        key=lambda i: -i["y1"]
    )

    blocos = []

    # =====================================================
    # PARA CADA "REGISTRO", PROCURA O NOME DO TIME ACIMA
    # =====================================================

    for header in headers_registro:

        candidatos = []

        for item in items:

            # nome precisa estar acima do cabecalho
            diferenca_y = item["y1"] - header["y1"]

            if not (5 <= diferenca_y <= 30):
                continue

            # nome do time normalmente começa na esquerda
            if item["x1"] > 200:
                continue

            texto = normalize_text(item["text"])
            texto_norm = normalize_key(texto)

            # ignora labels que nao sao nome de time
            if texto_norm in [
                "registro",
                "jogadores",
                "n",
                "amar",
                "verm",
                "substituicoes"
            ]:
                continue

            if "federacao paulista" in texto_norm:
                continue

            if len(texto) < 3:
                continue

            candidatos.append(item)

        if not candidatos:
            continue

        # pega o texto mais proximo verticalmente do cabecalho
        titulo = min(
            candidatos,
            key=lambda i: abs(i["y1"] - header["y1"])
        )

        # evita duplicar o mesmo bloco
        if any(
            abs(b["titulo"]["y1"] - titulo["y1"]) < 5
            for b in blocos
        ):
            continue

        blocos.append({
            "nome": titulo["text"],
            "titulo": titulo
        })

    # =====================================================
    # ORDENA:
    # BLOCO MAIS ALTO = MANDANTE
    # BLOCO MAIS BAIXO = VISITANTE
    # =====================================================

    blocos = sorted(
        blocos,
        key=lambda b: -b["titulo"]["y1"]
    )

    retorno = {
        "mandante": None,
        "visitante": None
    }

    if len(blocos) >= 1:
        retorno["mandante"] = blocos[0]

    if len(blocos) >= 2:
        retorno["visitante"] = blocos[1]

    return retorno
    
def normalize_text(text):
    if text is None:
        return ""

    text = str(text).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_key(text):
    text = normalize_text(text)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    return text


def is_time(text):
    return bool(re.fullmatch(r"\d{2}:\d{2}", normalize_text(text)))


def is_time_pair(text):
    return bool(re.fullmatch(r"\d{2}:\d{2}\s+\d{2}:\d{2}", normalize_text(text)))


def is_numeric(text):
    return bool(re.fullmatch(r"\d+", normalize_text(text)))


def try_int(value):
    try:
        return int(str(value).strip())
    except Exception:
        return None


def clean_team_name(text):
    text = normalize_text(text)
    return text


def extract_items_from_doc(result):
    items = []

    for item, level in result.document.iterate_items():
        text = getattr(item, "text", None)

        if not text or not hasattr(item, "prov"):
            continue

        text = normalize_text(text)

        for prov in item.prov:
            bbox = prov.bbox

            items.append({
                "text": text,
                "page": prov.page_no,
                "x1": round(bbox.l, 2),
                "y1": round(bbox.t, 2),
                "x2": round(bbox.r, 2),
                "y2": round(bbox.b, 2),
            })

    return items


def in_box(item, x_min, x_max, y_min, y_max):
    return (
        x_min <= item["x1"] <= x_max
        and y_min <= item["y1"] <= y_max
    )


def get_box_items(items, x_min, x_max, y_min, y_max):
    return [
        item for item in items
        if in_box(item, x_min, x_max, y_min, y_max)
    ]


def get_first_text(items, x_min, x_max, y_min, y_max, regex=None):
    encontrados = get_box_items(items, x_min, x_max, y_min, y_max)
    encontrados = sorted(encontrados, key=lambda i: (i["x1"], -i["y1"]))

    for item in encontrados:
        if regex:
            if re.fullmatch(regex, item["text"]):
                return item["text"]
        else:
            return item["text"]

    return None


def get_unique_box_texts(items, x_min, x_max, y_min, y_max):
    encontrados = get_box_items(items, x_min, x_max, y_min, y_max)
    encontrados = sorted(encontrados, key=lambda i: (-i["y1"], i["x1"]))

    vistos = set()
    saida = []

    for item in encontrados:
        chave = (item["text"], item["x1"], item["y1"])
        if chave not in vistos:
            vistos.add(chave)
            saida.append(item)

    return saida


def cluster_rows(items, y_tolerance=3.0):
    """
    Agrupa textos que estao praticamente na mesma linha.
    """
    if not items:
        return []

    items_sorted = sorted(items, key=lambda i: (-i["y1"], i["x1"]))
    rows = []

    for item in items_sorted:
        placed = False

        for row in rows:
            if abs(row["y"] - item["y1"]) <= y_tolerance:
                row["items"].append(item)
                row["y_values"].append(item["y1"])
                row["y"] = sum(row["y_values"]) / len(row["y_values"])
                placed = True
                break

        if not placed:
            rows.append({
                "y": item["y1"],
                "y_values": [item["y1"]],
                "items": [item]
            })

    for row in rows:
        row["items"] = sorted(row["items"], key=lambda i: i["x1"])

    rows = sorted(rows, key=lambda r: -r["y"])
    return rows


def row_text(row):
    return " ".join(item["text"] for item in row["items"]).strip()


def find_team_block_title(items, team_name):
    """
    Procura o titulo do bloco do time (na area das tabelas dos jogadores),
    ignorando o nome do time no cabecalho superior.
    """
    candidatos = []

    for item in items:
        if normalize_key(item["text"]) == normalize_key(team_name):
            # evita cabecalho do topo
            if 300 <= item["y1"] <= 720 and item["x1"] <= 120:
                candidatos.append(item)

    if not candidatos:
        return None

    # pega o titulo mais alto daquele bloco
    candidatos = sorted(candidatos, key=lambda i: -i["y1"])
    return candidatos[0]

def parse_player_row(row, amarelo_x=None, vermelho_x=None):
    """
    Le uma linha de jogador.

    Exemplos:
    176068 BENICIO EMMANUEL SALES BRAGA | 01 | 22:14
    209511 EDUARDO SANCHES VICENTE       | 08 |       | ***
    209511 EDUARDO SANCHES VICENTE       | 08 |       | **:**

    Regras:
    - numero = numero da camisa
    - horario normal de cartao: 08:30
    - cartao fora do horario pode vir como **:**
    - algumas sumulas podem trazer *, ** ou *** como marcacao
    """

    left_items = [
        i for i in row["items"]
        if i["x1"] <= 190
    ]

    right_items = [
        i for i in row["items"]
        if 190 < i["x1"] <= 320
    ]

    if not left_items:
        return None

    left_text = " ".join(
        i["text"] for i in left_items
    ).strip()

    left_norm = normalize_key(left_text)

    if any(chave in left_norm for chave in [
        "tecnico",
        "aux. tecnico",
        "aux tecnico",
        "prep. fisico",
        "prep fisico",
        "massagista",
        "med/fis/enf",
        "med fis enf"
    ]):
        return None

    match = re.match(
        r"^(\d+)\s+(.+)$",
        left_text
    )

    if not match:
        return None

    registro = match.group(1)
    nome = match.group(2).strip()

    numero = None
    amarelo = None
    vermelho = None
    cartoes_encontrados = []

    for item in right_items:
        texto = normalize_text(item["text"])

        tokens = re.findall(
            r"\*{2}:\*{2}|\d{2}:\d{2}|\*+|\d+",
            texto
        )

        encontrou_numero_neste_item = False

        for token in tokens:
            if numero is None and re.fullmatch(r"\d+", token):
                numero = token.zfill(2)
                encontrou_numero_neste_item = True
                continue

            eh_cartao = (
                is_time(token)
                or token == "**:**"
                or bool(re.fullmatch(r"\*+", token))
            )

            if eh_cartao:
                cartoes_encontrados.append({
                    "valor": token,
                    "x": item["x1"],
                    "mesmo_item_numero": encontrou_numero_neste_item
                })

    if len(cartoes_encontrados) >= 2:
        amarelo = cartoes_encontrados[0]["valor"]
        vermelho = cartoes_encontrados[1]["valor"]

    elif len(cartoes_encontrados) == 1:
        cartao = cartoes_encontrados[0]

        if cartao["mesmo_item_numero"]:
            amarelo = cartao["valor"]

        elif amarelo_x is not None and vermelho_x is not None:
            distancia_amarelo = abs(cartao["x"] - amarelo_x)
            distancia_vermelho = abs(cartao["x"] - vermelho_x)

            if distancia_vermelho < distancia_amarelo:
                vermelho = cartao["valor"]
            else:
                amarelo = cartao["valor"]

        else:
            amarelo = cartao["valor"]

    return {
        "registro": registro,
        "nome": nome,
        "numero": numero,
        "amarelo": amarelo,
        "vermelho": vermelho
    }
def parse_staff_rows(rows):

    equipe = {
        "tecnico": None,
        "auxiliar_tecnico": None,
        "preparador_fisico": None,
        "massagista": None,
        "medico_fisioterapeuta_enfermeiro": None
    }

    for row in rows:

        texto_linha = row_text(row)
        texto_norm = normalize_key(texto_linha)

        funcao = None

        # =====================================================
        # IDENTIFICA A FUNCAO
        # =====================================================

        if "aux" in texto_norm and "tecnico" in texto_norm:
            funcao = "auxiliar_tecnico"

        elif "prep" in texto_norm and "fisico" in texto_norm:
            funcao = "preparador_fisico"

        elif "massagista" in texto_norm:
            funcao = "massagista"

        elif (
            "med/fis/enf" in texto_norm
            or "med fis enf" in texto_norm
            or (
                "med" in texto_norm
                and "fis" in texto_norm
                and "enf" in texto_norm
            )
        ):
            funcao = "medico_fisioterapeuta_enfermeiro"

        elif "tecnico" in texto_norm:
            funcao = "tecnico"

        if not funcao:
            continue

        # =====================================================
        # REGISTRO
        # =====================================================

        registro = None

        for item in row["items"]:

            # registro fica na primeira coluna da tabela
            if item["x1"] <= 45 and is_numeric(item["text"]):
                registro = item["text"]
                break

        # =====================================================
        # NOME
        # =====================================================

        nomes = []

        for item in row["items"]:

            texto = normalize_text(item["text"])
            texto_item_norm = normalize_key(texto)

            # Nome da pessoa fica depois da coluna do cargo
            if item["x1"] < 80:
                continue

            # evita pegar novamente labels/cargos
            if any(chave in texto_item_norm for chave in [
                "tecnico:",
                "tecnico",
                "aux. tecnico",
                "aux tecnico",
                "prep. fisico",
                "prep fisico",
                "massagista",
                "med/fis/enf",
                "med fis enf"
            ]):
                continue

            # evita numeros soltos
            if is_numeric(texto):
                continue

            nomes.append(texto)

        nome = " ".join(nomes).strip()

        if not nome:
            nome = None

        # =====================================================
        # SALVA
        # =====================================================

        equipe[funcao] = {
            "registro": registro,
            "nome": nome
        }

    return equipe


def parse_goals_in_box(items, x_min, x_max, y_min, y_max):
    """
    Le os gols dentro da area informada.

    Gol normal:
        jogador_numero recebe a camisa.

    Gol contra:
        jogador_numero recebe "X".
    """

    area_items = get_box_items(
        items,
        x_min,
        x_max,
        y_min,
        y_max
    )

    tempos = [
        item
        for item in area_items
        if is_time(item["text"])
    ]

    gols = []

    for tempo in sorted(tempos, key=lambda i: i["x1"]):
        valores_acima = []

        for item in area_items:
            diferenca_y = item["y1"] - tempo["y1"]

            if not (7 <= diferenca_y <= 14):
                continue

            if not (
                item["x1"] >= tempo["x1"] - 2
                and item["x1"] <= tempo["x2"] + 2
            ):
                continue

            texto = normalize_text(item["text"])
            tokens = re.findall(r"\d+|[Xx]", texto)

            for token in tokens:
                valores_acima.append({
                    "valor": token.upper(),
                    "x": item["x1"]
                })

        valores_acima = sorted(
            valores_acima,
            key=lambda i: i["x"]
        )

        ordem = None
        jogador_numero = None

        if len(valores_acima) >= 1:
            if re.fullmatch(r"\d+", valores_acima[0]["valor"]):
                ordem = valores_acima[0]["valor"]

        if len(valores_acima) >= 2:
            jogador_numero = valores_acima[1]["valor"]

        if jogador_numero and jogador_numero != "X":
            jogador_numero = jogador_numero.zfill(2)

        gols.append({
            "ordem": ordem.zfill(2) if ordem else None,
            "jogador_numero": jogador_numero,
            "tempo": tempo["text"]
        })

    return gols
def parse_capitao(items, x_min, x_max, y_min, y_max):
    """
    Procura algo do tipo:
    RAFAEL HOPPE GARCIA (7)
    """
    area_items = get_box_items(items, x_min, x_max, y_min, y_max)

    candidatos = []
    for item in area_items:
        txt = normalize_text(item["text"])
        norm = normalize_key(txt)

        if "capitao" in norm:
            continue

        if re.search(r"\(\d{1,2}\)", txt):
            candidatos.append(txt)

    if not candidatos:
        return None

    # escolhe o mais comprido, normalmente o nome completo
    candidatos = sorted(candidatos, key=len, reverse=True)
    return candidatos[0]
def parse_team_block(items, team_name, title_item):
    """
    Usa o titulo do bloco para calcular as areas relativas:
    - jogadores
    - comissao tecnica
    - gols
    - capitao

    Tambem identifica as coordenadas das colunas Amar/Verm para
    diferenciar corretamente cartao amarelo e vermelho.
    """

    if not title_item:
        return {
            "nome": team_name,
            "jogadores": [],
            "comissao_tecnica": {
                "tecnico": None,
                "auxiliar_tecnico": None,
                "preparador_fisico": None,
                "massagista": None,
                "medico_fisioterapeuta_enfermeiro": None
            },
            "gols": [],
            "capitao": None
        }

    title_y = title_item["y1"]

    # =====================================================
    # POSICAO DAS COLUNAS AMAR / VERM
    # =====================================================

    amarelo_x = None
    vermelho_x = None

    cabecalho_items = get_box_items(
        items,
        180, 290,
        title_y - 35,
        title_y
    )

    for item in cabecalho_items:

        texto_norm = normalize_key(
            item["text"]
        )

        if "amar" in texto_norm:
            amarelo_x = item["x1"]

        if "verm" in texto_norm:
            vermelho_x = item["x1"]

    # =====================================================
    # JOGADORES
    # =====================================================

    player_items = get_box_items(
        items,
        15, 290,
        title_y - 165,
        title_y - 10
    )

    player_rows = cluster_rows(
        player_items,
        y_tolerance=4.5
    )

    jogadores = []

    for row in player_rows:

        jogador = parse_player_row(
            row,
            amarelo_x=amarelo_x,
            vermelho_x=vermelho_x
        )

        if jogador:
            jogadores.append(
                jogador
            )

    # =====================================================
    # COMISSAO TECNICA
    # =====================================================

    staff_items = get_box_items(
        items,
        15, 290,
        title_y - 240,
        title_y - 140
    )

    staff_rows = cluster_rows(
        staff_items,
        y_tolerance=3.0
    )

    comissao_tecnica = parse_staff_rows(
        staff_rows
    )

    # =====================================================
    # GOLS
    # =====================================================

    gols = parse_goals_in_box(
        items,
        15, 820,
        title_y - 360,
        title_y - 170
    )

    # =====================================================
    # CAPITAO
    # =====================================================

    capitao = parse_capitao(
        items,
        480, 580,
        title_y - 320,
        title_y - 110
    )

    return {
        "nome": team_name,
        "jogadores": jogadores,
        "comissao_tecnica": comissao_tecnica,
        "gols": gols,
        "capitao": capitao
    }
    
    
def criar_converter_docling():
    pipeline_options = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=False
    )

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options
            )
        }
    )

# =========================================================
# PROCESSAR UMA SUMULA
# =========================================================

def processar_sumula(pdf_file, nome_arquivo=None):
    """
    Processa uma unica sumula PDF e retorna os dados em dict.

    Nao grava PDF, JSON ou arquivos de debug em disco.
    O arquivo PDF recebido deve existir apenas durante o processamento.
    """

    from pathlib import Path as LocalPath

    pdf_file = LocalPath(pdf_file)

    if not pdf_file.exists():
        raise FileNotFoundError(
            f"Arquivo PDF nao encontrado: {pdf_file}"
        )

    # =====================================================
    # CONVERTE PDF
    # =====================================================

    converter = None
    result = None

    try:
        converter = criar_converter_docling()
        result = converter.convert(str(pdf_file))
        items = extract_items_from_doc(result)
    finally:
        del result
        del converter
        gc.collect()

    # =====================================================
    # CABECALHO
    # =====================================================

    codigo_jogo = get_first_text(items, 15, 55, 785, 795)
    data_jogo = get_first_text(items, 520, 575, 785, 795)

    gols_mandante = get_first_text(
        items,
        270, 300,
        785, 795,
        regex=r"\d+"
    )

    visitante_bruto = get_first_text(
        items,
        305, 430,
        785, 795
    )

    gols_visitante = None

    if visitante_bruto:
        match_visitante = re.match(
            r"^(\d+)\s+(.+)$",
            visitante_bruto
        )

        if match_visitante:
            gols_visitante = match_visitante.group(1)

    competicao = get_first_text(items, 55, 160, 770, 780)
    categoria = get_first_text(items, 55, 120, 760, 770)
    ginasio = get_first_text(items, 55, 280, 745, 760)
    cidade = get_first_text(items, 340, 420, 745, 760)

    # =====================================================
    # ARBITRAGEM
    # =====================================================

    arbitragem_area = get_box_items(items, 15, 320, 700, 740)
    arbitragem_rows = cluster_rows(
        arbitragem_area,
        y_tolerance=3.0
    )

    arbitragem = []

    for row in arbitragem_rows:
        registro = None
        funcao = None
        nome = None

        for item in row["items"]:
            if registro is None and is_numeric(item["text"]):
                registro = item["text"]

        labels = [
            i["text"]
            for i in row["items"]
            if 45 <= i["x1"] <= 150
        ]

        names = [
            i["text"]
            for i in row["items"]
            if i["x1"] >= 150
        ]

        if labels:
            funcao = " ".join(labels).strip(" :")

        if names:
            nome = " ".join(names).strip()

        if registro and nome:
            arbitragem.append({
                "registro": registro,
                "funcao": funcao,
                "nome": nome
            })

    # =====================================================
    # PERIODOS
    # =====================================================

    periodos = []
    periodo_area = get_box_items(items, 500, 575, 730, 770)

    pares_tempo = [
        item
        for item in periodo_area
        if is_time_pair(item["text"])
    ]

    pares_tempo = sorted(
        pares_tempo,
        key=lambda i: -i["y1"]
    )

    for idx_periodo, item in enumerate(
        pares_tempo[:4],
        start=1
    ):
        partes = item["text"].split()

        if len(partes) < 2:
            continue

        periodos.append({
            "periodo": f"{idx_periodo}º",
            "inicio": partes[0],
            "termino": partes[1]
        })

    # =====================================================
    # TIMES
    # =====================================================

    blocos_times = find_team_blocks(items)
    bloco_mandante = blocos_times["mandante"]
    bloco_visitante = blocos_times["visitante"]

    if bloco_mandante:
        mandante = parse_team_block(
            items,
            bloco_mandante["nome"],
            bloco_mandante["titulo"]
        )
    else:
        mandante = {
            "nome": None,
            "jogadores": [],
            "comissao_tecnica": {
                "tecnico": None,
                "auxiliar_tecnico": None,
                "preparador_fisico": None,
                "massagista": None,
                "medico_fisioterapeuta_enfermeiro": None
            },
            "gols": [],
            "capitao": None
        }

    if bloco_visitante:
        visitante = parse_team_block(
            items,
            bloco_visitante["nome"],
            bloco_visitante["titulo"]
        )
    else:
        visitante = {
            "nome": None,
            "jogadores": [],
            "comissao_tecnica": {
                "tecnico": None,
                "auxiliar_tecnico": None,
                "preparador_fisico": None,
                "massagista": None,
                "medico_fisioterapeuta_enfermeiro": None
            },
            "gols": [],
            "capitao": None
        }

    # =====================================================
    # RETORNO FINAL
    # =====================================================

    dados = {
        "arquivo": nome_arquivo or pdf_file.name,
        "jogo": {
            "codigo": codigo_jogo,
            "data": data_jogo,
            "competicao": competicao,
            "categoria": categoria,
            "ginasio": ginasio,
            "cidade": cidade,
            "placar": {
                "mandante": (
                    try_int(gols_mandante)
                    if gols_mandante
                    else None
                ),
                "visitante": (
                    try_int(gols_visitante)
                    if gols_visitante
                    else None
                )
            },
            "periodos": periodos,
            "arbitragem": arbitragem
        },
        "mandante": mandante,
        "visitante": visitante
    }

    return dados
