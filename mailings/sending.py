import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from django.conf import settings
from django.db import DatabaseError, transaction
from django.db.models import F, Max, Q
from django.utils import timezone

from mailings.models import Mailing

logger = logging.getLogger(__name__)
LEASE = timedelta(seconds=settings.MAILINGS_LEASE_SECONDS)
MAX_ATTEMPTS = settings.MAILINGS_MAX_ATTEMPTS
RETRY_BASE_SECONDS = settings.MAILINGS_RETRY_BASE_SECONDS
RETRY_MAX_SECONDS = settings.MAILINGS_RETRY_MAX_SECONDS


@dataclass
class SendStats:
    sent: int = 0
    failed: int = 0
    lost: int = 0
    retried: int = 0


class SendDatabaseError(RuntimeError):
    def __init__(self, stats: SendStats, unconfirmed: int = 0) -> None:
        super().__init__("Сбой базы данных при обработке очереди.")
        self.stats = stats
        self.unconfirmed = unconfirmed


class PermanentTransportError(RuntimeError):
    """A provider rejected a message and repeating it cannot succeed."""


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


def _log_transport(mailing_id: int, idempotency_key: str) -> None:
    _emit_log(
        logging.INFO,
        "Send EMAIL mailing_id=%s idempotency_key=%s",
        (mailing_id, idempotency_key),
        _StrictStreamHandler,
    )


def _log_diagnostic(level: int, message: str, *args: object) -> None:
    try:
        _emit_log(level, message, args, _QuietStreamHandler)
    except Exception:
        # Diagnostics must not replace the persisted queue result with a logging failure.
        return


def _eligible(now: datetime, retry_failed: bool) -> Q:
    automatic = Q(attempts__lt=MAX_ATTEMPTS) & (
        Q(status=Mailing.Status.PENDING)
        | Q(status=Mailing.Status.RETRYING, next_attempt_at__lte=now)
        | Q(status=Mailing.Status.PROCESSING, claimed_at__lte=now - LEASE)
    )
    return automatic | Q(status=Mailing.Status.FAILED) if retry_failed else automatic


def claim_next(max_id: int, after_id: int = 0, retry_failed: bool = False) -> Mailing | None:
    """Claim one job under a short row lock; delivery runs after commit."""
    with transaction.atomic():
        now = timezone.now()
        candidate = (
            Mailing.objects.select_for_update(skip_locked=True)
            .filter(_eligible(now, retry_failed), pk__gt=after_id, pk__lte=max_id)
            .order_by("pk")
            .first()
        )
        if candidate is None:
            return None
        candidate.status = Mailing.Status.PROCESSING
        candidate.claimed_at = now
        candidate.claim_token = uuid4()
        candidate.next_attempt_at = None
        candidate.attempts = F("attempts") + 1
        candidate.last_error = ""
        candidate.save(
            update_fields=(
                "status",
                "claimed_at",
                "claim_token",
                "next_attempt_at",
                "attempts",
                "last_error",
            )
        )
        candidate.refresh_from_db()
        return candidate


def delivery_idempotency_key(mailing: Mailing) -> str:
    """Stable provider key without exposing the external identifier."""
    return sha256(f"mailing:{mailing.external_id}".encode()).hexdigest()


def retry_delay(attempt: int) -> timedelta:
    exponent = min(max(attempt - 1, 0), 30)
    delay = min(RETRY_BASE_SECONDS * 2**exponent, RETRY_MAX_SECONDS)
    jitter = random.randint(0, max(1, delay // 4))  # noqa: S311  # nosec B311
    return timedelta(seconds=min(delay + jitter, RETRY_MAX_SECONDS))


def send_email(mailing: Mailing, *, idempotency_key: str | None = None) -> None:
    """The task's simulated email transport; never log recipient or message contents."""
    # The task requires a non-cryptographic random delay.
    time.sleep(random.randint(5, 20))  # noqa: S311  # nosec B311
    _log_transport(mailing.pk, idempotency_key or delivery_idempotency_key(mailing))


def _fail_exhausted_claims(now: datetime) -> int:
    return Mailing.objects.filter(
        status=Mailing.Status.PROCESSING,
        claimed_at__lte=now - LEASE,
        attempts__gte=MAX_ATTEMPTS,
    ).update(
        status=Mailing.Status.FAILED,
        claimed_at=None,
        claim_token=None,
        next_attempt_at=None,
        last_error="AttemptsExhausted",
    )


def send_mailings(limit: int | None = None, retry_failed: bool = False) -> SendStats:
    """Visit eligible IDs up to the initial cutoff once, without locks during delivery."""
    if limit is not None and limit < 1:
        raise ValueError("Лимит должен быть положительным.")
    stats = SendStats()
    try:
        stats.failed += _fail_exhausted_claims(timezone.now())
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
            send_email(mailing, idempotency_key=delivery_idempotency_key(mailing))
        except Exception as exc:
            # Isolate transport failures; do not expose arbitrary exception payloads.
            error_type = type(exc).__name__
            can_retry = not isinstance(exc, PermanentTransportError) and (
                mailing.attempts < MAX_ATTEMPTS
            )
            values = {
                "status": Mailing.Status.RETRYING if can_retry else Mailing.Status.FAILED,
                "claim_token": None,
                "claimed_at": None,
                "next_attempt_at": (
                    timezone.now() + retry_delay(mailing.attempts) if can_retry else None
                ),
                "last_error": error_type[:128],
            }
        else:
            error_type = None
            values = {
                "status": Mailing.Status.SENT,
                "sent_at": timezone.now(),
                "claim_token": None,
                "claimed_at": None,
                "next_attempt_at": None,
                "last_error": "",
            }
        try:
            changed = owned.update(**values)
        except DatabaseError as exc:
            raise SendDatabaseError(stats, unconfirmed=1) from exc
        if error_type is not None:
            if can_retry:
                stats.retried += bool(changed)
                _log_diagnostic(
                    logging.WARNING,
                    "Отправка отложена mailing_id=%s attempt=%s type=%s",
                    mailing.pk,
                    mailing.attempts,
                    error_type,
                )
            else:
                stats.failed += bool(changed)
                _log_diagnostic(
                    logging.ERROR,
                    "Отправка завершилась ошибкой mailing_id=%s attempt=%s type=%s",
                    mailing.pk,
                    mailing.attempts,
                    error_type,
                )
        else:
            stats.sent += bool(changed)
        if not changed:
            stats.lost += 1
            _log_diagnostic(
                logging.WARNING, "Потерян захват mailing_id=%s; статус не изменён.", mailing.pk
            )
        processed += 1
    return stats
