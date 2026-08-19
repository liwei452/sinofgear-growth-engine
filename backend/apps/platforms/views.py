from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.http import Http404, HttpResponseRedirect
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.permissions import CanManageCredentials, CanReadMemberships, CanReadPublishing
from integrations.platforms.authorization import (
    AuthorizationCompletion,
    ProviderAuthorizationError,
)
from integrations.platforms.base import ConnectorConfigurationRequired
from integrations.platforms.runtime import get_social_provider_runtime
from integrations.platforms.token_store import TokenStoreContext

from .models import AccountConnectionSession, ConnectorCredential, Platform, SocialAccount
from .provider_connections import (
    BufferConnectionError,
    build_buffer_connector,
    connect_buffer,
    disconnect_buffer,
    get_buffer_connection,
    probe_buffer_connection,
    rotate_buffer_credential,
    sync_buffer_channels,
)
from .lifecycle import (
    LifecycleAdapterRegistry,
    ProviderLifecycleError,
    disconnect_social_account,
    probe_social_account,
    start_reauthorization,
)
from .connection_status import connection_summary
from .connection_sessions import (
    ConnectionCandidate,
    ConnectionSessionInvalid,
    confirm_connection_session,
    create_connection_session,
    get_connection_session,
)
from .oauth import (
    AuthorizationAttemptInvalid,
    consume_authorization_attempt,
    create_authorization_attempt,
)
from .serializers import (
    ConnectorCredentialCreateSerializer, ConnectorCredentialListSerializer,
    ConnectorCredentialReadSerializer, ConnectorCredentialUpdateSerializer,
    PlatformListSerializer, PlatformSerializer, SocialAccountCreateSerializer,
    SocialAccountConnectionSerializer, SocialAccountListSerializer, SocialAccountReadSerializer,
    SocialAccountUpdateSerializer,
    PlatformAuthorizationRequestSerializer, PlatformAuthorizationResponseSerializer,
    PlatformConnectionListSerializer,
    AccountConnectionConfirmationResponseSerializer,
    AccountConnectionConfirmationSerializer, AccountConnectionSessionSerializer,
    PlatformAuthorizationCallbackSerializer,
    SocialAccountDisconnectSerializer, SocialAccountLifecycleSerializer,
    BufferProviderConnectionCreateSerializer,
    BufferProviderConnectionDisconnectSerializer,
    BufferProviderConnectionReadSerializer,
    BufferProviderConnectionRotateSerializer,
    BufferProviderConnectionSyncSerializer,
)


_social_runtime = get_social_provider_runtime()
authorization_registry = _social_runtime.authorization_registry
connection_token_store = _social_runtime.token_store
lifecycle_registry = LifecycleAdapterRegistry()
lifecycle_token_store = _social_runtime.token_store
buffer_token_store = _social_runtime.token_store


def buffer_connector_factory():
    return build_buffer_connector(buffer_token_store)


