from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.permissions import CanManageCredentials, CanReadMemberships

from .models import Platform, SocialAccount
from .serializers import PlatformSerializer, SocialAccountSerializer


class PlatformListView(APIView):
    permission_classes = [CanReadMemberships]

    def get(self, request: Request) -> Response:
        platforms = Platform.objects.prefetch_related("capability_definitions").all()
        return Response({"results": PlatformSerializer(platforms, many=True).data})


class SocialAccountListView(APIView):
    permission_classes = [CanManageCredentials]

    def get(self, request: Request) -> Response:
        accounts = SocialAccount.objects.filter(organization=request.organization).select_related("platform", "credential")
        return Response({"results": SocialAccountSerializer(accounts, many=True).data})

    def post(self, request: Request) -> Response:
        serializer = SocialAccountSerializer(data=request.data, context={"organization": request.organization})
        serializer.is_valid(raise_exception=True)
        account = serializer.save()
        return Response(SocialAccountSerializer(account).data, status=status.HTTP_201_CREATED)

