from datetime import datetime, timezone

from integrations.sources.base import SourceBatch, SourceItem


class E2EDiscoverySource:
    def fetch(self, query):
        return SourceBatch(
            items=(SourceItem(
                source_code="TED",
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
                "governance": {
                    "source_owner": "SINOFGEAR_TEST_FIXTURE",
                    "access_method": "DEMO_FIXTURE",
                    "license_contract": "TEST_DATA_ONLY",
                    "robots_policy": "NO_NETWORK_ACCESS",
                    "rate_limit": "ONE_LOCAL_FIXTURE_PER_RUN",
                    "allowed_fields": [
                        "buyer_identifier", "buyer_name", "buyer_country",
                        "notice_title", "publication_date", "deadline_date",
                        "cpv_codes", "source_url",
                    ],
                    "retention_period": "TEST_RUN_ONLY",
                    "redistribution_restriction": "NOT_FOR_REDISTRIBUTION",
                    "queue": "MONITORING",
                },
            },
            total_count=1,
            is_demo=True,
        )
