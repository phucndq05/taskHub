import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AssignmentEmailPayload:
    """Primitive data needed to notify a user about a task assignment."""

    recipient_email: str
    recipient_name: str
    task_id: str
    task_title: str
    project_name: str
    assigner_name: str


class EmailSender(Protocol):
    """Synchronous task-assignment email sender."""

    def send_assignment_email(self, payload: AssignmentEmailPayload) -> None:
        """Deliver one task-assignment email."""


class DisabledEmailSender:
    """No-op sender used when SMTP is not configured."""

    def send_assignment_email(self, payload: AssignmentEmailPayload) -> None:
        return None


class SmtpEmailSender:
    """Deliver task-assignment email with a fresh SMTP connection."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        from_email: str,
        use_starttls: bool,
        timeout_seconds: float,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_email = from_email
        self._use_starttls = use_starttls
        self._timeout_seconds = timeout_seconds

    def send_assignment_email(self, payload: AssignmentEmailPayload) -> None:
        message = build_assignment_email_message(payload, from_email=self._from_email)
        with smtplib.SMTP(
            self._host,
            self._port,
            timeout=self._timeout_seconds,
        ) as smtp:
            if self._use_starttls:
                smtp.starttls()
            if self._username is not None and self._password is not None:
                smtp.login(self._username, self._password)
            smtp.send_message(message)


def build_assignment_email_message(
    payload: AssignmentEmailPayload,
    *,
    from_email: str,
) -> EmailMessage:
    """Build the plain-text task-assignment email."""
    message = EmailMessage()
    message["From"] = formataddr(("TaskHub", from_email))
    message["To"] = payload.recipient_email
    message["Subject"] = f"Task assigned: {payload.task_title}"
    message.set_content(
        f"Hello {payload.recipient_name},\n\n"
        f'{payload.assigner_name} assigned you the task "{payload.task_title}" '
        f'in project "{payload.project_name}".\n\n'
        f"Task ID: {payload.task_id}\n"
    )
    return message


def send_assignment_email_safely(
    sender: EmailSender,
    payload: AssignmentEmailPayload,
) -> None:
    """Deliver assignment email without affecting the committed task mutation."""
    try:
        sender.send_assignment_email(payload)
    except Exception as exc:
        logger.warning(
            "Task assignment email delivery failed (%s).",
            type(exc).__name__,
        )
