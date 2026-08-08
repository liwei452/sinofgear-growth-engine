from django.urls import path

from apps.audit.models import ReviewAction

from .models import KnowledgeAlias, KnowledgeConcept, KnowledgeEvidence, KnowledgeRelation
from .views import (
    KnowledgeAliasListView,
    KnowledgeConceptDetailView,
    KnowledgeConceptListView,
    KnowledgeEvidenceListView,
    KnowledgeRelationListView,
    ResolveAliasView,
    review_action_view,
)


urlpatterns = [
    path("knowledge/concepts", KnowledgeConceptListView.as_view(), name="knowledge-concepts"),
    path("knowledge/concepts/<uuid:concept_id>", KnowledgeConceptDetailView.as_view(), name="knowledge-concept-detail"),
    path("knowledge/relations", KnowledgeRelationListView.as_view(), name="knowledge-relations"),
    path("knowledge/aliases", KnowledgeAliasListView.as_view(), name="knowledge-aliases"),
    path("knowledge/evidence", KnowledgeEvidenceListView.as_view(), name="knowledge-evidence"),
    path("knowledge/resolve", ResolveAliasView.as_view(), name="knowledge-resolve"),
]

for segment, model, parameter in (
    ("concepts", KnowledgeConcept, "concept_id"),
    ("relations", KnowledgeRelation, "relation_id"),
    ("aliases", KnowledgeAlias, "alias_id"),
    ("evidence", KnowledgeEvidence, "evidence_id"),
):
    for action, slug in (
        (ReviewAction.SUBMIT, "submit-review"),
        (ReviewAction.APPROVE, "approve"),
        (ReviewAction.REJECT, "reject"),
        (ReviewAction.DEPRECATE, "deprecate"),
    ):
        urlpatterns.append(
            path(
                f"knowledge/{segment}/<uuid:{parameter}>/{slug}",
                review_action_view(model=model, action=action),
                name=f"knowledge-{segment}-{slug}",
            )
        )
