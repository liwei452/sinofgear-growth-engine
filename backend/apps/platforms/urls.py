from django.urls import path

from .views import (
    ConnectorCredentialDetailView, ConnectorCredentialListView, PlatformListView,
    AccountConnectionConfirmationView, AccountConnectionSessionView,
    PlatformAuthorizationCallbackView, PlatformAuthorizationView, PlatformConnectionListView,
    SocialAccountConnectionView, SocialAccountDetailView, SocialAccountListView,
    SocialAccountDisconnectView, SocialAccountProbeView, SocialAccountReauthorizationView,
)

urlpatterns = [
    path("platforms", PlatformListView.as_view(), name="platform-list"),
    path("platform-connections", PlatformConnectionListView.as_view(), name="platform-connection-list"),
    path(
        "platform-connections/<str:platform_code>/authorize",
        PlatformAuthorizationView.as_view(),
        name="platform-connection-authorize",
    ),
    path(
        "platform-connections/<str:platform_code>/callback",
        PlatformAuthorizationCallbackView.as_view(),
        name="platform-connection-callback",
    ),
    path(
        "platform-connection-sessions/<uuid:session_id>",
        AccountConnectionSessionView.as_view(),
        name="platform-connection-session",
    ),
    path(
        "platform-connection-sessions/<uuid:session_id>/confirm",
        AccountConnectionConfirmationView.as_view(),
        name="platform-connection-session-confirm",
    ),
    path("social-accounts", SocialAccountListView.as_view(), name="social-account-list"),
    path("social-accounts/connect", SocialAccountConnectionView.as_view(), name="social-account-connect"),
    path("social-accounts/<uuid:account_id>", SocialAccountDetailView.as_view(), name="social-account-detail"),
    path("social-accounts/<uuid:account_id>/probe", SocialAccountProbeView.as_view(), name="social-account-probe"),
    path("social-accounts/<uuid:account_id>/reauthorize", SocialAccountReauthorizationView.as_view(), name="social-account-reauthorize"),
    path("social-accounts/<uuid:account_id>/disconnect", SocialAccountDisconnectView.as_view(), name="social-account-disconnect"),
    path("connector-credentials", ConnectorCredentialListView.as_view(), name="connector-credential-list"),
    path("connector-credentials/<uuid:credential_id>", ConnectorCredentialDetailView.as_view(), name="connector-credential-detail"),
]
