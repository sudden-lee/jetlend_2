import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


def positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be a positive integer.") from exc
    if value < 1:
        raise ImproperlyConfigured(f"{name} must be a positive integer.")
    return value


BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY when DJANGO_DEBUG=0.")
    # Stable local sessions; production cannot reach this branch.
    SECRET_KEY = "local-admin-development-key-do-not-use-in-production"  # noqa: S105  # nosec B105

POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")
if not POSTGRES_PASSWORD:
    if not DEBUG:
        raise ImproperlyConfigured("Set POSTGRES_PASSWORD when DJANGO_DEBUG=0.")
    # Matches compose.yaml for local development only.
    POSTGRES_PASSWORD = "mailings-local"  # noqa: S105  # nosec B105

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "mailings.apps.MailingsConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MAILINGS_LEASE_SECONDS = positive_int_env("MAILINGS_LEASE_SECONDS", 300)
MAILINGS_MAX_ATTEMPTS = positive_int_env("MAILINGS_MAX_ATTEMPTS", 5)
MAILINGS_RETRY_BASE_SECONDS = positive_int_env("MAILINGS_RETRY_BASE_SECONDS", 30)
MAILINGS_RETRY_MAX_SECONDS = positive_int_env("MAILINGS_RETRY_MAX_SECONDS", 3600)
if MAILINGS_RETRY_BASE_SECONDS > MAILINGS_RETRY_MAX_SECONDS:
    raise ImproperlyConfigured(
        "MAILINGS_RETRY_BASE_SECONDS must not exceed MAILINGS_RETRY_MAX_SECONDS."
    )
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "ru-ru"
USE_I18N = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "0")) if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = (
    not DEBUG and os.environ.get("DJANGO_HSTS_INCLUDE_SUBDOMAINS", "0") == "1"
)
SECURE_HSTS_PRELOAD = not DEBUG and os.environ.get("DJANGO_HSTS_PRELOAD", "0") == "1"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "mailings"),
        "USER": os.environ.get("POSTGRES_USER", "mailings"),
        "PASSWORD": POSTGRES_PASSWORD,
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "OPTIONS": {"connect_timeout": 5},
    }
}
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"default": {"format": "{asctime} {levelname} {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "default"}},
    "loggers": {"mailings": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}
