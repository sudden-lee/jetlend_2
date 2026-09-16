import logging
import posixpath
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from zipfile import BadZipFile, ZipFile
from zlib import error as ZlibError

from defusedxml import ElementTree as safe_xml
from defusedxml.common import DefusedXmlException
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import DatabaseError, connection
from django.utils import timezone
from openpyxl import load_workbook
from openpyxl.cell.cell import Cell
from openpyxl.cell.read_only import EmptyCell, ReadOnlyCell
from openpyxl.formula.translate import TranslatorError
from openpyxl.utils.exceptions import InvalidFileException
from psycopg import sql

from mailings.models import Mailing

logger = logging.getLogger(__name__)
COLUMNS = ("external_id", "user_id", "email", "subject", "message")
FILE_ERRORS = (
    OSError,
    BadZipFile,
    InvalidFileException,
    safe_xml.ParseError,
    DefusedXmlException,
    KeyError,
    IndexError,
    OverflowError,
    TranslatorError,
    TypeError,
    ValueError,
    EOFError,
    ZlibError,
)
CellType = Cell | ReadOnlyCell | EmptyCell


@dataclass
class ImportStats:
    processed: int = 0
    created: int = 0
    skipped: int = 0
    errors: int = 0

    @property
    def unfinished(self) -> int:
        """Rows read but not yet classified as committed, skipped, or invalid."""
        return self.processed - self.created - self.skipped - self.errors


class WorkbookError(ValueError):
    def __init__(self, message: str, stats: ImportStats) -> None:
        super().__init__(message)
        self.stats = stats


class ImportDatabaseError(RuntimeError):
    def __init__(self, stats: ImportStats) -> None:
        super().__init__("Ошибка базы данных при импорте.")
        self.stats = stats


class RowError(ValueError):
    pass


class HeaderError(ValueError):
    pass


WORKBOOK_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
WORKBOOK_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
MAX_METADATA_BYTES = 10 * 1024 * 1024


def _read_package_xml(archive: ZipFile, name: str):
    info = archive.getinfo(name)
    if info.file_size > MAX_METADATA_BYTES:
        raise InvalidFileException("Workbook metadata is too large.")
    return safe_xml.fromstring(archive.read(info), forbid_dtd=True)


def validate_first_worksheet(source: BinaryIO) -> None:
    """Reject a package whose first declared worksheet part is missing."""
    with ZipFile(source) as archive:
        content_types = _read_package_xml(archive, "[Content_Types].xml")
        workbook_part = next(
            (
                item.get("PartName", "").lstrip("/")
                for item in content_types.findall(f"{{{CONTENT_TYPES_NS}}}Override")
                if item.get("ContentType") == WORKBOOK_CONTENT_TYPE
            ),
            "",
        )
        if not workbook_part:
            raise InvalidFileException("Workbook part is missing.")

        workbook = _read_package_xml(archive, workbook_part)
        directory, filename = posixpath.split(workbook_part)
        relationships_part = posixpath.join(directory, "_rels", f"{filename}.rels")
        relationships = _read_package_xml(archive, relationships_part)
        by_id = {
            relation.get("Id"): relation
            for relation in relationships.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
        }
        for sheet in workbook.findall(f".//{{{WORKBOOK_NS}}}sheet"):
            relation = by_id.get(sheet.get(f"{{{OFFICE_REL_NS}}}id"))
            if relation is None:
                raise InvalidFileException("Worksheet relationship is missing.")
            if not relation.get("Type", "").endswith("/worksheet"):
                continue
            target = relation.get("Target", "")
            if relation.get("TargetMode") == "External" or not target:
                raise InvalidFileException("Worksheet part is external or missing.")
            if target.startswith("/"):
                worksheet_part = posixpath.normpath(target).lstrip("/")
            else:
                worksheet_part = posixpath.normpath(posixpath.join(directory, target))
            try:
                archive.getinfo(worksheet_part)
            except KeyError as exc:
                raise InvalidFileException("Worksheet part is missing.") from exc
            return
        raise InvalidFileException("Workbook contains no worksheets.")


def parse_headers(row: Sequence[CellType]) -> dict[str, int]:
    indexes: dict[str, int] = {}
    for index, cell in enumerate(row):
        if not isinstance(cell.value, str):
            continue
        name = cell.value.strip()
        if name in COLUMNS:
            if name in indexes:
                raise HeaderError(f"Повторяющийся заголовок: {name}.")
            indexes[name] = index
    missing = set(COLUMNS) - indexes.keys()
    if missing:
        raise HeaderError(f"Отсутствуют колонки: {', '.join(sorted(missing))}.")
    return indexes


