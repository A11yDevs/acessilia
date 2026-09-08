import aiosmtplib
from email.message import EmailMessage
from pathlib import Path
from backend.i18n import t
from backend.log_messages import (
    EMAIL_CONFIRMATION_BODY,
    EMAIL_CONFIRMATION_SUBJECT,
    EMAIL_RESULT_BODY_ATTACHED,
    EMAIL_RESULT_BODY_WITH_LINK,
    EMAIL_RESULT_SUBJECT,
    LOG_EMAIL_SEND_ERROR,
    LOG_EMAIL_SENT,
    LOG_SMTP_NOT_CONFIGURED,
)
from backend.tools.logger import logger
from backend.config.settings import settings


async def send_email_notification(
    to_email: str, subject: str, body: str, attachment_path: Path | None = None
):
    if not settings.smtp_user or not settings.smtp_password:
        logger.warning(t(LOG_SMTP_NOT_CONFIGURED).format(to_email=to_email))
        return

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
        logger.info(t(LOG_EMAIL_SENT).format(to_email=to_email))
    except Exception as e:
        logger.error(t(LOG_EMAIL_SEND_ERROR).format(to_email=to_email, error=e))


async def send_confirmation_email(to_email: str, filename: str):
    subject = t(EMAIL_CONFIRMATION_SUBJECT)
    body = t(EMAIL_CONFIRMATION_BODY).format(filename=filename)
    await send_email_notification(to_email, subject, body)


async def send_result_email(
    to_email: str,
    filename: str,
    zip_path: Path | None = None,
    download_url: str | None = None,
):
    subject = t(EMAIL_RESULT_SUBJECT)

    if download_url:
        body = t(EMAIL_RESULT_BODY_WITH_LINK).format(
            filename=filename, download_url=download_url
        )
        await send_email_notification(to_email, subject, body)
    else:
        body = t(EMAIL_RESULT_BODY_ATTACHED).format(filename=filename)
        await send_email_notification(to_email, subject, body, attachment_path=zip_path)
