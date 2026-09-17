from argparse import ArgumentParser

from django.core.management.base import BaseCommand, CommandError

from mailings.sending import SendDatabaseError, SendStats, send_mailings


class Command(BaseCommand):
    help = "Отправка сохранённой очереди через лог с задержкой 5–20 секунд."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--limit", type=int)
        parser.add_argument("--retry-failed", action="store_true")

    def report(self, stats: SendStats, unconfirmed: int = 0) -> None:
        self.stdout.write(
            f"Отправлено: {stats.sent}; назначено повторов: {stats.retried}; "
            f"окончательных ошибок: {stats.failed}; "
            f"потеряно захватов: {stats.lost}; "
            f"неподтверждённых результатов: {unconfirmed}"
        )

    def handle(self, *args: object, **options: object) -> None:
        limit = options["limit"]
        if limit is not None and (not isinstance(limit, int) or limit < 1):
            raise CommandError("--limit должен быть положительным.")
        try:
            stats = send_mailings(limit=limit, retry_failed=bool(options["retry_failed"]))
        except SendDatabaseError as exc:
            self.report(exc.stats, exc.unconfirmed)
            raise CommandError("Сбой базы данных при обработке очереди.") from None
        self.report(stats)
        if stats.retried or stats.failed or stats.lost:
            raise CommandError("Очередь обработана с ошибками.")
