from django.contrib import admin
from django.http import HttpRequest

from mailings.models import Mailing


@admin.register(Mailing)
class MailingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "external_id",
        "user_id",
        "email",
        "status",
        "created_at",
        "sent_at",
    )
    list_filter = ("status",)
    search_fields = ("external_id", "email", "subject")
    readonly_fields = [field.name for field in Mailing._meta.fields]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Mailing | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Mailing | None = None) -> bool:
        return False
