from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class DiscoveryQuery:
    cpv_codes: tuple[str, ...]
    published_from: date
    limit: int = 20

    def __post_init__(self):
        if not 1 <= self.limit <= 20:
            raise ValueError("Discovery result limit must be between 1 and 20.")
        if not self.cpv_codes or any(
            len(code) != 8 or not code.isdigit() for code in self.cpv_codes
        ):
            raise ValueError("Discovery CPV codes must be eight digit values.")


@dataclass(frozen=True)
class SourceItem:
    source_code: str
    external_id: str
    buyer_name: str
    buyer_country: str
    title: str
    published_at: datetime
    deadline_at: datetime | None
    source_url: str
    cpv_codes: tuple[str, ...]
    buyer_identifier: str = ""


@dataclass(frozen=True)
class SourceBatch:
    items: tuple[SourceItem, ...]
    capability_snapshot: dict[str, object]
    skipped_count: int = 0
    total_count: int = 0
    is_demo: bool = False


class SourceAdapterError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