def parse_row(row: Sequence[CellType], indexes: dict[str, int]) -> Mailing:
    values: dict[str, object] = {}
    for name, index in indexes.items():
        if index >= len(row) or row[index].value is None:
            raise RowError(f"{name}: обязательное поле.")
        cell = row[index]
        if cell.data_type in {"f", "e"}:
            raise RowError(f"{name}: формулы и ошибки Excel не поддерживаются.")
        values[name] = cell.value

    external_id = values["external_id"]
    if type(external_id) is int and abs(external_id) < 10**15:
        external_id = str(external_id)
    if not isinstance(external_id, str) or not 1 <= len(external_id.strip()) <= 255:
        raise RowError("external_id: требуется текст до 255 символов или целое до 15 цифр.")
    external_id = external_id.strip()
    if "\x00" in external_id:
        raise RowError("external_id: недопустимый символ.")

    user_id = values["user_id"]
    if isinstance(user_id, str):
        text = user_id.strip()
        if not text.isascii() or not text.isdecimal() or len(text) > 19:
            raise RowError("user_id: требуется положительное целое число.")
        user_id = int(text)
    elif type(user_id) is not int or user_id >= 10**15:
        raise RowError("user_id: большие идентификаторы нужно хранить как текст.")
    if not 1 <= user_id <= 2**63 - 1:
        raise RowError("user_id: число вне диапазона 1..9223372036854775807.")

    texts: dict[str, str] = {}
    for name, limit in (("email", 254), ("subject", 255), ("message", 32767)):
        value = values[name]
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise RowError(f"{name}: требуется непустой текст до {limit} символов.")
        if "\x00" in value or (name != "message" and any(c in value for c in "\r\n")):
            raise RowError(f"{name}: недопустимый символ.")
        texts[name] = value.strip() if name == "email" else value
    try:
        validate_email(texts["email"])
    except ValidationError as exc:
        raise RowError("email: некорректный адрес.") from exc

    return Mailing(external_id=external_id, user_id=user_id, **texts)


def save_batch(batch: list[Mailing], stats: ImportStats) -> None:
    if not batch:
        return
    unique: dict[str, Mailing] = {}
    for mailing in batch:
        unique.setdefault(mailing.external_id, mailing)

    columns = (
        "external_id",
        "user_id",
        "email",
        "subject",
        "message",
        "status",
        "created_at",
        "sent_at",
        "claimed_at",
        "claim_token",
        "attempts",
        "last_error",
    )
    created_at = timezone.now()
    rows = [
        (
            mailing.external_id,
            mailing.user_id,
            mailing.email,
            mailing.subject,
            mailing.message,
            mailing.status,
            created_at,
            mailing.sent_at,
            mailing.claimed_at,
            mailing.claim_token,
            mailing.attempts,
            mailing.last_error,
        )
        for mailing in unique.values()
    ]
    row_placeholder = sql.SQL("({})").format(sql.SQL(", ").join(sql.Placeholder() for _ in columns))
    statement = sql.SQL(
        "INSERT INTO {} ({}) VALUES {} ON CONFLICT ({}) DO NOTHING RETURNING 1"
    ).format(
        sql.Identifier(Mailing._meta.db_table),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(row_placeholder for _ in rows),
        sql.Identifier("external_id"),
    )
    params = [value for row in rows for value in row]
    with connection.cursor() as cursor:
        cursor.execute(statement, params)
        created = len(cursor.fetchall())
    stats.created += created
    stats.skipped += len(batch) - created
    batch.clear()


def save_import_batch(batch: list[Mailing], stats: ImportStats) -> None:
    try:
        save_batch(batch, stats)
    except DatabaseError as exc:
        raise ImportDatabaseError(stats) from exc


def import_mailings(path: Path, batch_size: int = 500) -> ImportStats:
    """Import the first worksheet; retain completed batches if the input is damaged."""
    stats = ImportStats()
    if not 1 <= batch_size <= 500:
        raise ValueError("Размер пакета должен быть от 1 до 500.")
    if path.suffix.lower() != ".xlsx":
        raise WorkbookError("Ожидается файл с расширением .xlsx.", stats)
    try:
        source = path.open("rb")
    except OSError as exc:
        raise WorkbookError("Не удалось открыть XLSX-файл.", stats) from exc

    with source:
        try:
            validate_first_worksheet(source)
            source.seek(0)
            workbook = load_workbook(source, read_only=True, data_only=False, keep_links=False)
        except FILE_ERRORS as exc:
            raise WorkbookError("Не удалось прочитать XLSX-файл.", stats) from exc

        batch: list[Mailing] = []
        try:
            if not workbook.worksheets:
                raise WorkbookError("В файле нет листов.", stats)
            sheet = workbook.worksheets[0]
            sheet.reset_dimensions()
            with closing(sheet.iter_rows()) as rows:
                try:
                    headers = next(rows, ())
                except FILE_ERRORS as exc:
                    raise WorkbookError("Ошибка структуры или чтения XLSX-файла.", stats) from exc
                try:
                    indexes = parse_headers(headers)
                except HeaderError as exc:
                    raise WorkbookError(str(exc), stats) from exc
                number = 1
                while True:
                    try:
                        row = next(rows)
                    except StopIteration:
                        break
                    except FILE_ERRORS as exc:
                        # Valid rows already read remain usable; a repeat import is safe.
                        save_import_batch(batch, stats)
                        raise WorkbookError(
                            "Ошибка структуры или чтения XLSX-файла.", stats
                        ) from exc
                    number += 1
                    if all(cell.value is None for cell in row):
                        continue
                    stats.processed += 1
                    try:
                        batch.append(parse_row(row, indexes))
                    except RowError as exc:
                        stats.errors += 1
                        logger.warning("Строка %s: %s", number, exc)
                    if len(batch) >= batch_size:
                        save_import_batch(batch, stats)
            save_import_batch(batch, stats)
            return stats
        finally:
            workbook.close()