def _account(organization, account_id):
    try:
        return SocialAccount.objects.select_related("platform", "credential", "provider_connection").get(
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
            "platform", "credential", "provider_connection"
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


def _lifecycle_error(error: Exception) -> Response:
    return Response({
        "code": getattr(error, "code", "PROVIDER_UNAVAILABLE"),
        "message": "官方渠道暂时不可用，请稍后重试或重新授权。",
    }, status=status.HTTP_409_CONFLICT)


@extend_schema(tags=["SocialAccounts"])
class SocialAccountProbeView(APIView):
    permission_classes = [CanManageCredentials]

    @extend_schema(responses={200: SocialAccountLifecycleSerializer})
    def post(self, request: Request, account_id) -> Response:
        account = _account(request.organization, account_id)
        try:
            adapter = lifecycle_registry.resolve(account.platform.code)
            account = probe_social_account(
                account=account, adapter=adapter, token_store=lifecycle_token_store,
                actor=request.user,
            )
        except (ProviderLifecycleError, ConnectorConfigurationRequired) as error:
            return _lifecycle_error(error)
        return Response(SocialAccountLifecycleSerializer(account).data)


@extend_schema(tags=["SocialAccounts"])
class SocialAccountReauthorizationView(APIView):
    permission_classes = [CanManageCredentials]

    @extend_schema(responses={200: SocialAccountLifecycleSerializer})
    def post(self, request: Request, account_id) -> Response:
        account = _account(request.organization, account_id)
        try:
            account = start_reauthorization(account=account, actor=request.user)
        except ProviderLifecycleError as error:
            return _lifecycle_error(error)
        data = SocialAccountLifecycleSerializer(account).data
        data["authorization_path"] = (
            f"/api/v1/platform-connections/{account.platform.code}/authorize"
        )
        return Response(data)


class _UnavailableLifecycleAdapter:
    def revoke(self, token):
        del token
        raise ProviderLifecycleError("CONFIGURATION_REQUIRED")


@extend_schema(tags=["SocialAccounts"])
class SocialAccountDisconnectView(APIView):
    permission_classes = [CanManageCredentials]

    @extend_schema(
        request=SocialAccountDisconnectSerializer,
        responses={200: SocialAccountLifecycleSerializer},
    )
    def post(self, request: Request, account_id) -> Response:
        serializer = SocialAccountDisconnectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not serializer.validated_data["confirm"]:
            return Response({
                "code": "DISCONNECT_CONFIRMATION_REQUIRED",
                "message": "请明确确认后再断开连接。",
            }, status=status.HTTP_400_BAD_REQUEST)
        account = _account(request.organization, account_id)
        try:
            adapter = lifecycle_registry.resolve(account.platform.code)
        except ProviderLifecycleError:
            adapter = _UnavailableLifecycleAdapter()
        account = disconnect_social_account(
            account=account, adapter=adapter, token_store=lifecycle_token_store,
            actor=request.user, confirmed=True,
        )
        return Response(SocialAccountLifecycleSerializer(account).data)


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
    ("YOUTUBE", "YouTube"),
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
                "account_id": summary.account_id,
                "publication_mode": _social_runtime.readiness.get(code).publication_mode
                if _social_runtime.readiness.get(code) else "UNAVAILABLE",
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


def _platform_or_404(platform_code: str) -> Platform:
    if platform_code not in {code for code, _name in PLATFORM_CONNECTIONS}:
        raise Http404
    try:
        return Platform.objects.get(code=platform_code)
    except Platform.DoesNotExist as error:
        raise Http404 from error


def _safe_callback_redirect(return_path: str, **values: str) -> str:
    parsed = urlsplit(return_path)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(values)
    return urlunsplit(("", "", parsed.path, urlencode(query), ""))


@extend_schema(tags=["PlatformConnections"])
class PlatformAuthorizationCallbackView(APIView):
    permission_classes = [CanManageCredentials]

    @extend_schema(responses={302: None})
    def get(self, request: Request, platform_code: str):
        platform = _platform_or_404(platform_code)
        serializer = PlatformAuthorizationCallbackSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        provider_key = "META" if platform_code in {"FACEBOOK", "INSTAGRAM"} else platform_code
        config = settings.SOCIAL_PROVIDER_CONFIG.get(provider_key, {})
        if not config.get("enabled") or not config.get("redirect_uri"):
            return Response({
                "code": "CONFIGURATION_REQUIRED",
                "message": "官方账号连接尚未配置。",
            }, status=status.HTTP_409_CONFLICT)
        try:
            attempt = consume_authorization_attempt(
                raw_state=serializer.validated_data["state"],
                actor=request.user,
                platform_code=platform_code,
            )
        except AuthorizationAttemptInvalid:
            return Response({
                "code": "AUTHORIZATION_REJECTED",
                "message": "授权未完成，请重新连接。",
            }, status=status.HTTP_400_BAD_REQUEST)
        if serializer.validated_data.get("error"):
            return HttpResponseRedirect(_safe_callback_redirect(
                attempt.return_path, connection_status="authorization_rejected",
            ))
        try:
            adapter = authorization_registry.resolve(platform_code)
            bundle, managed_accounts, granted_capabilities = adapter.complete(
                AuthorizationCompletion(
                    code=serializer.validated_data["code"],
                    redirect_uri=config["redirect_uri"],
                    pkce_reference=attempt.pkce_verifier_reference,
                )
            )
            bundle_reference = connection_token_store.store(
                bundle,
                TokenStoreContext(
                    organization_id=request.organization.id,
                    actor_id=request.user.id,
                    platform_code=platform_code,
                    attempt_id=attempt.id,
                ),
            )
            try:
                session = create_connection_session(
                    organization=request.organization,
                    actor=request.user,
                    platform=platform,
                    secret_reference=bundle_reference,
                    credential_expires_at=bundle.primary.expires_at,
                    candidates=[ConnectionCandidate(
                        candidate_id=item.candidate_id,
                        external_id=item.external_id,
                        display_name=item.display_name,
                        channel=item.channel,
                        capabilities=item.capabilities,
                        publication_mode=item.publication_mode,
                        discovered_at=item.discovered_at,
                    ) for item in managed_accounts],
                    granted_capabilities=list(granted_capabilities),
                )
            except Exception:
                connection_token_store.delete(bundle_reference)
                raise
        except (ConnectorConfigurationRequired, ProviderAuthorizationError, ValueError) as error:
            error_code = getattr(error, "code", "CONFIGURATION_REQUIRED")
            return HttpResponseRedirect(_safe_callback_redirect(
                attempt.return_path,
                connection_status=str(error_code).lower(),
            ))
        return HttpResponseRedirect(_safe_callback_redirect(
            attempt.return_path,
            connection_session=str(session.id),
            connection_status="ready",
        ))


def _session_or_404(request: Request, session_id) -> AccountConnectionSession:
    session = AccountConnectionSession.objects.filter(
        pk=session_id,
        organization=request.organization,
        actor=request.user,
    ).select_related("platform").first()
    if session is None:
        raise Http404
    return session


def _safe_candidate(item: dict) -> dict:
    publication_mode = item.get("publication_mode")
    return {
        "candidate_id": item.get("candidate_id"),
        "display_name": item.get("display_name"),
        "channel": item.get("channel"),
        "capability_label": "仅私密发布" if publication_mode == "PRIVATE_ONLY" else "可发布",
        "publication_mode": publication_mode,
    }


@extend_schema(tags=["PlatformConnections"])
class AccountConnectionSessionView(APIView):
    permission_classes = [CanManageCredentials]

    @extend_schema(responses={200: AccountConnectionSessionSerializer})
    def get(self, request: Request, session_id):
        session = _session_or_404(request, session_id)
        try:
            session = get_connection_session(
                session_id=session.id,
                organization=request.organization,
                actor=request.user,
            )
        except ConnectionSessionInvalid as error:
            return Response({
                "code": str(error),
                "message": "连接已超时，请重新连接。",
            }, status=status.HTTP_410_GONE)
        return Response({
            "id": session.id,
            "platform": session.platform.code,
            "platform_name": session.platform.name,
            "expires_at": session.expires_at,
            "candidates": [_safe_candidate(item) for item in session.candidates],
        })


@extend_schema(tags=["PlatformConnections"])
class AccountConnectionConfirmationView(APIView):
    permission_classes = [CanManageCredentials]

    @extend_schema(
        request=AccountConnectionConfirmationSerializer,
        responses={200: AccountConnectionConfirmationResponseSerializer},
    )
    def post(self, request: Request, session_id):
        serializer = AccountConnectionConfirmationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = _session_or_404(request, session_id)
        candidate_id = str(serializer.validated_data["candidate_id"])
        candidate = next((
            item for item in session.candidates
            if isinstance(item, dict) and item.get("candidate_id") == candidate_id
        ), None)
        if candidate is None:
            return Response({
                "code": "CANDIDATE_NOT_FOUND",
                "message": "该发布账号已不可用，请重新连接。",
            }, status=status.HTTP_400_BAD_REQUEST)
        bound_reference = session.secret_reference
        did_bind = False
        try:
            if session.consumed_at is None:
                bound_reference = connection_token_store.bind(
                    session.secret_reference, candidate_id,
                )
                did_bind = True
            account = confirm_connection_session(
                session=session,
                candidate_id=candidate_id,
                credential_reference=bound_reference,
            )
        except (ConnectorConfigurationRequired, ConnectionSessionInvalid) as error:
            if did_bind:
                connection_token_store.delete(bound_reference)
            return Response({
                "code": getattr(error, "code", str(error)),
                "message": "账号连接暂时无法完成，请重新连接。",
            }, status=status.HTTP_409_CONFLICT)
        summary = connection_summary(
            organization=request.organization,
            platform_code=account.platform.code,
        )
        return Response({
            "platform": account.platform.code,
            "status": summary.status,
            "connection_label": summary.connection_label,
            "recovery_action": summary.recovery_action,
            "mode": summary.mode,
        })


def _buffer_error_response(error: BufferConnectionError) -> Response:
    return Response(
        {"code": error.code, "message": error.message},
        status=error.http_status,
    )


@extend_schema(tags=["BufferProviderConnection"])
class BufferProviderConnectionView(APIView):
    permission_classes = [IsAuthenticated, CanManageCredentials]

    @extend_schema(responses={200: BufferProviderConnectionReadSerializer})
    def get(self, request: Request) -> Response:
        try:
            connection = get_buffer_connection(request.organization)
        except BufferConnectionError as error:
            return _buffer_error_response(error)
        return Response(BufferProviderConnectionReadSerializer(connection).data)

    @extend_schema(
        request=BufferProviderConnectionCreateSerializer,
        responses={201: BufferProviderConnectionReadSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = BufferProviderConnectionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            connection = connect_buffer(
                organization=request.organization,
                actor=request.user,
                api_key=serializer.validated_data["api_key"],
                organization_id=serializer.validated_data["organization_id"],
                token_store=buffer_token_store,
                connector=buffer_connector_factory(),
            )
        except BufferConnectionError as error:
            return _buffer_error_response(error)
        return Response(
            BufferProviderConnectionReadSerializer(connection).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=BufferProviderConnectionRotateSerializer,
        responses={200: BufferProviderConnectionReadSerializer},
    )
    def patch(self, request: Request) -> Response:
        serializer = BufferProviderConnectionRotateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            connection = rotate_buffer_credential(
                organization=request.organization,
                actor=request.user,
                api_key=serializer.validated_data["api_key"],
                token_store=buffer_token_store,
                connector=buffer_connector_factory(),
            )
        except BufferConnectionError as error:
            return _buffer_error_response(error)
        return Response(BufferProviderConnectionReadSerializer(connection).data)


@extend_schema(tags=["BufferProviderConnection"])
class BufferProviderConnectionProbeView(APIView):
    permission_classes = [IsAuthenticated, CanManageCredentials]

    @extend_schema(request=None, responses={200: BufferProviderConnectionReadSerializer})
    def post(self, request: Request) -> Response:
        try:
            connection = probe_buffer_connection(
                organization=request.organization,
                actor=request.user,
                connector=buffer_connector_factory(),
            )
        except BufferConnectionError as error:
            return _buffer_error_response(error)
        return Response(BufferProviderConnectionReadSerializer(connection).data)


@extend_schema(tags=["BufferProviderConnection"])
class BufferProviderConnectionSyncView(APIView):
    permission_classes = [IsAuthenticated, CanManageCredentials]

    @extend_schema(request=None, responses={200: BufferProviderConnectionSyncSerializer})
    def post(self, request: Request) -> Response:
        try:
            result = sync_buffer_channels(
                organization=request.organization,
                actor=request.user,
                connector=buffer_connector_factory(),
            )
        except BufferConnectionError as error:
            return _buffer_error_response(error)
        data = {
            "created_count": result.created_count,
            "updated_count": result.updated_count,
            "disconnected_count": result.disconnected_count,
            "ignored_channels": [
                {
                    "provider_account_id": item.provider_account_id,
                    "service": item.service,
                    "reason": item.reason,
                }
                for item in result.ignored_channels
            ],
            "synced_at": result.synced_at,
        }
        return Response(data)


@extend_schema(tags=["BufferProviderConnection"])
class BufferProviderConnectionDisconnectView(APIView):
    permission_classes = [IsAuthenticated, CanManageCredentials]

    @extend_schema(
        request=BufferProviderConnectionDisconnectSerializer,
        responses={200: BufferProviderConnectionReadSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = BufferProviderConnectionDisconnectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not serializer.validated_data["confirm"]:
            return Response({
                "code": "DISCONNECT_CONFIRMATION_REQUIRED",
                "message": "请明确确认后再断开连接。",
            }, status=status.HTTP_400_BAD_REQUEST)
        try:
            connection = disconnect_buffer(
                organization=request.organization,
                actor=request.user,
                token_store=buffer_token_store,
            )
        except BufferConnectionError as error:
            return _buffer_error_response(error)
        return Response(BufferProviderConnectionReadSerializer(connection).data)
