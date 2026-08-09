from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db import IntegrityError
from django.http import Http404
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import ReviewAction
from apps.identity.permissions import (
    CanCreateKnowledge,
    CanDeprecateKnowledge,
    CanReadKnowledge,
    CanReviewOrganizationKnowledge,
    PermissionCode,
)
from apps.identity.services import require_permission

from .models import KnowledgeAlias, KnowledgeConcept, KnowledgeEvidence, KnowledgeRelation, KnowledgeStatus
from .serializers import (
    AliasResolutionSerializer,
    KnowledgeAliasListSerializer,
    KnowledgeAliasSerializer,
    KnowledgeConceptListSerializer,
    KnowledgeConceptSerializer,
    KnowledgeErrorSerializer,
    KnowledgeValidationErrorSerializer,
    KnowledgeEvidenceListSerializer,
    KnowledgeEvidenceSerializer,
    KnowledgeRelationListSerializer,
    KnowledgeRelationSerializer,
    RejectActionRequestSerializer,
    ResolveAliasRequestSerializer,
    ReviewActionRequestSerializer,
)
from .services import KnowledgeReviewService, KnowledgeStateError, OntologyContextService


ERROR_RESPONSES = {
    400: KnowledgeValidationErrorSerializer,
    403: KnowledgeErrorSerializer,
    404: KnowledgeErrorSerializer,
}


def _raise_validation_error(errors) -> None:
    normalized = {}
    for field, messages in errors.items():
        if isinstance(messages, (list, tuple)):
            normalized[field] = [str(message) for message in messages]
        else:
            normalized[field] = [str(messages)]
    raise serializers.ValidationError({"errors": normalized})


def _validate(serializer) -> None:
    if not serializer.is_valid():
        _raise_validation_error(serializer.errors)


def _save(serializer):
    try:
        return serializer.save()
    except serializers.ValidationError as error:
        details = error.detail
        if isinstance(details, dict) and set(details) == {"errors"}:
            raise
        _raise_validation_error(details if isinstance(details, dict) else {"detail": details})


def _can_manage_system(request: Request) -> bool:
    return PermissionCode.KNOWLEDGE_MANAGE_SYSTEM in request.membership.role.permissions


def _filter_review_visibility(request: Request, queryset):
    review_permissions = {
        PermissionCode.KNOWLEDGE_CREATE,
        PermissionCode.KNOWLEDGE_REVIEW_ORGANIZATION,
        PermissionCode.KNOWLEDGE_MANAGE_SYSTEM,
        PermissionCode.KNOWLEDGE_DEPRECATE,
    }
    if not review_permissions.intersection(request.membership.role.permissions):
        return queryset.filter(status=KnowledgeStatus.APPROVED)
    return queryset


@extend_schema(tags=["KnowledgeConcepts"])
class KnowledgeConceptListView(APIView):
    def get_permissions(self):
        return [(CanReadKnowledge if self.request.method == "GET" else CanCreateKnowledge)()]

    @extend_schema(operation_id="knowledge_concepts_list", responses={200: KnowledgeConceptListSerializer, 403: KnowledgeErrorSerializer})
    def get(self, request: Request) -> Response:
        queryset = _filter_review_visibility(
            request,
            OntologyContextService(request.organization).visible_concepts().prefetch_related("evidence"),
        )
        return Response({"results": KnowledgeConceptSerializer(queryset, many=True).data})

    @extend_schema(
        operation_id="knowledge_concepts_create",
        request=KnowledgeConceptSerializer,
        responses={201: KnowledgeConceptSerializer, **ERROR_RESPONSES},
    )
    def post(self, request: Request) -> Response:
        service = OntologyContextService(request.organization)
        serializer = KnowledgeConceptSerializer(
            data=request.data,
            context={
                "organization": request.organization,
                "actor": request.user,
                "allow_system": _can_manage_system(request),
                "service": service,
            },
        )
        _validate(serializer)
        concept = _save(serializer)
        return Response(KnowledgeConceptSerializer(concept).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["KnowledgeConcepts"])
