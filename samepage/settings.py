"""Runtime settings.

SAMEPAGE_MODE is "demo" or "production" and defaults to production, so a missing
variable never turns the demo sign-in links and the published demo tokens on.
DEBUG is off unless SAMEPAGE_DEBUG=1 and the mode is demo.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

MODES = ("demo", "production")
MODE = os.environ.get("SAMEPAGE_MODE", "production").strip().lower()
if MODE not in MODES:
    raise ImproperlyConfigured(f"SAMEPAGE_MODE must be demo or production, not {MODE!r}.")
DEMO_MODE = MODE == "demo"
DEBUG = os.environ.get("SAMEPAGE_DEBUG") == "1" and DEMO_MODE
# The demo key is public. Production refuses to boot with it (samepage/ops/preflight.py).
DEMO_SECRET_KEY = "demo-secret-key-not-for-production-use-32b"
SECRET_KEY = os.environ.get("SECRET_KEY") or DEMO_SECRET_KEY
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,app").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
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

# Without it psycopg waits up to 130 s for an unreachable database; /readyz should say 503 well before that.
DB_OPTIONS = {"connect_timeout": 5}


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
        "OPTIONS": dict(DB_OPTIONS),
    }


def _databases() -> dict:
    # DB_OWNER_URL last: a one-off `docker compose exec app python manage.py ...` has only the owner URL.
    # The served process always has DATABASE_URL (the entrypoint sets it to the runtime role).
    url = os.environ.get("DATABASE_URL") or os.environ.get("DB_APP_URL") or os.environ.get("DB_OWNER_URL")
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
            "OPTIONS": dict(DB_OPTIONS),
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
    "DEFAULT_CONTENT_NEGOTIATION_CLASS": "samepage.core.negotiation.ViewChoosesFormat",
    "URL_FORMAT_OVERRIDE": None,
    "DEFAULT_SCHEMA_CLASS": "samepage.core.schema.SamepageAutoSchema",
    "EXCEPTION_HANDLER": "samepage.core.errors.exception_handler",
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
    # Only write actions are throttled (core/throttles.py). run.py's GET routes are not.
    "DEFAULT_THROTTLE_RATES": {
        "login": os.environ.get("SAMEPAGE_LOGIN_RATE", "10/min"),
        "ballot": os.environ.get("SAMEPAGE_BALLOT_RATE", "30/min"),
        "comment": os.environ.get("SAMEPAGE_COMMENT_RATE", "10/min"),
        "magic_link": os.environ.get("SAMEPAGE_MAGIC_LINK_RATE", "5/min"),
    },
    # 0 means the throttle keys on the TCP peer and ignores X-Forwarded-For, which a client can forge.
    # Behind one reverse proxy that sets X-Forwarded-For, set SAMEPAGE_NUM_PROXIES=1.
    "NUM_PROXIES": int(os.environ.get("SAMEPAGE_NUM_PROXIES", "0")),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Samepage API",
    "DESCRIPTION": "OpenAPI specification for Samepage evaluation and hackathon platform.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

CSRF_FAILURE_VIEW = "samepage.core.errors.csrf_failure"

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    # The sign-in throttle counts in Postgres (migration 0003), so the limit holds across gunicorn workers.
    "throttle": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "samepage_cache"},
}

ENGINE_BOOT_BUDGET_S = float(os.environ.get("SAMEPAGE_ENGINE_BOOT_BUDGET_S", "30"))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8080")
# Passwords that production refuses for the database owner and runtime roles.
DEFAULT_DB_PASSWORDS = {"", "demo-owner", "demo-app", "postgres", "password", "samepage"}

# Behind TLS, cookies are Secure. Plain http on localhost keeps them usable in demo mode.
if not DEMO_MODE and PUBLIC_URL.startswith("https://"):
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# One line per request error on stdout, with the correlation id the error page shows.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "stdout": {"class": "logging.StreamHandler", "stream": "ext://sys.stdout", "formatter": "plain"},
    },
    "loggers": {
        "samepage": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["stdout"], "level": "ERROR", "propagate": False},
    },
}
