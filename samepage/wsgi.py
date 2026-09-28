import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "samepage.settings")

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
