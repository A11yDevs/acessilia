from pathlib import Path

from config.settings import settings


def is_extension_allowed(filename: str) -> bool:
    ext = Path(filename).suffix.lower()
    return ext in settings.allowed_extensions


def is_file_size_allowed(file_size: int) -> bool:
    return file_size <= settings.max_file_size_bytes


def validate_file(filename: str, file_size: int) -> tuple[bool, str]:
    if not is_extension_allowed(filename):
        return (
            False,
            "Formato de arquivo não suportado. Envie PDF, DOCX, HTML, PNG, JPG, TIFF, BMP ou WEBP.",
        )
    if not is_file_size_allowed(file_size):
        return False, f"Arquivo muito grande. Limite: {settings.max_file_size_mb} MB."
    return True, ""
