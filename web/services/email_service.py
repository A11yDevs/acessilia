import aiosmtplib
from email.message import EmailMessage
from pathlib import Path
from bot.utils.logger import logger
from config.settings import settings

async def send_email_notification(to_email: str, subject: str, body: str, attachment_path: Path | None = None):
    """Envia um e-mail de forma assíncrona."""
    if not settings.smtp_user or not settings.smtp_password:
        logger.warning("SMTP não configurado. E-mail para {} não enviado.", to_email)
        return

    message = EmailMessage()
    # Define o nome amigável e o e-mail no formato: "Nome <email@dominio.com>"
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
                filename=attachment_path.name
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
    except Exception as e:
        logger.error("Erro ao enviar e-mail para {}: {}", to_email, e)

async def send_confirmation_email(to_email: str, filename: str):
    subject = "Recebemos seu arquivo - Bot Acess"
    body = (
        f"Olá!\n\nRecebemos o arquivo '{filename}' e já estamos trabalhando para torná-lo acessível.\n"
        "Este processo envolve análise por inteligência artificial e geração de audiodescrição em áudio.\n\n"
        "Assim que estiver pronto, você receberá um novo e-mail com o pacote acessível em anexo.\n\n"
        "Atenciosamente,\nEquipe Bot Acess"
    )
    await send_email_notification(to_email, subject, body)

async def send_result_email(to_email: str, filename: str, zip_path: Path):
    subject = "Seu arquivo acessível está pronto! - Bot Acess"
    body = (
        f"Olá!\n\nO processamento do arquivo '{filename}' foi concluído com sucesso.\n"
        "Em anexo, você encontrará um pacote ZIP contendo os seguintes formatos:\n"
        "- Texto Puro (.txt)\n"
        "- Documento Word (.docx)\n"
        "- PDF Acessível (.pdf)\n"
        "- Página Web (.html)\n"
        "- Audiodescrição em Áudio (.mp3)\n\n"
        "Atenciosamente,\nEquipe Bot Acess"
    )
    await send_email_notification(to_email, subject, body, attachment_path=zip_path)
