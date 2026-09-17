import logging
import random
import time
from dataclasses import dataclass

from django.utils import timezone

from mailings.models import Mailing

logger = logging.getLogger(__name__)


@dataclass
class SendStats:
    sent: int = 0
    failed: int = 0


def send_email(mailing: Mailing) -> None:
    """Simulated transport required by the task: a random delay, then a log line."""
    time.sleep(random.randint(5, 20))  # noqa: S311
    logger.info("Send EMAIL mailing_id=%s", mailing.pk)


def send_mailings() -> SendStats:
    stats = SendStats()
    queryset = Mailing.objects.filter(status=Mailing.Status.PENDING).order_by("id")
    for mailing in queryset.iterator():
        try:
            send_email(mailing)
        except Exception as exc:
            mailing.status = Mailing.Status.FAILED
            mailing.last_error = str(exc)[:255]
            mailing.save(update_fields=["status", "last_error"])
            stats.failed += 1
            logger.warning("Ошибка отправки mailing_id=%s: %s", mailing.pk, exc)
        else:
            mailing.status = Mailing.Status.SENT
            mailing.sent_at = timezone.now()
            mailing.save(update_fields=["status", "sent_at"])
            stats.sent += 1
    return stats
