from django.db import models


class Mailing(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает отправки"
        RETRYING = "retrying", "Ожидает повтора"
        PROCESSING = "processing", "Отправляется"
        SENT = "sent", "Отправлено"
        FAILED = "failed", "Ошибка отправки"

    external_id = models.CharField("внешний идентификатор", max_length=255, unique=True)
    user_id = models.PositiveBigIntegerField("идентификатор пользователя")
    email = models.EmailField("email получателя", max_length=254)
    subject = models.CharField("тема письма", max_length=255)
    message = models.TextField("текст письма")
    status = models.CharField(
        "статус",
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField("создано", auto_now_add=True)
    sent_at = models.DateTimeField("отправлено", null=True, blank=True)
    claimed_at = models.DateTimeField("захвачено обработчиком", null=True, blank=True)
    claim_token = models.UUIDField("токен обработчика", null=True, blank=True)
    next_attempt_at = models.DateTimeField("следующая попытка", null=True, blank=True)
    attempts = models.PositiveIntegerField("попыток отправки", default=0)
    last_error = models.CharField("последняя ошибка", max_length=128, blank=True)

    class Meta:
        verbose_name = "рассылка"
        verbose_name_plural = "рассылки"
        indexes = [
            models.Index(
                fields=("status", "next_attempt_at", "id"),
                name="mailing_ready_idx",
            ),
            models.Index(
                fields=("status", "claimed_at", "id"),
                name="mailing_lease_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(user_id__gt=0),
                name="mailing_user_id_gt_0",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="processing",
                        claimed_at__isnull=False,
                        claim_token__isnull=False,
                        next_attempt_at__isnull=True,
                        sent_at__isnull=True,
                    )
                    | models.Q(
                        status="sent",
                        claimed_at__isnull=True,
                        claim_token__isnull=True,
                        next_attempt_at__isnull=True,
                        sent_at__isnull=False,
                    )
                    | models.Q(
                        status__in=("pending", "failed"),
                        claimed_at__isnull=True,
                        claim_token__isnull=True,
                        next_attempt_at__isnull=True,
                        sent_at__isnull=True,
                    )
                    | models.Q(
                        status="retrying",
                        claimed_at__isnull=True,
                        claim_token__isnull=True,
                        next_attempt_at__isnull=False,
                        sent_at__isnull=True,
                    )
                ),
                name="mailing_status_fields_consistent",
            ),
        ]

    def __str__(self) -> str:
        return self.external_id
