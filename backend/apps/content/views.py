from django.db import transaction
from django.db.models import Exists, OuterRef
from django.http import Http404
from drf_spectacular.utils import (
    OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_view,
)
from rest_framework import status
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai.models import PromptVersion
from apps.campaigns.models import ContentBrief, ContentBriefPlatform
from apps.campaigns.services import build_content_generation_input
from apps.common.openapi import bounded_integer_query_parameter
from apps.identity.permissions import CanManageContent, CanReadContent, CanReviewContent
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.platforms.models import Platform

from .models import MasterContent, PlatformContent
from .serializers import (
    EmptySerializer, JobAcceptedSerializer, MasterContentSerializer,
    MasterRevisionSerializer, PlatformContentSerializer,
    PlatformGenerationSerializer, PlatformRevisionSerializer, ReviewSerializer,
    ContentFilterSerializer,
)
from .services import (
    ContentStateError, create_master_revision, create_platform_content,
    create_platform_revision, transition_content, content_is_consistent,
)
from .tasks import generate_master_content_job


class ContentPagination(CursorPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50
    ordering = ("-created_at", "-id")


def _with_current_head(queryset, model):
    successors = model.objects.filter(
        organization_id=OuterRef("organization_id"),
        lineage_id=OuterRef("lineage_id"),
        previous_version_id=OuterRef("pk"),
    )
    return queryset.annotate(_is_current_head=~Exists(successors))


def _object(model, organization, pk):
    try:
        queryset = model.objects.select_related(
            *("brief", "generation_job", "ai_run", "previous_version")
            if model is MasterContent
            else (
                "master_content__brief", "master_content__generation_job",
                "master_content__ai_run", "master_content__previous_version",
                "platform", "previous_version", "growth_channel_package",
            )
        )
        if model is PlatformContent:
            queryset = queryset.annotate(
                _selected_platform=Exists(
                    ContentBriefPlatform.objects.filter(
                        brief_id=OuterRef("master_content__brief_id"),
                        platform_id=OuterRef("platform_id"),
                    )
                )
            )
        content = _with_current_head(queryset, model).get(
            pk=pk, organization=organization
        )
        if not content_is_consistent(content):
            raise Http404
        return content
    except (model.DoesNotExist, ValueError) as exc:
        raise Http404 from exc


def _error(exc, code="invalid_content_transition"):
    return Response(
        {"code": code, "message": str(exc), "recovery_action": "Refresh and retry."},
        status=status.HTTP_409_CONFLICT,
    )


class ContentListView(APIView):
    permission_classes = [CanReadContent]
    model = MasterContent
    serializer = MasterContentSerializer
    serializer_class = MasterContentSerializer

    @extend_schema(parameters=[
        OpenApiParameter("status", OpenApiTypes.STR),
        bounded_integer_query_parameter("page_size", minimum=1, maximum=50),
    ])
    def get(self, request):
        queryset = self.model.objects.filter(organization=request.organization)
        queryset = _with_current_head(queryset, self.model)
        if self.model is MasterContent:
            queryset = queryset.select_related(
                "brief", "generation_job", "ai_run", "previous_version"
            )
        else:
            queryset = queryset.select_related(
                "master_content__brief", "master_content__generation_job",
                "master_content__ai_run", "master_content__previous_version",
                "platform", "previous_version", "growth_channel_package",
            ).annotate(
                _selected_platform=Exists(
                    ContentBriefPlatform.objects.filter(
                        brief_id=OuterRef("master_content__brief_id"),
                        platform_id=OuterRef("platform_id"),
                    )
                )
            )
        repeated = {
            name: ["Provide this filter at most once."]
            for name in request.query_params
            if len(request.query_params.getlist(name)) > 1
        }
        serializer = ContentFilterSerializer(data=request.query_params)
        if repeated or not serializer.is_valid():
            errors = {**serializer.errors, **repeated}
            return Response({"errors": errors}, status=400)
        values = serializer.validated_data
        if "status" in values and values["status"] not in self.model.Status.values:
            return Response(
                {"errors": {"status": ["Select a valid choice."]}}, status=400
            )
        for key in ("status", "version"):
            if key in values:
                queryset = queryset.filter(**{key: values[key]})
        if "lineage" in values:
            queryset = queryset.filter(lineage_id=values["lineage"])
        prefix = "" if self.model is MasterContent else "master_content__"
        if "brief" in values:
            queryset = queryset.filter(**{f"{prefix}brief_id": values["brief"]})
        if "campaign" in values:
            queryset = queryset.filter(**{f"{prefix}brief__campaign_id": values["campaign"]})
        if "product" in values:
            queryset = queryset.filter(**{f"{prefix}brief__product_links__product_id": values["product"]})
        if "platform" in values:
            if self.model is PlatformContent:
                queryset = queryset.filter(platform_id=values["platform"])
            else:
                queryset = queryset.filter(brief__platform_links__platform_id=values["platform"])
        queryset = queryset.distinct()
        paginator = ContentPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        safe_page = [content for content in page if content_is_consistent(content)]
        return paginator.get_paginated_response(self.serializer(safe_page, many=True).data)


@extend_schema_view(get=extend_schema(operation_id="master_contents_list", tags=["MasterContents"]))
class MasterListView(ContentListView):
    pass


@extend_schema_view(get=extend_schema(operation_id="platform_contents_list", tags=["PlatformContents"]))
class PlatformListView(ContentListView):
    model = PlatformContent
    serializer = PlatformContentSerializer
    serializer_class = PlatformContentSerializer


class ContentDetailView(APIView):
    permission_classes = [CanReadContent]
    model = MasterContent
    serializer = MasterContentSerializer
    serializer_class = MasterContentSerializer

    def get(self, request, content_id):
        return Response(self.serializer(_object(self.model, request.organization, content_id)).data)


@extend_schema_view(get=extend_schema(operation_id="master_contents_retrieve", tags=["MasterContents"]))
class MasterDetailView(ContentDetailView):
    pass


@extend_schema_view(get=extend_schema(operation_id="platform_contents_retrieve", tags=["PlatformContents"]))
class PlatformDetailView(ContentDetailView):
    model = PlatformContent
    serializer = PlatformContentSerializer
    serializer_class = PlatformContentSerializer


@extend_schema(tags=["MasterContents"])
class MasterRevisionView(APIView):
    permission_classes = [CanManageContent]
    serializer_class = MasterRevisionSerializer

    @extend_schema(request=MasterRevisionSerializer, responses={201: MasterContentSerializer})
    def post(self, request, content_id):
        serializer = MasterRevisionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=400)
        source = _object(MasterContent, request.organization, content_id)
        try:
            revision = create_master_revision(
                source, actor=request.user, payload=serializer.validated_data["payload"]
            )
        except ContentStateError as exc:
            return _error(exc)
        return Response(MasterContentSerializer(revision).data, status=201)


