import asyncio
import json
import threading
import uuid
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select

from backend.config.settings import settings
from backend.services import database
from backend.tools.logger import logger

# Database connection configuration
_connection_lock = threading.Lock()

TOKEN_EXPIRY_DAYS = 7

FORMAT_EXTENSIONS = {
    "txt": "texto",
    "docx": "word",
    "pdf": "pdf",
    "pdf_ua": "pdf/ua",
    "html": "html",
    "mp3": "audio",
    "zip": "completo",
}

FORMAT_OUTPUT_SUFFIX = {
    "pdf_ua": "pdf_ua.pdf",
}


async def criar_token(output_dir: Path, filename: str, formats: list = None) -> str:
    token = str(uuid.uuid4())
    formats_json = json.dumps(formats) if formats else '[]'
    with _connection_lock:
        engine = database.get_engine()
        with engine.begin() as conn:
            conn.execute(
                database.download_tokens.insert().values(
                    token=token,
                    output_dir=str(output_dir),
                    filename=filename,
                    formats=formats_json,
                )
            )
    logger.debug("Token de download criado: {} -> {}", token, filename)
    return token


async def obter_info_token(token: str) -> dict | None:
    with _connection_lock:
        engine = database.get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                select(
                    database.download_tokens.c.output_dir,
                    database.download_tokens.c.filename,
                    database.download_tokens.c.formats,
                    database.download_tokens.c.criado_em,
                ).where(database.download_tokens.c.token == token)
            ).first()
    if row is None:
        return None
    row = row._mapping
    output_dir = Path(row["output_dir"])
    if not output_dir.exists():
        return None
    formats_list = json.loads(row["formats"]) if row["formats"] else []
    formats = []
    for ext, label in FORMAT_EXTENSIONS.items():
        suffix = FORMAT_OUTPUT_SUFFIX.get(ext, ext)
        file_path = output_dir / f"{Path(row['filename']).stem}.{suffix}"
        if file_path.exists():
            size_kb = file_path.stat().st_size / 1024
            size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
            formats.append({
                "ext": ext,
                "label": label,
                "file_path": str(file_path),
                "size": size_str,
                "url": f"/download/{token}/{ext}",
            })
    return {
        "filename": row["filename"],
        "stem": Path(row["filename"]).stem,
        "output_dir": str(output_dir),
        "criado_em": _serializar_criado_em(row["criado_em"]),
        "formats": formats,
    }


def _serializar_criado_em(valor) -> str | None:
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d %H:%M:%S")
    return valor


async def limpar_tokens_expirados(dias: int = TOKEN_EXPIRY_DAYS):
    cutoff = datetime.utcnow() - timedelta(days=dias)
    with _connection_lock:
        engine = database.get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                select(database.download_tokens.c.output_dir).where(
                    database.download_tokens.c.criado_em < cutoff
                )
            )
            output_dirs = [row._mapping["output_dir"] for row in rows]
        for output_dir in output_dirs:
            path = Path(output_dir)
            if path.exists():
                if str(path).startswith(str(settings.temp_dir)):
                    shutil.rmtree(path, ignore_errors=True)
                    logger.debug("Diretório temporário removido: {}", path)
        with engine.begin() as conn:
            conn.execute(
                delete(database.download_tokens).where(
                    database.download_tokens.c.criado_em < cutoff
                )
            )
