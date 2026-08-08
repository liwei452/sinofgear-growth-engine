from django.urls import path

from .views import PlatformListView, SocialAccountListView

urlpatterns = [
    path("platforms", PlatformListView.as_view(), name="platform-list"),
    path("social-accounts", SocialAccountListView.as_view(), name="social-account-list"),
]

