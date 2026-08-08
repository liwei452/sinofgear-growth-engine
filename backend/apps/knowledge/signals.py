from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from .guards import validate_evidence_link_scope
from .models import KnowledgeConcept, KnowledgeEvidence, KnowledgeRelation


def _validate_evidence_change(*, instance, model, pk_set, reverse: bool) -> None:
    if not pk_set:
        return
    if reverse:
        evidence = [instance]
        owners = model.objects.filter(pk__in=pk_set)
    else:
        evidence = KnowledgeEvidence.objects.filter(pk__in=pk_set)
        owners = [instance]
    for owner in owners:
        validate_evidence_link_scope(owner=owner, evidence_objects=evidence)


@receiver(m2m_changed, sender=KnowledgeConcept.evidence.through)
def validate_concept_evidence_scope(sender, instance, action, reverse, model, pk_set, **kwargs) -> None:
    if action == "pre_add":
        _validate_evidence_change(instance=instance, model=model, pk_set=pk_set, reverse=reverse)


@receiver(m2m_changed, sender=KnowledgeRelation.evidence.through)
def validate_relation_evidence_scope(sender, instance, action, reverse, model, pk_set, **kwargs) -> None:
    if action == "pre_add":
        _validate_evidence_change(instance=instance, model=model, pk_set=pk_set, reverse=reverse)
