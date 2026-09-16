from argparse import ArgumentParser
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from mailings.importing import ImportDatabaseError, ImportStats, WorkbookError, import_mailings


class Command(BaseCommand):
    help = "Потоковый импорт XLSX в сохранённую очередь рассылок."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("path", type=Path)
        parser.add_argument("--batch-size", type=int, default=500)

    def report(self, stats: ImportStats, *, include_unfinished: bool = False) -> None:
        report = (
            f"Обработано: {stats.processed}; создано: {stats.created}; "
            f"пропущено: {stats.skipped}; ошибочных строк: {stats.errors}"
        )
        if include_unfinished:
            report += f"; незавершённых строк: {stats.unfinished}"
        self.stdout.write(report)

    def handle(self, *args: object, **options: object) -> None:
        path = options["path"]
        batch_size = options["batch_size"]
        if not isinstance(path, Path) or not isinstance(batch_size, int):
            raise CommandError("Некорректные параметры импорта.")
        if not 1 <= batch_size <= 500:
            raise CommandError("--batch-size должен быть от 1 до 500.")
        try:
            stats = import_mailings(path, batch_size)
        except WorkbookError as exc:
            self.report(exc.stats)
            raise CommandError(str(exc)) from None
        except ImportDatabaseError as exc:
            self.report(exc.stats, include_unfinished=True)
            raise CommandError("Ошибка базы данных; импорт завершён частично.") from None
        self.report(stats)
        if stats.errors:
            raise CommandError(
                "Импорт завершён с ошибочными строками; корректные строки сохранены."
            )
