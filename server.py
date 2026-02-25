"""Docling GPU extraction server for RunPod."""

import logging
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_converter: DocumentConverter | None = None


def _get_converter() -> DocumentConverter:
    global _converter
    if _converter is None:
        pipeline_options = PdfPipelineOptions()
        pipeline_options.generate_picture_images = True
        pipeline_options.images_scale = 2.0
        pipeline_options.do_table_structure = True
        pipeline_options.do_ocr = False

        _converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
                )
            }
        )
        logger.info("DocumentConverter inicializado com CUDA")
    return _converter


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Pre-carregando DocumentConverter...")
    _get_converter()
    logger.info("Converter pronto.")
    yield


app = FastAPI(title="Docling GPU Server", lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "converter_loaded": _converter is not None,
    }


@app.post("/extract")
async def extract_pdf(file: UploadFile = File(...)):
    """Recebe PDF, executa Docling, retorna DoclingDocument JSON."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Arquivo deve ser PDF")

    start = time.monotonic()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        converter = _get_converter()
        result = converter.convert(str(tmp_path))
        document = result.document

        elapsed = time.monotonic() - start
        page_count = len(list(document.pages))

        doc_dict = document.export_to_dict()

        logger.info(
            f"[{file.filename}] Extraido em {elapsed:.1f}s | "
            f"{page_count} paginas"
        )

        return JSONResponse(content={
            "document": doc_dict,
            "filename": file.filename,
            "pages": page_count,
            "elapsed_seconds": round(elapsed, 2),
        })
    except Exception as e:
        logger.error(f"Erro ao extrair {file.filename}: {e}")
        raise HTTPException(500, f"Erro na extracao: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
