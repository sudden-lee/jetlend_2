import logging
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError

from mailings.models import Mailing
from mailings.sending import SendStats, send_email, send_mailings

pytestmark = pytest.mark.django_db


def test_send_email_sleeps_and_logs_without_leaking_content(make_mailing, caplog):
    mailing = make_mailing()
    with patch("mailings.sending.random.randint", return_value=7) as randint:
        with patch("mailings.sending.time.sleep") as sleep:
            with caplog.at_level(logging.INFO, logger="mailings.sending"):
                send_email(mailing)
    randint.assert_called_once_with(5, 20)
    sleep.assert_called_once_with(7)
    assert caplog.messages == [f"Send EMAIL mailing_id={mailing.pk}"]


def test_send_mailings_marks_pending_as_sent(make_mailing):
    make_mailing()
    with patch("mailings.sending.time.sleep"):
        stats = send_mailings()
    assert stats == SendStats(sent=1, failed=0)
    mailing = Mailing.objects.get()
    assert mailing.status == Mailing.Status.SENT
    assert mailing.sent_at is not None


def test_send_mailings_marks_failed_on_transport_error(make_mailing, caplog):
    make_mailing()
    with patch("mailings.sending.send_email", side_effect=RuntimeError("boom")):
        with caplog.at_level(logging.WARNING, logger="mailings.sending"):
            stats = send_mailings()
    assert stats == SendStats(sent=0, failed=1)
    mailing = Mailing.objects.get()
    assert mailing.status == Mailing.Status.FAILED
    assert mailing.last_error == "boom"
    assert mailing.sent_at is None


def test_send_mailings_does_not_resend_already_processed(make_mailing):
    make_mailing(status=Mailing.Status.SENT)
    make_mailing(external_id="failed-one", status=Mailing.Status.FAILED)
    with patch("mailings.sending.send_email") as transport:
        stats = send_mailings()
    transport.assert_not_called()
    assert stats == SendStats()


def test_command_reports_summary(make_mailing, capsys):
    make_mailing()
    with patch("mailings.sending.time.sleep"):
        call_command("send_mailings")
    assert "Отправлено: 1; ошибок: 0" in capsys.readouterr().out


def test_command_wraps_database_errors(make_mailing):
    make_mailing()
    with patch("mailings.sending.time.sleep"):
        with patch("mailings.models.Mailing.save", side_effect=DatabaseError("boom")):
            with pytest.raises(CommandError):
                call_command("send_mailings")
