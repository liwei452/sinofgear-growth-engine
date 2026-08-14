from django.urls import path

from .views import (
    ConnectorCredentialDetailView, ConnectorCredentialListView, PlatformListView,
    PlatformAuthorizationView, PlatformConnectionListView,
    SocialAccountConnectionView, SocialAccountDetailView, SocialAccountListView,
)

urlpatterns = [
    path("platforms", PlatformListView.as_view(), name="platform-list"),
    path("platform-connections", PlatformConnectionListView.as_view(), name="platform-connection-list"),
    path(
        "platform-connections/<str:platform_code>/authorize",
        PlatformAuthorizationView.as_view(),
        name="platform-connection-authorize",
    ),
    path("social-accounts", SocialAccountListView.as_view(), name="social-account-list"),
    path("social-accounts/connect", SocialAccountConnectionView.as_view(), name="social-account-connect"),
    path("social-accounts/<uuid:account_id>", SocialAccountDetailView.as_view(), name="social-account-detail"),
    path("connector-credentials", ConnectorCredentialListView.as_view(), name="connector-credential-list"),
    path("connector-credentials/<uuid:credential_id>", ConnectorCredentialDetailView.as_view(), name="connector-credential-detail"),
]
