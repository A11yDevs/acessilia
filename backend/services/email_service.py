import aiosmtplib
from email.message import EmailMessage
from pathlib import Path
from backend.tools.logger import logger
from backend.config.settings import settings


FORMAT_LABELS = {
    "txt": "Texto (TXT)",
    "docx": "Documento Word (DOCX)",
    "pdf": "PDF",
    "pdf_ua": "PDF/UA",
    "html": "Página Web (HTML)",
    "mp3": "Audiodescrição em Áudio (MP3)",
    "zip": "Pacote ZIP",
}


async def send_email_notification(
    to_email: str, subject: str, body: str, attachment_path: Path | None = None
) -> bool:
    if not settings.smtp_user or not settings.smtp_password:
        logger.warning("SMTP não configurado. E-mail para {} não enviado.", to_email)
        return False

    message = EmailMessage()
    message["From"] = f"{settings.smtp_name} <{settings.smtp_from}>"
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    if attachment_path and attachment_path.exists():
        with open(attachment_path, "rb") as f:
            file_data = f.read()
            message.add_attachment(
                file_data,
                maintype="application",
                subtype="zip",
                filename=attachment_path.name,
            )

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_server,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            use_tls=settings.smtp_port == 465,
            start_tls=settings.smtp_port == 587,
        )
        logger.info("E-mail enviado para {} com sucesso.", to_email)
        return True
    except Exception as e:
        logger.error("Erro ao enviar e-mail para {}: {}", to_email, e)
        return False


async def send_confirmation_email(to_email: str, filename: str) -> bool:
    subject = "Recebemos seu arquivo - Acessilia"
    body = (
        f"Olá!\n\nRecebemos o arquivo '{filename}' e já estamos trabalhando para torná-lo acessível.\n"
        "Este processo envolve análise por inteligência artificial e geração de audiodescrição em áudio.\n\n"
        "Assim que estiver pronto, você receberá um novo e-mail com o pacote acessível em anexo.\n\n"
        "Atenciosamente,\nEquipe Acessilia"
    )
    return await send_email_notification(to_email, subject, body)


async def send_result_email(
    to_email: str,
    filename: str,
    zip_path: Path | None = None,
    download_url: str | None = None,
    completed_formats: list[str] | None = None,
    warnings: list[str] | None = None,
) -> bool:
    subject = "Seu arquivo acessível está pronto! - Acessilia"
    labels = [
        FORMAT_LABELS[format_name]
        for format_name in (completed_formats or ["txt", "docx", "pdf", "pdf_ua", "html", "mp3"])
        if format_name in FORMAT_LABELS
    ]
    formats_text = ", ".join(labels)
    warnings_text = ""
    if warnings:
        warnings_text = "\n\nAlguns formatos opcionais não foram gerados:\n"
        warnings_text += "\n".join(f"- {warning}" for warning in warnings)

    if download_url:
        body = (
            f"Olá!\n\nO processamento do arquivo '{filename}' foi concluído com sucesso.\n\n"
            f"Acesse o link abaixo para visualizar e baixar os formatos disponíveis:\n\n"
            f"{download_url}\n\n"
            f"Formatos disponíveis: {formats_text}."
            f"{warnings_text}\n\n"
            f"O link expira em 7 dias.\n\n"
            f"Atenciosamente,\nEquipe Acessilia"
        )
        return await send_email_notification(to_email, subject, body)
    else:
        body = (
            f"Olá!\n\nO processamento do arquivo '{filename}' foi concluído com sucesso.\n"
            "Em anexo, você encontrará um pacote ZIP contendo os seguintes formatos:\n"
            + "\n".join(f"- {label}" for label in labels)
            + f"{warnings_text}\n\n"
            "Atenciosamente,\nEquipe Acessilia"
        )
        return await send_email_notification(to_email, subject, body, attachment_path=zip_path)
