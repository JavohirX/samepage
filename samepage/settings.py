"""Runtime settings. DEBUG is off unless SAMEPAGE_DEBUG=1 and the mode is not production."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent

MODE = os.environ.get("SAMEPAGE_MODE", "demo")
DEMO_MODE = MODE != "production"
DEBUG = os.environ.get("SAMEPAGE_DEBUG") == "1" and DEMO_MODE
SECRET_KEY = os.environ.get("SECRET_KEY", "demo-secret-key-not-for-production-use-32b")
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,app").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "samepage.apps.portal",
]

MIDDLEWARE = [
    "samepage.core.middleware.CorrelationMiddleware",
    "samepage.core.middleware.BearerCSRFBypass",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "samepage.core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "samepage.urls"
WSGI_APPLICATION = "samepage.wsgi.application"
AUTH_USER_MODEL = "portal.Person"
APPEND_SLASH = False
LOGIN_URL = "/login"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "samepage" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "samepage.core.context.shell",
            ],
        },
    }
]

def _parse_database_url(url: str) -> dict:
    parsed = urlparse(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "127.0.0.1",
        "PORT": str(parsed.port or 5432),
        "ATOMIC_REQUESTS": True,
        "CONN_HEALTH_CHECKS": True,
    }


def _databases() -> dict:
    url = os.environ.get("DATABASE_URL") or os.environ.get("DB_APP_URL")
    if url:
        return {"default": _parse_database_url(url)}
    return {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "samepage"),
            "USER": os.environ.get("DB_USER", "samepage_app"),
            "PASSWORD": os.environ.get("DB_PASSWORD", "demo-app"),
            "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
            "PORT": os.environ.get("DB_PORT", "5432"),
            "ATOMIC_REQUESTS": True,
            "CONN_HEALTH_CHECKS": True,
        }
    }


DATABASES = _databases()

AUTH_PASSWORD_VALIDATORS = []
if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("SAMEPAGE_FAST_HASH") == "1":
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "samepage" / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
WHITENOISE_USE_FINDERS = True

MEDIA_ROOT = os.environ.get("MEDIA_ROOT", str(BASE_DIR / "media"))
MEDIA_URL = "/media-files/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "samepage.core.auth.BearerAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "URL_FORMAT_OVERRIDE": None,
    "EXCEPTION_HANDLER": "samepage.core.errors.exception_handler",
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
}

CSRF_FAILURE_VIEW = "samepage.core.errors.csrf_failure"

ENGINE_BOOT_BUDGET_S = float(os.environ.get("SAMEPAGE_ENGINE_BOOT_BUDGET_S", "30"))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8080")
TRUSTED_PROXIES = [h.strip() for h in os.environ.get("TRUSTED_PROXIES", "").split(",") if h.strip()]
DEFAULT_DB_PASSWORDS = {"demo-owner", "demo-app", "postgres", "password"}