@extend_schema(tags=["PlatformContents"])
class PlatformRevisionView(APIView):
    permission_classes = [CanManageContent]
    serializer_class = PlatformRevisionSerializer

    @extend_schema(request=PlatformRevisionSerializer, responses={201: PlatformContentSerializer})
    def post(self, request, content_id):
        serializer = PlatformRevisionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=400)
        source = _object(PlatformContent, request.organization, content_id)
        try:
            revision = create_platform_revision(
                source, actor=request.user, payload=serializer.validated_data["payload"]
            )
        except ContentStateError as exc:
            return _error(exc)
        return Response(PlatformContentSerializer(revision).data, status=201)


class ContentActionView(APIView):
    permission_classes = [CanReviewContent]
    model = MasterContent
    serializer = MasterContentSerializer
    action = ""
    serializer_class = ReviewSerializer

    @extend_schema(request=ReviewSerializer)
    def post(self, request, content_id):
        serializer = ReviewSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=400)
        content = _object(self.model, request.organization, content_id)
        try:
            content = transition_content(
                content, action=self.action, actor=request.user,
                comment=serializer.validated_data["comment"],
            )
        except ContentStateError as exc:
            return _error(exc)
        return Response(self.serializer(content).data)


@extend_schema(tags=["MasterContents"])
class MasterApproveView(ContentActionView):
    action = "APPROVE"


@extend_schema(tags=["MasterContents"])
class MasterRejectView(ContentActionView):
    action = "REJECT"


@extend_schema(tags=["MasterContents"])
class MasterArchiveView(ContentActionView):
    action = "ARCHIVE"


@extend_schema(tags=["MasterContents"])
class MasterSubmitView(ContentActionView):
    permission_classes = [CanManageContent]
    action = "SUBMIT"


class PlatformActionView(ContentActionView):
    model = PlatformContent
    serializer = PlatformContentSerializer


@extend_schema(tags=["PlatformContents"])
class PlatformApproveView(PlatformActionView):
    action = "APPROVE"


@extend_schema(tags=["PlatformContents"])
class PlatformRejectView(PlatformActionView):
    action = "REJECT"


@extend_schema(tags=["PlatformContents"])
class PlatformArchiveView(PlatformActionView):
    action = "ARCHIVE"


@extend_schema(tags=["PlatformContents"])
class PlatformSubmitView(PlatformActionView):
    permission_classes = [CanManageContent]
    action = "SUBMIT"


@extend_schema(tags=["MasterContents"])
class GeneratePlatformView(APIView):
    permission_classes = [CanManageContent]

    @extend_schema(request=PlatformGenerationSerializer, responses={201: PlatformContentSerializer})
    def post(self, request, content_id):
        serializer = PlatformGenerationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=400)
        master = _object(MasterContent, request.organization, content_id)
        try:
            platform = Platform.objects.get(pk=serializer.validated_data["platform_id"])
            content = create_platform_content(master, platform=platform, actor=request.user)
        except Platform.DoesNotExist as exc:
            raise Http404 from exc
        except ContentStateError as exc:
            return _error(exc)
        return Response(PlatformContentSerializer(content).data, status=201)


@extend_schema(tags=["ContentBriefs"])
class GenerateMasterView(APIView):
    permission_classes = [CanManageContent]

    @extend_schema(request=EmptySerializer, responses={202: JobAcceptedSerializer})
    def post(self, request, brief_id):
        serializer = EmptySerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=400)
        try:
            brief = ContentBrief.objects.get(pk=brief_id, organization=request.organization)
        except ContentBrief.DoesNotExist as exc:
            raise Http404 from exc
        if brief.status != ContentBrief.Status.READY:
            return _error(ContentStateError("Content brief must be READY."))
        prompt = PromptVersion.objects.filter(
            purpose="CONTENT_GENERATE", status=PromptVersion.Status.PUBLISHED
        ).order_by("-version").first()
        if prompt is None:
            return _error(ContentStateError("Published generation prompt is unavailable."))
        snapshot = build_content_generation_input(brief.id).to_dict()
        job = JobService.create(
            organization=request.organization,
            job_type=Job.Type.CONTENT_GENERATE,
            input_snapshot=snapshot,
            idempotency_key=f"master:{brief.id}:{brief.version}:{prompt.id}",
            created_by=request.user,
        )
        transaction.on_commit(
            lambda: generate_master_content_job.delay(str(job.id), str(prompt.id))
        )
        return Response({"job_id": job.id, "status": job.status}, status=202)
