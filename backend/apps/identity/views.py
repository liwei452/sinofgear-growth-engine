from django.contrib.auth import login, logout
from django.http import Http404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from .models import Membership
from .permissions import CanManageMemberships, CanReadMemberships
from .serializers import (
    CurrentUserSerializer,
    LoginSerializer,
    MembershipSerializer,
    MembershipStatusSerializer,
)


class LoginRateThrottle(AnonRateThrottle):
    """Per-IP rate limit for credential attempts on the login endpoint."""

    scope = "login"


@method_decorator(csrf_protect, name="dispatch")
@extend_schema(tags=["Auth"])
class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]

    @extend_schema(request=LoginSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_400_BAD_REQUEST)
        login(request, serializer.validated_data["user"])
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["Auth"])
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(ensure_csrf_cookie, name="dispatch")
@extend_schema(tags=["Auth"])
class CsrfCookieView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses={204: None})
    def get(self, request: Request) -> Response:
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["Auth"])
class CurrentUserView(APIView):
    permission_classes = [CanReadMemberships]

    @extend_schema(responses={200: CurrentUserSerializer})
    def get(self, request: Request) -> Response:
        return Response(CurrentUserSerializer(request.membership).data)


@extend_schema(tags=["Auth"])
class MembershipDetailView(APIView):
    def get_permissions(self) -> list[IsAuthenticated]:
        permission_class = CanReadMemberships if self.request.method == "GET" else CanManageMemberships
        return [permission_class()]

    def get_object(self, request: Request, membership_id: str) -> Membership:
        try:
            return Membership.objects.select_related("organization", "role", "user").get(
                id=membership_id,
                organization=request.organization,
            )
        except Membership.DoesNotExist as error:
            raise Http404 from error

    @extend_schema(responses={200: MembershipSerializer})
    def get(self, request: Request, membership_id: str) -> Response:
        return Response(MembershipSerializer(self.get_object(request, membership_id)).data)

    @extend_schema(request=MembershipStatusSerializer, responses={200: MembershipSerializer})
    def patch(self, request: Request, membership_id: str) -> Response:
        serializer = MembershipStatusSerializer(
            self.get_object(request, membership_id), data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MembershipSerializer(serializer.instance).data)
