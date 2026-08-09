from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.permissions import CanManageCredentials, CanReadMemberships, CanReadPublishing

from .models import ConnectorCredential, Platform, SocialAccount
from .serializers import (
    ConnectorCredentialCreateSerializer, ConnectorCredentialListSerializer,
    ConnectorCredentialReadSerializer, ConnectorCredentialUpdateSerializer,
    PlatformListSerializer, PlatformSerializer, SocialAccountCreateSerializer,
    SocialAccountConnectionSerializer, SocialAccountListSerializer, SocialAccountReadSerializer,
    SocialAccountUpdateSerializer,
)


def _account(organization, account_id):
    try:
        return SocialAccount.objects.select_related("platform", "credential").get(
            pk=account_id, organization=organization
        )
    except (SocialAccount.DoesNotExist, ValueError) as error:
        raise Http404 from error


def _credential(organization, credential_id):
    try:
        return ConnectorCredential.objects.select_related("platform").get(
            pk=credential_id, organization=organization
        )
    except (ConnectorCredential.DoesNotExist, ValueError) as error:
        raise Http404 from error


@extend_schema(tags=["Platforms"])
class PlatformListView(APIView):
    permission_classes = [CanReadMemberships]

    @extend_schema(responses=PlatformListSerializer)
    def get(self, request: Request) -> Response:
        platforms = Platform.objects.prefetch_related("capability_definitions").all()
        return Response({"results": PlatformSerializer(platforms, many=True).data})


@extend_schema(tags=["SocialAccounts"])
class SocialAccountListView(APIView):
    def get_permissions(self):
        return [(CanManageCredentials if self.request.method == "POST" else CanReadPublishing)()]

    @extend_schema(operation_id="social_accounts_list", responses=SocialAccountListSerializer)
    def get(self, request: Request) -> Response:
        accounts = SocialAccount.objects.filter(organization=request.organization).select_related(
            "platform", "credential"
        )
        return Response({"results": SocialAccountReadSerializer(accounts, many=True).data})

    @extend_schema(
        request=SocialAccountCreateSerializer,
        responses={201: SocialAccountReadSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = SocialAccountCreateSerializer(
            data=request.data, context={"organization": request.organization}
        )
        serializer.is_valid(raise_exception=True)
        account = serializer.save()
        return Response(SocialAccountReadSerializer(account).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["SocialAccounts"])
class SocialAccountDetailView(APIView):
    def get_permissions(self):
        return [(CanManageCredentials if self.request.method == "PATCH" else CanReadPublishing)()]

    @extend_schema(operation_id="social_accounts_retrieve", responses={200: SocialAccountReadSerializer})
    def get(self, request: Request, account_id) -> Response:
        return Response(SocialAccountReadSerializer(_account(request.organization, account_id)).data)

    @extend_schema(
        request=SocialAccountUpdateSerializer,
        responses={200: SocialAccountReadSerializer},
    )
    def patch(self, request: Request, account_id) -> Response:
        account = _account(request.organization, account_id)
        serializer = SocialAccountUpdateSerializer(
            account, data=request.data, partial=True,
            context={"organization": request.organization},
        )
        serializer.is_valid(raise_exception=True)
        return Response(SocialAccountReadSerializer(serializer.save()).data)


@extend_schema(tags=["SocialAccounts"])
class SocialAccountConnectionView(APIView):
    permission_classes = [CanManageCredentials]

    @extend_schema(request=SocialAccountConnectionSerializer, responses={201: SocialAccountReadSerializer})
    def post(self, request: Request) -> Response:
        serializer = SocialAccountConnectionSerializer(
            data=request.data, context={"organization": request.organization}
        )
        serializer.is_valid(raise_exception=True)
        return Response(
            SocialAccountReadSerializer(serializer.save()).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["ConnectorCredentials"])
class ConnectorCredentialListView(APIView):
    permission_classes = [CanManageCredentials]

    @extend_schema(responses={200: ConnectorCredentialListSerializer})
    def get(self, request: Request) -> Response:
        credentials = ConnectorCredential.objects.filter(
            organization=request.organization
        ).select_related("platform")
        return Response({
            "results": ConnectorCredentialReadSerializer(credentials, many=True).data
        })

    @extend_schema(
        request=ConnectorCredentialCreateSerializer,
        responses={201: ConnectorCredentialReadSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = ConnectorCredentialCreateSerializer(
            data=request.data, context={"organization": request.organization}
        )
        serializer.is_valid(raise_exception=True)
        return Response(
            ConnectorCredentialReadSerializer(serializer.save()).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["ConnectorCredentials"])
class ConnectorCredentialDetailView(APIView):
    permission_classes = [CanManageCredentials]

    @extend_schema(
        request=ConnectorCredentialUpdateSerializer,
        responses={200: ConnectorCredentialReadSerializer},
    )
    def patch(self, request: Request, credential_id) -> Response:
        credential = _credential(request.organization, credential_id)
        serializer = ConnectorCredentialUpdateSerializer(
            credential, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        return Response(ConnectorCredentialReadSerializer(serializer.save()).data)
