from datetime import datetime, timezone

from integrations.sources.base import SourceBatch, SourceItem


class E2EDiscoverySource:
    def fetch(self, query):
        return SourceBatch(
            items=(SourceItem(
                external_id="E2E-TED-42141300",
                buyer_name="E2E Gear Procurement Authority",
                buyer_country="DEU",
                title="Demo industrial gears procurement",
                published_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
                deadline_at=datetime(2026, 9, 15, tzinfo=timezone.utc),
                source_url="https://ted.europa.eu/en/notice/-/detail/534032-2026",
                cpv_codes=("42141300",),
                buyer_identifier="E2E-DE-42141300",
            ),),
            capability_snapshot={
                "source": "TED_E2E_FIXTURE",
                "capture_method": "DEMO_FIXTURE",
                "authentication": "NONE",
                "result_limit": query.limit,
            },
            total_count=1,
            is_demo=True,
        )
