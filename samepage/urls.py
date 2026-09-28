from django.urls import include, path

urlpatterns = [
    path("", include("samepage.apps.portal.urls")),
]

handler404 = "samepage.core.errors.handle_404"
handler500 = "samepage.core.errors.handle_500"
