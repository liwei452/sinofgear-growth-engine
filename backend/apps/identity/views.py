from django.contrib.auth import login, logout
from django.http import Http404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Membership
from .permissions import CanManageMemberships, CanReadMemberships
from .serializers import CurrentUserSerializer, LoginSerializer, MembershipSerializer


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_400_BAD_REQUEST)
        login(request, serializer.validated_data["user"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfCookieView(APIView):
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        return Response(status=status.HTTP_204_NO_CONTENT)


class CurrentUserView(APIView):
    permission_classes = [CanReadMemberships]

    def get(self, request: Request) -> Response:
        return Response(CurrentUserSerializer(request.membership).data)


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

    def get(self, request: Request, membership_id: str) -> Response:
        return Response(MembershipSerializer(self.get_object(request, membership_id)).data)

    def patch(self, request: Request, membership_id: str) -> Response:
        serializer = MembershipSerializer(
            self.get_object(request, membership_id), data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