class KnowledgeConceptDetailView(APIView):
    permission_classes = [CanReadKnowledge]

    @extend_schema(operation_id="knowledge_concepts_retrieve", responses={200: KnowledgeConceptSerializer, 403: KnowledgeErrorSerializer, 404: KnowledgeErrorSerializer})
    def get(self, request: Request, concept_id) -> Response:
        queryset = _filter_review_visibility(request, OntologyContextService(request.organization).visible_concepts())
        try:
            concept = queryset.get(id=concept_id)
        except KnowledgeConcept.DoesNotExist as error:
            raise Http404 from error
        return Response(KnowledgeConceptSerializer(concept).data)


@extend_schema(tags=["KnowledgeRelations"])
class KnowledgeRelationListView(APIView):
    def get_permissions(self):
        return [(CanReadKnowledge if self.request.method == "GET" else CanCreateKnowledge)()]

    @extend_schema(responses={200: KnowledgeRelationListSerializer, 403: KnowledgeErrorSerializer})
    def get(self, request: Request) -> Response:
        queryset = _filter_review_visibility(
            request,
            OntologyContextService(request.organization).visible_relations().prefetch_related("evidence"),
        )
        return Response({"results": KnowledgeRelationSerializer(queryset, many=True).data})

    @extend_schema(request=KnowledgeRelationSerializer, responses={201: KnowledgeRelationSerializer, **ERROR_RESPONSES})
    def post(self, request: Request) -> Response:
        service = OntologyContextService(request.organization)
        serializer = KnowledgeRelationSerializer(
            data=request.data,
            context={
                "organization": request.organization,
                "actor": request.user,
                "service": service,
                "allow_system": _can_manage_system(request),
            },
        )
        _validate(serializer)
        relation = _save(serializer)
        return Response(KnowledgeRelationSerializer(relation).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["KnowledgeAliases"])
class KnowledgeAliasListView(APIView):
    def get_permissions(self):
        return [(CanReadKnowledge if self.request.method == "GET" else CanCreateKnowledge)()]

    @extend_schema(responses={200: KnowledgeAliasListSerializer, 403: KnowledgeErrorSerializer})
    def get(self, request: Request) -> Response:
        queryset = _filter_review_visibility(request, OntologyContextService(request.organization).visible_aliases())
        return Response({"results": KnowledgeAliasSerializer(queryset, many=True).data})

    @extend_schema(request=KnowledgeAliasSerializer, responses={201: KnowledgeAliasSerializer, **ERROR_RESPONSES})
    def post(self, request: Request) -> Response:
        service = OntologyContextService(request.organization)
        serializer = KnowledgeAliasSerializer(
            data=request.data,
            context={
                "organization": request.organization,
                "actor": request.user,
                "service": service,
                "allow_system": _can_manage_system(request),
                "system_requested": request.data.get("scope") == KnowledgeConcept.Scope.SYSTEM,
            },
        )
        _validate(serializer)
        alias = _save(serializer)
        return Response(KnowledgeAliasSerializer(alias).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["KnowledgeEvidence"])
class KnowledgeEvidenceListView(APIView):
    def get_permissions(self):
        return [(CanReadKnowledge if self.request.method == "GET" else CanCreateKnowledge)()]

    @extend_schema(responses={200: KnowledgeEvidenceListSerializer, 403: KnowledgeErrorSerializer})
    def get(self, request: Request) -> Response:
        queryset = _filter_review_visibility(request, OntologyContextService(request.organization).visible_evidence())
        return Response({"results": KnowledgeEvidenceSerializer(queryset, many=True).data})

    @extend_schema(request=KnowledgeEvidenceSerializer, responses={201: KnowledgeEvidenceSerializer, **ERROR_RESPONSES})
    def post(self, request: Request) -> Response:
        serializer = KnowledgeEvidenceSerializer(
            data=request.data,
            context={
                "organization": request.organization,
                "actor": request.user,
                "allow_system": _can_manage_system(request),
            },
        )
        _validate(serializer)
        evidence = _save(serializer)
        return Response(KnowledgeEvidenceSerializer(evidence).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["KnowledgeConcepts"])
