from django.urls import path

from .views import CsrfCookieView, CurrentUserView, LoginView, LogoutView, MembershipDetailView

urlpatterns = [
    path("auth/login", LoginView.as_view(), name="login"),
    path("auth/csrf", CsrfCookieView.as_view(), name="csrf-cookie"),
    path("auth/logout", LogoutView.as_view(), name="logout"),
    path("auth/me", CurrentUserView.as_view(), name="current-user"),
    path("memberships/<uuid:membership_id>", MembershipDetailView.as_view(), name="membership-detail"),
]
