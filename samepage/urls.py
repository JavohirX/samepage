from django.urls import include, path
from drf_spectacular.renderers import OpenApiJsonRenderer
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("openapi.json", SpectacularAPIView.as_view(renderer_classes=[OpenApiJsonRenderer]), name="openapi-schema"),
    path("api/v1/openapi.json", SpectacularAPIView.as_view(renderer_classes=[OpenApiJsonRenderer]), name="openapi-schema-v1"),
    path("docs", SpectacularSwaggerView.as_view(url_name="openapi-schema"), name="swagger-ui"),
    path("", include("samepage.apps.portal.urls")),
]

handler404 = "samepage.core.errors.handle_404"
handler500 = "samepage.core.errors.handle_500"
