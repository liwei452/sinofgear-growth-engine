from apps.catalog.models import Product, ProductConceptLink, ROLE_CONCEPT_TYPES
from apps.knowledge.models import KnowledgeStatus


class CatalogProductContextAdapter:
    """Translate the current catalog product schema into a stable context document."""

    def serialize(
        self,
        product: Product,
        *,
        concept_links: list[ProductConceptLink] | None = None,
    ) -> dict:
        if concept_links is None:
            concept_links = self._current_concept_links(product)
        concepts = [
            {
                "link_id": str(link.id),
                "link_version": link.version,
                "role": link.role,
                "concept_id": str(link.concept_id),
                "concept_version": link.concept.version,
                "concept_status": link.concept.status,
                "concept_type": link.concept.concept_type,
                "concept_code": link.concept.code,
            }
            for link in concept_links
        ]
        return {
            "id": str(product.id),
            "version": product.version,
            "name_zh": product.name_zh,
            "name_en": product.name_en,
            "status": product.status,
            "landing_page_url": product.landing_page_url,
            "moq": product.moq,
            "lead_time": product.lead_time,
            "manufacturing_capabilities": list(product.manufacturing_capabilities),
            "inspection_capabilities": list(product.inspection_capabilities),
            "concepts": concepts,
            "technical_attributes": {
                "module_min": str(product.module_min),
                "module_max": str(product.module_max),
                "tooth_count_min": product.tooth_count_min,
                "tooth_count_max": product.tooth_count_max,
                "pressure_angle": str(product.pressure_angle),
                "accuracy_grade": product.accuracy_grade,
                "heat_treatment": product.heat_treatment,
                "surface_treatment": product.surface_treatment,
            },
        }

    @staticmethod
    def _current_concept_links(product: Product) -> list[ProductConceptLink]:
        links = list(
            ProductConceptLink.objects.select_for_update()
            .filter(product=product, retired_at__isnull=True)
            .select_related("concept")
            .order_by("role", "concept__code", "id")
        )
        return [
            link
            for link in links
            if link.organization_id == product.organization_id
            and link.concept.organization_id in {None, product.organization_id}
            and link.concept.status == KnowledgeStatus.APPROVED
            and link.concept.concept_type in ROLE_CONCEPT_TYPES.get(link.role, frozenset())
        ]
