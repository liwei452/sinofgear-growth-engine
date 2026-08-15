from django.db.models import Q
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.knowledge.models import KnowledgeConcept

from .models import (
    ROLE_CONCEPT_TYPES,
    Product,
    ProductConceptLink,
    compatible_link_types_q,
)
from .services import create_product, update_product


class ProductConceptSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeConcept
        fields = ["id", "code", "concept_type", "label_zh", "label_en", "version"]


class ProductConceptLinkSerializer(serializers.ModelSerializer):
    concept = ProductConceptSummarySerializer(read_only=True)

    class Meta:
        model = ProductConceptLink
        fields = ["id", "role", "version", "concept"]


class ProductConceptLinkInputSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=ProductConceptLink.Role.choices)
    concept_id = serializers.UUIDField()

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        organization = self.context["organization"]
        try:
            concept = KnowledgeConcept.objects.filter(
                Q(organization__isnull=True) | Q(organization=organization),
                status=KnowledgeConcept.Status.APPROVED,
            ).get(pk=attrs["concept_id"])
        except KnowledgeConcept.DoesNotExist as error:
            raise serializers.ValidationError(
                {"concept_id": "Approved concept does not exist."}
            ) from error
        role = attrs["role"]
        if concept.concept_type not in ROLE_CONCEPT_TYPES[role]:
            raise serializers.ValidationError(
                {"concept_id": f"Concept type is not compatible with the {role} product role."}
            )
        return attrs


PRODUCT_FIELDS = [
    "name_zh",
    "name_en",
    "module_min",
    "module_max",
    "tooth_count_min",
    "tooth_count_max",
    "pressure_angle",
    "accuracy_grade",
    "heat_treatment",
    "surface_treatment",
    "manufacturing_capabilities",
    "inspection_capabilities",
    "moq",
    "lead_time",
    "landing_page_url",
    "status",
    "internal_notes",
]


class ProductSerializer(serializers.ModelSerializer):
    concept_links = serializers.SerializerMethodField()
    verified_fact_count = serializers.IntegerField(read_only=True, default=0)

    @extend_schema_field(ProductConceptLinkSerializer(many=True))
    def get_concept_links(self, product: Product) -> list[dict[str, object]]:
        links = getattr(product, "active_concept_links", None)
        if links is None:
            links = list(
                ProductConceptLink.objects.active()
                .filter(
                    product=product,
                    organization_id=product.organization_id,
                    product__organization_id=product.organization_id,
                    concept__status=KnowledgeConcept.Status.APPROVED,
                )
                .filter(
                    Q(concept__organization__isnull=True)
                    | Q(concept__organization_id=product.organization_id)
                )
                .filter(compatible_link_types_q())
                .select_related("concept")
                .order_by("role", "concept__code", "id")
            )
        links = [
            link
            for link in links
            if (
                link.retired_at is None
                and link.product_id == product.id
                and link.organization_id == product.organization_id
                and link.concept.organization_id in {None, product.organization_id}
                and link.concept.status == KnowledgeConcept.Status.APPROVED
                and link.concept.concept_type in ROLE_CONCEPT_TYPES.get(link.role, ())
            )
        ]
        return ProductConceptLinkSerializer(links, many=True).data

    class Meta:
        model = Product
        fields = [
            "id",
            "organization",
            *PRODUCT_FIELDS,
            "version",
            "concept_links",
            "verified_fact_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ProductListSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = ProductSerializer(many=True)


class ProductCreateSerializer(serializers.ModelSerializer):
    concept_links = ProductConceptLinkInputSerializer(many=True, required=False)

    class Meta:
        model = Product
        fields = [*PRODUCT_FIELDS, "concept_links"]

    def create(self, validated_data: dict[str, object]) -> Product:
        concept_links = validated_data.pop("concept_links", [])
        return create_product(
            organization=self.context["organization"],
            values=validated_data,
            concept_links=concept_links,
        )


class ProductPatchSerializer(serializers.ModelSerializer):
    concept_links = ProductConceptLinkInputSerializer(many=True, required=False)

    class Meta:
        model = Product
        fields = [*PRODUCT_FIELDS, "concept_links"]

    def update(self, instance: Product, validated_data: dict[str, object]) -> Product:
        return update_product(product=instance, values=validated_data)


class ProductFilterSerializer(serializers.Serializer):
    type = serializers.CharField(required=False, allow_blank=False)
    material = serializers.CharField(required=False, allow_blank=False)
    application = serializers.CharField(required=False, allow_blank=False)
    status = serializers.ChoiceField(choices=Product.Status.choices, required=False)
    cursor = serializers.CharField(required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=50, required=False)


class ProductErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()


class ProductValidationErrorSerializer(serializers.Serializer):
    errors = serializers.DictField()


class ProductPreconditionErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    detail = serializers.CharField()


class ProductVersionConflictSerializer(serializers.Serializer):
    code = serializers.CharField()
    current_version = serializers.IntegerField(min_value=1)
