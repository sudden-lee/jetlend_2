import logging
import random
import time
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from django.db import DatabaseError
from django.db.models import F, Max, Q
from django.utils import timezone

from mailings.models import Mailing

logger = logging.getLogger(__name__)
LEASE = timedelta(minutes=5)


@dataclass
class SendStats:
    sent: int = 0
    failed: int = 0
    lost: int = 0


class SendDatabaseError(RuntimeError):
    def __init__(self, stats: SendStats, unconfirmed: int = 0) -> None:
        super().__init__("Сбой базы данных при обработке очереди.")
        self.stats = stats
        self.unconfirmed = unconfirmed


class _StrictStreamHandler(logging.StreamHandler):
    def handleError(self, record: logging.LogRecord) -> None:
        raise


class _QuietStreamHandler(logging.StreamHandler):
    def handleError(self, record: logging.LogRecord) -> None:
        pass


def _emit_log(
    level: int,
    message: str,
    args: tuple[object, ...],
    stream_handler: type[logging.StreamHandler],
) -> None:
    current: logging.Logger | None = logger
    while current is not None and not current.handlers:
        current = current.parent if current.propagate else None
    configured = current.handlers[0] if current is not None else logging.StreamHandler()
    record = logger.makeRecord(
        logger.name,
        level,
        __file__,
        0,
        message,
        args,
        None,
    )
    if not isinstance(configured, logging.StreamHandler):
        configured.handle(record)
        return
    handler = stream_handler(configured.stream)
    handler.setFormatter(configured.formatter)
    handler.handle(record)


def _log_transport(mailing_id: int) -> None:
    _emit_log(
        logging.INFO,
        "Send EMAIL mailing_id=%s",
        (mailing_id,),
        _StrictStreamHandler,
    )


def _log_diagnostic(level: int, message: str, *args: object) -> None:
    try:
        _emit_log(level, message, args, _QuietStreamHandler)
    except Exception:
        # Diagnostics must not replace the persisted queue result with a logging failure.
        return


def claim_next(max_id: int, after_id: int = 0, retry_failed: bool = False) -> Mailing | None:
    """Claim a job with a PostgreSQL-safe conditional UPDATE."""
    while True:
        now = timezone.now()
        eligible = Q(status=Mailing.Status.PENDING) | Q(
            status=Mailing.Status.PROCESSING, claimed_at__lte=now - LEASE
        )
        if retry_failed:
            eligible |= Q(status=Mailing.Status.FAILED)
        candidate = (
            Mailing.objects.filter(eligible, pk__gt=after_id, pk__lte=max_id).order_by("pk").first()
        )
        if candidate is None:
            return None
        token = uuid4()
        changed = Mailing.objects.filter(eligible, pk=candidate.pk).update(
            status=Mailing.Status.PROCESSING,
            claimed_at=now,
            claim_token=token,
            attempts=F("attempts") + 1,
            last_error="",
        )
        if changed:
            claimed = Mailing.objects.filter(
                pk=candidate.pk, status=Mailing.Status.PROCESSING, claim_token=token
            ).first()
            if claimed is not None:
                return claimed
            after_id = candidate.pk


def send_email(mailing: Mailing) -> None:
    """The task's simulated email transport; never log recipient or message contents."""
    # The task requires a non-cryptographic random delay.
    time.sleep(random.randint(5, 20))  # noqa: S311  # nosec B311
    _log_transport(mailing.pk)


def send_mailings(limit: int | None = None, retry_failed: bool = False) -> SendStats:
    """Visit eligible IDs up to the initial cutoff once, without locks during delivery."""
    if limit is not None and limit < 1:
        raise ValueError("Лимит должен быть положительным.")
    stats = SendStats()
    try:
        max_id = Mailing.objects.aggregate(value=Max("pk"))["value"]
    except DatabaseError as exc:
        raise SendDatabaseError(stats) from exc
    if max_id is None:
        return stats
    processed = 0
    after_id = 0
    while limit is None or processed < limit:
        try:
            mailing = claim_next(max_id, after_id=after_id, retry_failed=retry_failed)
        except DatabaseError as exc:
            raise SendDatabaseError(stats) from exc
        if mailing is None:
            break
        # Failed retries and lost claims are reconsidered by a later command, not this run.
        after_id = mailing.pk
        owned = Mailing.objects.filter(
            pk=mailing.pk, status=Mailing.Status.PROCESSING, claim_token=mailing.claim_token
        )
        try:
            send_email(mailing)
        except Exception as exc:
            # Isolate transport failures; do not expose arbitrary exception payloads.
            error_type = type(exc).__name__
            values = {
                "status": Mailing.Status.FAILED,
                # Bandit mistakes a queue-ownership token reset for a password literal.
                "claim_token": None,  # nosec B105
                "claimed_at": None,
                "last_error": error_type[:128],
            }
        else:
            error_type = None
            values = {
                "status": Mailing.Status.SENT,
                "sent_at": timezone.now(),
                # Bandit mistakes a queue-ownership token reset for a password literal.
                "claim_token": None,  # nosec B105
                "claimed_at": None,
            }
        try:
            changed = owned.update(**values)
        except DatabaseError as exc:
            raise SendDatabaseError(stats, unconfirmed=1) from exc
        if error_type is not None:
            _log_diagnostic(
                logging.ERROR, "Ошибка отправки mailing_id=%s type=%s", mailing.pk, error_type
            )
            stats.failed += bool(changed)
        else:
            stats.sent += bool(changed)
        if not changed:
            stats.lost += 1
            _log_diagnostic(
                logging.WARNING, "Потерян захват mailing_id=%s; статус не изменён.", mailing.pk
            )
        processed += 1
    return stats
