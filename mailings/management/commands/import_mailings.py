from argparse import ArgumentParser
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from mailings.importing import WorkbookError, import_mailings


class Command(BaseCommand):
    help = "Импорт рассылок из XLSX-файла: первая строка — заголовки колонок."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("path", type=Path, help="Путь к XLSX-файлу")

    def handle(self, *args: object, **options: Path) -> None:
        path = options["path"]
        if not path.exists():
            raise CommandError(f"Файл не найден: {path}")
        try:
            stats = import_mailings(path)
        except WorkbookError as exc:
            raise CommandError(str(exc)) from exc
        except DatabaseError as exc:
            raise CommandError("Ошибка базы данных при импорте.") from exc

        self.stdout.write(
            f"Обработано: {stats.processed}; создано: {stats.created}; "
            f"пропущено: {stats.skipped}; ошибочных строк: {stats.errors}"
        )
