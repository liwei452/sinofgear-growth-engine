from dataclasses import dataclass

from .models import KnowledgeConcept, KnowledgeRelation


@dataclass(frozen=True)
class PredicateTypeRule:
    subject_types: frozenset[str]
    object_types: frozenset[str]
    require_same_type: bool = False


PREDICATE_TYPE_RULES = {
    KnowledgeRelation.Predicate.IS_A: PredicateTypeRule(
        frozenset(KnowledgeConcept.ConceptType.values),
        frozenset(KnowledgeConcept.ConceptType.values),
        require_same_type=True,
    ),
    KnowledgeRelation.Predicate.APPLIES_TO: PredicateTypeRule(
        frozenset({KnowledgeConcept.ConceptType.PRODUCT_TYPE}),
        frozenset({KnowledgeConcept.ConceptType.APPLICATION, KnowledgeConcept.ConceptType.INDUSTRY}),
    ),
    KnowledgeRelation.Predicate.USES_MATERIAL: PredicateTypeRule(
        frozenset({KnowledgeConcept.ConceptType.PRODUCT_TYPE}),
        frozenset({KnowledgeConcept.ConceptType.MATERIAL}),
    ),
    KnowledgeRelation.Predicate.REQUIRES_PROCESS: PredicateTypeRule(
        frozenset({KnowledgeConcept.ConceptType.PRODUCT_TYPE}),
        frozenset({KnowledgeConcept.ConceptType.PROCESS}),
    ),
    KnowledgeRelation.Predicate.COMPLIES_WITH: PredicateTypeRule(
        frozenset({KnowledgeConcept.ConceptType.PRODUCT_TYPE, KnowledgeConcept.ConceptType.PROCESS}),
        frozenset({KnowledgeConcept.ConceptType.STANDARD}),
    ),
    KnowledgeRelation.Predicate.RELEVANT_TO_CUSTOMER_TYPE: PredicateTypeRule(
        frozenset(
            {
                KnowledgeConcept.ConceptType.PRODUCT_TYPE,
                KnowledgeConcept.ConceptType.APPLICATION,
                KnowledgeConcept.ConceptType.INDUSTRY,
            }
        ),
        frozenset({KnowledgeConcept.ConceptType.CUSTOMER_TYPE}),
    ),
    KnowledgeRelation.Predicate.INDICATES_PURCHASE_INTENT: PredicateTypeRule(
        frozenset(
            {
                KnowledgeConcept.ConceptType.APPLICATION,
                KnowledgeConcept.ConceptType.INDUSTRY,
                KnowledgeConcept.ConceptType.CUSTOMER_TYPE,
                KnowledgeConcept.ConceptType.PURCHASE_INTENT,
            }
        ),
        frozenset({KnowledgeConcept.ConceptType.PURCHASE_INTENT}),
    ),
    KnowledgeRelation.Predicate.REQUIRES_PARAMETER: PredicateTypeRule(
        frozenset({KnowledgeConcept.ConceptType.PRODUCT_TYPE}),
        frozenset({KnowledgeConcept.ConceptType.PARAMETER}),
    ),
}


class RelationRuleError(ValueError):
    pass


class RelationCycleError(RelationRuleError):
    def __init__(self, path: list[str]) -> None:
        self.path = path
        super().__init__(f"IS_A cycle rejected: {' -> '.join(path)}")


def validate_predicate_types(*, subject: KnowledgeConcept, predicate: str, object: KnowledgeConcept) -> None:
    try:
        rule = PREDICATE_TYPE_RULES[predicate]
    except KeyError as error:
        raise RelationRuleError(f"Unsupported predicate: {predicate}") from error
    valid = subject.concept_type in rule.subject_types and object.concept_type in rule.object_types
    if rule.require_same_type:
        valid = valid and subject.concept_type == object.concept_type
    if not valid:
        subject_types = ", ".join(sorted(rule.subject_types))
        object_types = ", ".join(sorted(rule.object_types))
        suffix = " with matching concept types" if rule.require_same_type else ""
        raise RelationRuleError(
            f"{predicate} requires subject types [{subject_types}] and object types [{object_types}]{suffix}; "
            f"received {subject.concept_type} -> {object.concept_type}."
        )
