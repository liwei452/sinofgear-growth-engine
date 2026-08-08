from django.db import IntegrityError
from rest_framework import serializers

from .models import KnowledgeAlias, KnowledgeConcept, KnowledgeEvidence, KnowledgeRelation
from .relation_rules import RelationRuleError
from .services import AliasResolution, KnowledgeRelationService


class KnowledgeConceptSerializer(serializers.ModelSerializer):
    scope = serializers.ChoiceField(
        choices=KnowledgeConcept.Scope.choices,
        required=False,
        default=KnowledgeConcept.Scope.ORGANIZATION,
    )
    evidence = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=KnowledgeEvidence.objects.none(),
        required=False,
    )

    class Meta:
        model = KnowledgeConcept
        fields = [
            "id", "scope", "organization", "concept_type", "code", "label_zh", "label_en", "description",
            "status", "version", "suggested_by_ai_run_id", "evidence", "created_by", "reviewed_by", "reviewed_at",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "organization", "status", "version", "created_by", "reviewed_by", "reviewed_at",
            "created_at", "updated_at",
        ]

    def validate_scope(self, value: str) -> str:
        if value == KnowledgeConcept.Scope.SYSTEM and not self.context.get("allow_system", False):
            raise serializers.ValidationError("SYSTEM knowledge requires the system-management permission.")
        return value

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        service = self.context.get("service")
        if service is not None:
            self.fields["evidence"].child_relation.queryset = service.visible_evidence()

    def create(self, validated_data: dict[str, object]) -> KnowledgeConcept:
        scope = validated_data.pop("scope", KnowledgeConcept.Scope.ORGANIZATION)
        evidence = validated_data.pop("evidence", [])
        organization = None if scope == KnowledgeConcept.Scope.SYSTEM else self.context["organization"]
        if organization is None and any(item.organization_id is not None for item in evidence):
            raise serializers.ValidationError({"evidence": "SYSTEM concepts may link only SYSTEM evidence."})
        try:
            concept = KnowledgeConcept.objects.create(
                scope=scope,
                organization=organization,
                status=KnowledgeConcept.Status.SUGGESTED,
                created_by=self.context["actor"],
                **validated_data,
            )
            concept.evidence.set(evidence)
            return concept
        except IntegrityError as error:
            raise serializers.ValidationError({"code": "A concept with this scoped type and code already exists."}) from error


class KnowledgeConceptListSerializer(serializers.Serializer):
    results = KnowledgeConceptSerializer(many=True)


