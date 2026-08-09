from django.urls import path

from .views import ProductDetailView, ProductListView


urlpatterns = [
    path("products", ProductListView.as_view(), name="products"),
    path("products/<uuid:product_id>", ProductDetailView.as_view(), name="product-detail"),
]
