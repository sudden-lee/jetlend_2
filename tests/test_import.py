from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError

from mailings.importing import COLUMNS, ImportStats, WorkbookError, import_mailings
from mailings.models import Mailing

pytestmark = pytest.mark.django_db


def test_import_creates_mailings_and_reports_counts(make_workbook):
    rows = [
        ["first", 1, "one@example.com", "First subject", "First message"],
        ["second", 2, "two@example.com", "Second subject", "Second message"],
    ]
    stats = import_mailings(make_workbook(rows))
    assert stats == ImportStats(processed=2, created=2, skipped=0, errors=0)
    mailing = Mailing.objects.get(external_id="first")
    assert mailing.user_id == 1
    assert mailing.email == "one@example.com"
    assert mailing.status == Mailing.Status.PENDING


def test_reimport_skips_existing_external_ids(make_workbook):
    path = make_workbook([["first", 1, "one@example.com", "Subject", "Body"]])
    import_mailings(path)
    stats = import_mailings(path)
    assert stats == ImportStats(processed=1, created=0, skipped=1, errors=0)
    assert Mailing.objects.count() == 1


def test_duplicate_external_id_within_file_keeps_first(make_workbook):
    rows = [
        ["same", 1, "one@example.com", "First", "Body"],
        ["same", 2, "two@example.com", "Replacement", "Body"],
    ]
    stats = import_mailings(make_workbook(rows))
    assert stats == ImportStats(processed=2, created=1, skipped=1, errors=0)
    assert Mailing.objects.get().subject == "First"


def test_headers_can_be_reordered_and_extra_columns_ignored(make_workbook):
    headers = ("message", "ignored", "email", "user_id", "subject", "external_id")
    rows = [["Body", "extra", "user@example.com", "5", "Subject", "id"]]
    stats = import_mailings(make_workbook(rows, headers))
    assert stats == ImportStats(processed=1, created=1, skipped=0, errors=0)
    mailing = Mailing.objects.get()
    assert (mailing.external_id, mailing.user_id) == ("id", 5)


def test_empty_rows_are_not_counted(make_workbook):
    rows = [[None] * 5, ["id", 1, "user@example.com", "Subject", "Body"]]
    stats = import_mailings(make_workbook(rows))
    assert stats == ImportStats(processed=1, created=1, skipped=0, errors=0)


def test_invalid_rows_are_counted_as_errors_without_blocking_valid_rows(make_workbook, caplog):
    valid = ["good", 1, "user@example.com", "Subject", "Body"]
    invalid_rows = [
        ["missing-email", 1, "", "Subject", "Body"],
        ["bad-email", 1, "not-an-email", "Subject", "Body"],
        ["bad-user-id", "abc", "user@example.com", "Subject", "Body"],
        ["zero-user-id", 0, "user@example.com", "Subject", "Body"],
        ["missing-subject", 1, "user@example.com", "", "Body"],
    ]
    with caplog.at_level("WARNING", logger="mailings.importing"):
        stats = import_mailings(make_workbook([valid, *invalid_rows]))
    assert stats == ImportStats(processed=6, created=1, skipped=0, errors=5)
    assert Mailing.objects.get().external_id == "good"
    assert len(caplog.records) == 5


def test_missing_required_column_raises_workbook_error(make_workbook):
    with pytest.raises(WorkbookError):
        import_mailings(make_workbook([], headers=COLUMNS[:-1]))
    assert not Mailing.objects.exists()


def test_non_xlsx_extension_is_rejected(tmp_path):
    with pytest.raises(WorkbookError):
        import_mailings(tmp_path / "mailings.csv")


def test_command_reports_summary(make_workbook, capsys):
    rows = [
        ["good", 1, "user@example.com", "Subject", "Body"],
        ["bad", 1, "not-an-email", "Subject", "Body"],
    ]
    call_command("import_mailings", str(make_workbook(rows)))
    output = capsys.readouterr().out
    assert "Обработано: 2; создано: 1; пропущено: 0; ошибочных строк: 1" in output


def test_command_rejects_missing_file(tmp_path):
    with pytest.raises(CommandError):
        call_command("import_mailings", str(tmp_path / "missing.xlsx"))


def test_command_wraps_database_errors(make_workbook):
    rows = [["id", 1, "user@example.com", "Subject", "Body"]]
    with patch("mailings.models.Mailing.save", side_effect=DatabaseError("boom")):
        with pytest.raises(CommandError):
            call_command("import_mailings", str(make_workbook(rows)))