class KnowledgeAliasSerializer(serializers.ModelSerializer):
    normalized_alias = serializers.CharField(read_only=True)

    class Meta:
        model = KnowledgeAlias
        fields = [
            "id", "organization", "concept", "language", "alias", "normalized_alias", "alias_type", "status",
            "version", "suggested_by_ai_run_id", "created_by", "reviewed_by", "reviewed_at", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "organization", "normalized_alias", "status", "version", "created_by", "reviewed_by",
            "reviewed_at", "created_at", "updated_at",
        ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        service = self.context.get("service")
        if service is not None:
            self.fields["concept"].queryset = service.visible_concepts()

    def create(self, validated_data: dict[str, object]) -> KnowledgeAlias:
        concept = validated_data["concept"]
        organization = None if self.context.get("allow_system", False) and concept.organization_id is None and self.context.get("system_requested") else self.context["organization"]
        alias = KnowledgeAlias(
            organization=organization,
            status=KnowledgeAlias.Status.SUGGESTED,
            created_by=self.context["actor"],
            **validated_data,
        )
        alias.clean()
        alias.save()
        return alias


class KnowledgeAliasListSerializer(serializers.Serializer):
    results = KnowledgeAliasSerializer(many=True)


class KnowledgeRelationSerializer(serializers.ModelSerializer):
    scope = serializers.ChoiceField(
        choices=KnowledgeConcept.Scope.choices,
        write_only=True,
        required=False,
        default=KnowledgeConcept.Scope.ORGANIZATION,
    )
    evidence = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=KnowledgeEvidence.objects.none(),
        required=False,
    )

    class Meta:
        model = KnowledgeRelation
        fields = [
            "id", "scope", "organization", "subject_concept", "predicate", "object_concept", "status", "confidence",
            "version", "suggested_by_ai_run_id", "evidence", "created_by", "reviewed_by", "reviewed_at", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "organization", "status", "version", "created_by", "reviewed_by", "reviewed_at",
            "created_at", "updated_at",
        ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        service = self.context.get("service")
        if service is not None:
            visible = service.visible_concepts()
            self.fields["subject_concept"].queryset = visible
            self.fields["object_concept"].queryset = visible
            self.fields["evidence"].child_relation.queryset = service.visible_evidence()

    def validate_scope(self, value: str) -> str:
        if value == KnowledgeConcept.Scope.SYSTEM and not self.context.get("allow_system", False):
            raise serializers.ValidationError("SYSTEM knowledge requires the system-management permission.")
        return value

    def create(self, validated_data: dict[str, object]) -> KnowledgeRelation:
        subject = validated_data.pop("subject_concept")
        object_ = validated_data.pop("object_concept")
        scope = validated_data.pop("scope")
        evidence = validated_data.pop("evidence", [])
        if scope == KnowledgeConcept.Scope.SYSTEM and any(item.organization_id is not None for item in evidence):
            raise serializers.ValidationError({"evidence": "SYSTEM relations may link only SYSTEM evidence."})
        try:
            relation = KnowledgeRelationService(self.context["organization"]).create(
                subject=subject,
                object=object_,
                status=KnowledgeRelation.Status.SUGGESTED,
                created_by=self.context["actor"],
                scope=scope,
                **validated_data,
            )
            relation.evidence.set(evidence)
            return relation
        except (RelationRuleError, IntegrityError) as error:
            raise serializers.ValidationError({"relation": str(error)}) from error


class KnowledgeRelationListSerializer(serializers.Serializer):
    results = KnowledgeRelationSerializer(many=True)


class KnowledgeEvidenceSerializer(serializers.ModelSerializer):
    scope = serializers.ChoiceField(
        choices=KnowledgeConcept.Scope.choices,
        write_only=True,
        required=False,
        default=KnowledgeConcept.Scope.ORGANIZATION,
    )

    class Meta:
        model = KnowledgeEvidence
        fields = [
            "id", "scope", "organization", "evidence_type", "source_object_type", "source_object_id", "source_url",
            "excerpt", "captured_at", "status", "version", "suggested_by_ai_run_id", "created_by", "reviewed_by",
            "reviewed_at", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "organization", "status", "version", "created_by", "reviewed_by", "reviewed_at",
            "created_at", "updated_at",
        ]

    def validate_scope(self, value: str) -> str:
        if value == KnowledgeConcept.Scope.SYSTEM and not self.context.get("allow_system", False):
            raise serializers.ValidationError("SYSTEM knowledge requires the system-management permission.")
        return value

    def create(self, validated_data: dict[str, object]) -> KnowledgeEvidence:
        scope = validated_data.pop("scope")
        return KnowledgeEvidence.objects.create(
            organization=None if scope == KnowledgeConcept.Scope.SYSTEM else self.context["organization"],
            status=KnowledgeEvidence.Status.SUGGESTED,
            created_by=self.context["actor"],
            **validated_data,
        )


class KnowledgeEvidenceListSerializer(serializers.Serializer):
    results = KnowledgeEvidenceSerializer(many=True)


class ResolveAliasRequestSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=255, allow_blank=False)
    language = serializers.CharField(max_length=16, allow_blank=False)


class ConceptMatchSerializer(serializers.Serializer):
    concept_id = serializers.UUIDField()
    code = serializers.CharField()
    concept_type = serializers.CharField()
    scope = serializers.CharField()
    label_zh = serializers.CharField()
    label_en = serializers.CharField()


class AliasResolutionSerializer(serializers.Serializer):
    ambiguous = serializers.BooleanField()
    selected = ConceptMatchSerializer(allow_null=True)
    candidates = ConceptMatchSerializer(many=True)

    def to_representation(self, instance: AliasResolution) -> dict[str, object]:
        return super().to_representation(instance)


class ReviewActionRequestSerializer(serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class RejectActionRequestSerializer(serializers.Serializer):
    comment = serializers.CharField(allow_blank=False, trim_whitespace=True)


class KnowledgeErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()
