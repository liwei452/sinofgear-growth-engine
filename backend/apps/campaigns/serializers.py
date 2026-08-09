from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Campaign, ContentBrief, ContentBriefConceptLink
from .services import create_campaign, create_content_brief, update_content_brief


class StrictFieldsMixin:
    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: ["Unknown field."] for name in sorted(unknown)}
            )
        return super().to_internal_value(data)


class CampaignSerializer(serializers.ModelSerializer):
    product_ids = serializers.SerializerMethodField()

    @extend_schema_field(serializers.ListField(child=serializers.UUIDField()))
    def get_product_ids(self, campaign):
        links = getattr(campaign, "safe_product_links", campaign.product_links.all())
        return [link.product_id for link in links]

    class Meta:
        model = Campaign
        fields = [
            "id", "name", "description", "status", "version", "product_ids",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "version", "product_ids", "created_at", "updated_at"]


class CampaignCreateSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    product_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )

    class Meta:
        model = Campaign
        fields = ["name", "description", "status", "product_ids"]

    def create(self, validated_data):
        product_ids = validated_data.pop("product_ids", ())
        return create_campaign(
            organization=self.context["organization"],
            values=validated_data,
            product_ids=product_ids,
        )


class CampaignPatchSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = ["name", "description", "status"]


class ConceptLinkInputSerializer(StrictFieldsMixin, serializers.Serializer):
    role = serializers.ChoiceField(choices=ContentBriefConceptLink.Role.choices)
    concept_id = serializers.UUIDField()


class ContentBriefSerializer(serializers.ModelSerializer):
    campaign_id = serializers.UUIDField(read_only=True)
    product_ids = serializers.SerializerMethodField()
    asset_ids = serializers.SerializerMethodField()
    platform_ids = serializers.SerializerMethodField()
    concept_links = serializers.SerializerMethodField()

    @staticmethod
    def _ids(brief, attr, field):
        links = getattr(brief, attr)
        return [getattr(link, field) for link in links]

    @extend_schema_field(serializers.ListField(child=serializers.UUIDField()))
    def get_product_ids(self, brief):
        return self._ids(brief, "safe_product_links", "product_id")

    @extend_schema_field(serializers.ListField(child=serializers.UUIDField()))
    def get_asset_ids(self, brief):
        return self._ids(brief, "safe_asset_links", "asset_id")

    @extend_schema_field(serializers.ListField(child=serializers.UUIDField()))
    def get_platform_ids(self, brief):
        return self._ids(brief, "safe_platform_links", "platform_id")

    @extend_schema_field(ConceptLinkInputSerializer(many=True))
    def get_concept_links(self, brief):
        return [
            {"role": link.role, "concept_id": link.concept_id}
            for link in brief.safe_concept_links
        ]

    class Meta:
        model = ContentBrief
        fields = [
            "id", "campaign_id", "previous_version_id", "version", "status",
            "target_country", "customer_type", "content_objective", "cta",
            "landing_page_url", "language", "prohibited_claims", "selling_points",
            "advantages", "keywords", "product_ids", "asset_ids", "platform_ids",
            "concept_links", "created_by", "reviewed_by", "reviewed_at", "created_at",
            "updated_at",
        ]
        read_only_fields = fields


BRIEF_VALUE_FIELDS = [
    "target_country", "customer_type", "content_objective", "cta",
    "landing_page_url", "language", "prohibited_claims", "selling_points",
    "advantages", "keywords",
]


class ContentBriefCreateSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    campaign_id = serializers.UUIDField()
    product_ids = serializers.ListField(child=serializers.UUIDField())
    asset_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    platform_ids = serializers.ListField(child=serializers.UUIDField())
    concept_links = ConceptLinkInputSerializer(many=True, required=False, default=list)

    class Meta:
        model = ContentBrief
        fields = ["campaign_id", *BRIEF_VALUE_FIELDS, "product_ids", "asset_ids", "platform_ids", "concept_links"]

    def create(self, validated_data):
        organization = self.context["organization"]
        try:
            campaign = Campaign.objects.get(
                pk=validated_data.pop("campaign_id"), organization=organization
            )
        except Campaign.DoesNotExist as error:
            raise serializers.ValidationError({"campaign_id": ["Campaign does not exist."]}) from error
        relations = {
            key: validated_data.pop(key)
            for key in ("product_ids", "asset_ids", "platform_ids", "concept_links")
        }
        return create_content_brief(
            organization=organization,
            campaign=campaign,
            creator=self.context["creator"],
            values=validated_data,
            **relations,
        )


class ContentBriefPatchSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    product_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    asset_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    platform_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    concept_links = ConceptLinkInputSerializer(many=True, required=False)

    class Meta:
        model = ContentBrief
        fields = [
            *BRIEF_VALUE_FIELDS,
            "product_ids", "asset_ids", "platform_ids", "concept_links",
        ]

    def update(self, instance, validated_data):
        relations = {
            key: validated_data.pop(key)
            for key in ("product_ids", "asset_ids", "platform_ids", "concept_links")
            if key in validated_data
        }
        return update_content_brief(
            instance.id, values=validated_data, **relations
        )


class CampaignFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Campaign.Status.choices, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=50, required=False)
    cursor = serializers.CharField(required=False)


class ContentBriefFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ContentBrief.Status.choices, required=False)
    campaign = serializers.UUIDField(required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=50, required=False)
    cursor = serializers.CharField(required=False)


class ValidationErrorSerializer(serializers.Serializer):
    errors = serializers.DictField()


class ErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()


class CampaignListSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = CampaignSerializer(many=True)


class ContentBriefListSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = ContentBriefSerializer(many=True)
