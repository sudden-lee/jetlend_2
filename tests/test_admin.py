import pytest
from django.contrib import admin
from django.test import RequestFactory
from django.urls import reverse

from mailings.models import Mailing

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_user(django_user_model):
    return django_user_model.objects.create_superuser(username="admin")


@pytest.fixture
def visible_mailing(make_mailing):
    return make_mailing(
        external_id="admin-visible",
        user_id=42,
        email="admin@example.com",
        subject="Visible subject",
        message="Visible message",
    )


def test_model_has_localized_names(visible_mailing):
    assert str(visible_mailing) == "admin-visible"
    assert Mailing._meta.verbose_name == "рассылка"
    assert visible_mailing.get_status_display() == "Ожидает отправки"


def test_admin_changelist_is_registered_and_searchable(client, staff_user, visible_mailing):
    changelist_url = reverse("admin:mailings_mailing_changelist")
    assert client.get(changelist_url).status_code == 302

    client.force_login(staff_user)
    response = client.get(changelist_url, {"q": "admin-visible"})
    assert response.status_code == 200
    assert b"admin-visible" in response.content


def test_admin_forbids_bypassing_the_import_and_send_commands(staff_user, visible_mailing):
    model_admin = admin.site._registry[Mailing]
    request = RequestFactory().get("/admin/mailings/mailing/")
    request.user = staff_user
    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request, visible_mailing) is False
    assert model_admin.has_delete_permission(request, visible_mailing) is False