class ResolveAliasView(APIView):
    permission_classes = [CanReadKnowledge]

    @extend_schema(
        request=ResolveAliasRequestSerializer,
        responses={
            200: AliasResolutionSerializer,
            400: KnowledgeValidationErrorSerializer,
            403: KnowledgeErrorSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = ResolveAliasRequestSerializer(data=request.data)
        _validate(serializer)
        result = OntologyContextService(request.organization).resolve_alias(**serializer.validated_data)
        return Response(AliasResolutionSerializer(result).data)


SERIALIZER_BY_MODEL = {
    KnowledgeConcept: KnowledgeConceptSerializer,
    KnowledgeRelation: KnowledgeRelationSerializer,
    KnowledgeAlias: KnowledgeAliasSerializer,
    KnowledgeEvidence: KnowledgeEvidenceSerializer,
}


class KnowledgeReviewActionView(APIView):
    model = KnowledgeConcept
    action = ReviewAction.APPROVE

    def get_permissions(self):
        if self.action == ReviewAction.DEPRECATE:
            permission_class = CanDeprecateKnowledge
        elif self.action == ReviewAction.SUBMIT:
            permission_class = CanCreateKnowledge
        else:
            permission_class = CanReviewOrganizationKnowledge
        return [permission_class()]

    def post(self, request: Request, object_id=None, **kwargs) -> Response:
        object_id = object_id or next(value for key, value in kwargs.items() if key.endswith("_id"))
        request_serializer_class = RejectActionRequestSerializer if self.action == ReviewAction.REJECT else ReviewActionRequestSerializer
        request_serializer = request_serializer_class(data=request.data)
        _validate(request_serializer)
        service = OntologyContextService(request.organization)
        visible_map = {
            KnowledgeConcept: service.visible_concepts,
            KnowledgeRelation: service.visible_relations,
            KnowledgeAlias: service.visible_aliases,
            KnowledgeEvidence: service.visible_evidence,
        }
        try:
            instance = visible_map[self.model]().get(id=object_id)
        except self.model.DoesNotExist as error:
            raise Http404 from error
        if instance.organization_id is None:
            try:
                require_permission(membership=request.membership, permission=PermissionCode.KNOWLEDGE_MANAGE_SYSTEM)
            except DjangoPermissionDenied as error:
                raise PermissionDenied(str(error)) from error
        try:
            updated = KnowledgeReviewService(request.organization).transition(
                instance=instance,
                action=self.action,
                actor=request.user,
                comment=request_serializer.validated_data.get("comment", ""),
            )
        except IntegrityError:
            if self.model is KnowledgeAlias and self.action == ReviewAction.APPROVE:
                _raise_validation_error(
                    {
                        "alias": [
                            "An approved alias with this scope, language, and normalized value already exists."
                        ]
                    }
                )
            raise
        except (ValueError, KnowledgeStateError) as error:
            _raise_validation_error({"detail": [str(error)]})
        return Response(SERIALIZER_BY_MODEL[self.model](updated).data)


def review_action_view(*, model, action: str):
    serializer_class = SERIALIZER_BY_MODEL[model]
    request_serializer = RejectActionRequestSerializer if action == ReviewAction.REJECT else ReviewActionRequestSerializer
    view_class = type(
        f"{model.__name__}{action.title()}View",
        (KnowledgeReviewActionView,),
        {"model": model, "action": action},
    )
    tags = {
        KnowledgeConcept: ["KnowledgeConcepts"],
        KnowledgeRelation: ["KnowledgeRelations"],
        KnowledgeAlias: ["KnowledgeAliases"],
        KnowledgeEvidence: ["KnowledgeEvidence"],
    }[model]
    documented = extend_schema_view(
        post=extend_schema(
            request=request_serializer,
            responses={200: serializer_class, **ERROR_RESPONSES},
            tags=tags,
        )
    )(view_class)
    return documented.as_view()
