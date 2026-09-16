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
        "attempts",
        "created_at",
        "sent_at",
    )
    list_display_links = ("id", "external_id")
    list_filter = ("status", "created_at", "sent_at")
    search_fields = ("=external_id", "=user_id", "email", "subject")
    search_help_text = "Поиск по внешнему ID, ID пользователя, email или теме"
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_per_page = 100
    show_full_result_count = False
    actions = None
    readonly_fields = (
        "id",
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
    fieldsets = (
        (
            "Письмо",
            {"fields": ("id", "external_id", "user_id", "email", "subject", "message")},
        ),
        (
            "Обработка",
            {
                "fields": (
                    "status",
                    "attempts",
                    "last_error",
                    "claim_token",
                    "claimed_at",
                )
            },
        ),
        ("Время", {"fields": ("created_at", "sent_at")}),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Mailing | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Mailing | None = None) -> bool:
        return False


admin.site.site_header = "Управление рассылками"
admin.site.site_title = "Рассылки"
admin.site.index_title = "Очередь писем"
