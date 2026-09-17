from django.db import models


class Mailing(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает отправки"
        SENT = "sent", "Отправлено"
        FAILED = "failed", "Ошибка отправки"

    external_id = models.CharField("внешний идентификатор", max_length=255, unique=True)
    user_id = models.PositiveBigIntegerField("идентификатор пользователя")
    email = models.EmailField("email получателя")
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
    last_error = models.CharField("последняя ошибка", max_length=255, blank=True)

    class Meta:
        verbose_name = "рассылка"
        verbose_name_plural = "рассылки"
        indexes = [models.Index(fields=("status",), name="mailing_status_idx")]

    def __str__(self) -> str:
        return self.external_id
