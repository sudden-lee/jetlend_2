import pytest
from openpyxl import Workbook

from mailings.importing import COLUMNS
from mailings.models import Mailing


@pytest.fixture(autouse=True)
def fast_password_hasher(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def make_workbook(tmp_path):
    def _make(rows, headers=COLUMNS):
        path = tmp_path / "mailings.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        workbook.save(path)
        workbook.close()
        return path

    return _make


@pytest.fixture
def make_mailing(db):
    def _make(**overrides):
        data = {
            "external_id": "id",
            "user_id": 1,
            "email": "user@example.com",
            "subject": "Subject",
            "message": "Body",
        }
        data.update(overrides)
        return Mailing.objects.create(**data)

    return _make
