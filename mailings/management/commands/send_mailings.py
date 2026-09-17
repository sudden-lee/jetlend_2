from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from mailings.sending import send_mailings


class Command(BaseCommand):
    help = "Отправка рассылок из очереди: имитация письма — задержка 5-20 секунд и запись в лог."

    def handle(self, *args: object, **options: object) -> None:
        try:
            stats = send_mailings()
        except DatabaseError as exc:
            raise CommandError("Ошибка базы данных при отправке.") from exc
        self.stdout.write(f"Отправлено: {stats.sent}; ошибок: {stats.failed}")
