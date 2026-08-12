from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.permissions import CanDecideDirector, CanReadDirector

from .models import DirectorProposal
from .selectors import cockpit_snapshot
from .serializers import (
    DirectorCockpitSerializer,
    DirectorConflictSerializer,
    DirectorDecisionRequestSerializer,
    DirectorDecisionResultSerializer,
    DirectorReadErrorSerializer,
    DirectorValidationErrorSerializer,
)
from .services import DirectorService, DirectorStateConflict, DirectorVersionConflict


def _validation(errors):
    return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)


def _conflict(code, detail):
    return Response({"code": code, "detail": detail}, status=status.HTTP_409_CONFLICT)


@extend_schema(tags=["Growth Director"])
class DirectorCockpitView(APIView):
    permission_classes = [CanReadDirector]

    @extend_schema(
        operation_id="director_cockpit_retrieve",
        responses={
            200: DirectorCockpitSerializer,
            401: DirectorReadErrorSerializer,
            403: DirectorReadErrorSerializer,
        },
    )
    def get(self, request):
        snapshot = cockpit_snapshot(
            organization=request.organization,
            permissions=request.membership.role.permissions,
            now=timezone.now(),
        )
        return Response(DirectorCockpitSerializer(snapshot).data)


@extend_schema(tags=["Growth Director"])
class DirectorProposalDecisionView(APIView):
    permission_classes = [CanDecideDirector]

    @extend_schema(
        operation_id="director_proposals_decisions_create",
        request=DirectorDecisionRequestSerializer,
        responses={
            200: DirectorDecisionResultSerializer,
            400: DirectorValidationErrorSerializer,
            401: DirectorReadErrorSerializer,
            403: DirectorReadErrorSerializer,
            404: DirectorReadErrorSerializer,
            409: DirectorConflictSerializer,
        },
    )
    def post(self, request, id):
        serializer = DirectorDecisionRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return _validation(serializer.errors)
        values = serializer.validated_data
        try:
            proposal = DirectorService.decide(
                organization=request.organization,
                proposal_id=id,
                expected_version=values["expected_version"],
                action=values["action"],
                actor=request.user,
                comment=values["comment"],
            )
        except DirectorProposal.DoesNotExist as error:
            raise Http404 from error
        except DirectorVersionConflict as error:
            return _conflict("director_version_conflict", str(error))
        except DirectorStateConflict as error:
            code = "director_expired" if "expired" in str(error).lower() else "director_state_conflict"
            return _conflict(code, str(error))
        except DjangoValidationError as error:
            if "comment" in getattr(error, "message_dict", {}):
                return _conflict("director_comment_required", "请填写调整或拒绝原因。")
            errors = getattr(error, "message_dict", {"non_field_errors": error.messages})
            return _validation(errors)
        return Response({"id": proposal.id, "status": proposal.status, "version": proposal.version})
