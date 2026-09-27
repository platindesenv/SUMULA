# -*- coding: utf-8 -*-

import os
import tempfile

from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException

from sumula_salao import processar_sumula


# =========================================================
# CONFIGURACOES
# =========================================================

app = FastAPI(
    title="API Sumulas",
    version="1.0.0"
)


# =========================================================
# HOME
# =========================================================

@app.get("/")
def home():
    return {
        "sucesso": True,
        "servico": "API Sumulas"
    }


# =========================================================
# PROCESSAR SUMULA DE SALAO
# =========================================================

@app.post("/sumula/salao")
async def processar_sumula_salao(
    arquivo: UploadFile = File(...)
):
    caminho_temp = None

    try:
        # =================================================
        # VALIDA ARQUIVO
        # =================================================

        if not arquivo.filename:
            raise HTTPException(
                status_code=400,
                detail="Arquivo nao informado."
            )

        nome_pdf = Path(arquivo.filename).name

        if not nome_pdf.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail="O arquivo precisa ser um PDF."
            )

        if nome_pdf.lower().startswith("sumula_paulista_"):
            raise HTTPException(
                status_code=400,
                detail="Esta sumula e do modelo campo."
            )

        # =================================================
        # LE O PDF RECEBIDO
        # =================================================

        conteudo = await arquivo.read()

        if not conteudo:
            raise HTTPException(
                status_code=400,
                detail="O arquivo esta vazio."
            )

        if not conteudo.startswith(b"%PDF"):
            raise HTTPException(
                status_code=400,
                detail=(
                    "O arquivo recebido nao parece "
                    "ser um PDF valido."
                )
            )

        # =================================================
        # CRIA PDF TEMPORARIO
        # =================================================

        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".pdf",
            delete=False
        ) as arquivo_temp:
            arquivo_temp.write(conteudo)
            caminho_temp = arquivo_temp.name

        # =================================================
        # PROCESSA DIRETAMENTE
        # =================================================

        resultado = processar_sumula(
            caminho_temp,
            nome_arquivo=nome_pdf
        )

        # =================================================
        # RETORNA JSON
        # =================================================

        return {
            "sucesso": True,
            "arquivo": nome_pdf,
            "dados": resultado
        }

    except HTTPException:
        raise

    except Exception as erro:
        raise HTTPException(
            status_code=500,
            detail={
                "erro": "Erro ao processar a sumula.",
                "tipo": type(erro).__name__,
                "mensagem": str(erro)
            }
        )

    finally:
        try:
            await arquivo.close()
        except Exception:
            pass

        if caminho_temp:
            try:
                os.remove(caminho_temp)
            except FileNotFoundError:
                pass
            except Exception:
                pass
