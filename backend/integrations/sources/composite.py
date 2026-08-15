from .base import DiscoveryQuery, SourceAdapterError, SourceBatch


class CompositeDiscoverySource:
    source_code = "OFFICIAL_PROCUREMENT"

    def __init__(self, sources):
        self.sources = tuple(sources)

    def fetch(self, query: DiscoveryQuery) -> SourceBatch:
        successful_batches = []
        failures = []
        for source in self.sources:
            try:
                successful_batches.append(source.fetch(query))
            except SourceAdapterError as error:
                failures.append({"source": source.source_code, "code": error.code})
        if not successful_batches:
            raise SourceAdapterError("SOURCE_UNAVAILABLE")

        iterators = [iter(batch.items) for batch in successful_batches]
        items = []
        while iterators and len(items) < query.limit:
            remaining = []
            for iterator in iterators:
                try:
                    items.append(next(iterator))
                except StopIteration:
                    continue
                if len(items) >= query.limit:
                    break
                remaining.append(iterator)
            iterators = remaining

        return SourceBatch(
            items=tuple(items),
            capability_snapshot={
                "source": self.source_code,
                "capture_method": "OFFICIAL_PUBLIC_API",
                "authentication": "ANONYMOUS",
                "result_limit": query.limit,
                "sources": [batch.capability_snapshot for batch in successful_batches],
                "failures": failures,
            },
            skipped_count=sum(batch.skipped_count for batch in successful_batches),
            total_count=sum(batch.total_count for batch in successful_batches),
            is_demo=any(batch.is_demo for batch in successful_batches),
        )
