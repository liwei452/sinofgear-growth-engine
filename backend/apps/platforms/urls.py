from django.urls import path

from .views import (
    ConnectorCredentialDetailView, ConnectorCredentialListView, PlatformListView,
    SocialAccountDetailView, SocialAccountListView,
)

urlpatterns = [
    path("platforms", PlatformListView.as_view(), name="platform-list"),
    path("social-accounts", SocialAccountListView.as_view(), name="social-account-list"),
    path("social-accounts/<uuid:account_id>", SocialAccountDetailView.as_view(), name="social-account-detail"),
    path("connector-credentials", ConnectorCredentialListView.as_view(), name="connector-credential-list"),
    path("connector-credentials/<uuid:credential_id>", ConnectorCredentialDetailView.as_view(), name="connector-credential-detail"),
]
