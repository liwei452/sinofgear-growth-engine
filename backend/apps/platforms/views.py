from urllib.parse import urlencode

from django.conf import settings
from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.permissions import CanManageCredentials, CanReadMemberships, CanReadPublishing

from .models import ConnectorCredential, Platform, SocialAccount
from .connection_status import connection_summary
from .oauth import create_authorization_attempt
from .serializers import (
    ConnectorCredentialCreateSerializer, ConnectorCredentialListSerializer,
    ConnectorCredentialReadSerializer, ConnectorCredentialUpdateSerializer,
    PlatformListSerializer, PlatformSerializer, SocialAccountCreateSerializer,
    SocialAccountConnectionSerializer, SocialAccountListSerializer, SocialAccountReadSerializer,
    SocialAccountUpdateSerializer,
    PlatformAuthorizationRequestSerializer, PlatformAuthorizationResponseSerializer,
    PlatformConnectionListSerializer,
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


PLATFORM_CONNECTIONS = (
    ("LINKEDIN", "LinkedIn"),
    ("FACEBOOK", "Facebook"),
    ("INSTAGRAM", "Instagram"),
    ("TIKTOK", "TikTok"),
)


@extend_schema(tags=["PlatformConnections"])
class PlatformConnectionListView(APIView):
    permission_classes = [CanReadPublishing]

    @extend_schema(responses={200: PlatformConnectionListSerializer})
    def get(self, request: Request) -> Response:
        results = []
        for code, name in PLATFORM_CONNECTIONS:
            summary = connection_summary(
                organization=request.organization, platform_code=code,
            )
            results.append({
                "platform": code,
                "platform_name": name,
                "status": summary.status,
                "connection_label": summary.connection_label,
                "recovery_action": summary.recovery_action,
                "mode": summary.mode,
            })
        return Response({"results": results})


@extend_schema(tags=["PlatformConnections"])
class PlatformAuthorizationView(APIView):
    permission_classes = [CanManageCredentials]

    @extend_schema(
        request=PlatformAuthorizationRequestSerializer,
        responses={201: PlatformAuthorizationResponseSerializer},
    )
    def post(self, request: Request, platform_code: str) -> Response:
        try:
            platform = Platform.objects.get(code=platform_code)
        except Platform.DoesNotExist as error:
            raise Http404 from error
        if platform_code not in {code for code, _name in PLATFORM_CONNECTIONS}:
            raise Http404
        serializer = PlatformAuthorizationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider_key = "META" if platform_code in {"FACEBOOK", "INSTAGRAM"} else platform_code
        config = settings.SOCIAL_PROVIDER_CONFIG.get(provider_key, {})
        required = ("client_id", "authorization_url", "redirect_uri")
        if not config.get("enabled") or any(not config.get(field) for field in required):
            return Response({
                "code": "CONFIGURATION_REQUIRED",
                "message": "官方账号连接尚未配置。",
                "recovery_action": "由管理员完成平台应用配置后再连接",
                "detail": "Official platform authorization is disabled.",
            }, status=status.HTTP_409_CONFLICT)
        started = create_authorization_attempt(
            organization=request.organization,
            actor=request.user,
            platform=platform,
            return_path=serializer.validated_data["return_path"],
        )
        query = {
            "client_id": config["client_id"],
            "redirect_uri": config["redirect_uri"],
            "response_type": "code",
            "state": started.raw_state,
        }
        scopes = config.get("scopes", ())
        if scopes:
            query["scope"] = " ".join(scopes)
        authorization_url = f"{config['authorization_url']}?{urlencode(query)}"
        return Response({
            "status": "AUTHORIZATION_REQUIRED",
            "authorization_url": authorization_url,
            "expires_at": started.expires_at,
        }, status=status.HTTP_201_CREATED)
