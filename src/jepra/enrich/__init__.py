"""リードの補完（サイト巡回によるメールアドレス発掘など）。"""

from .website import EnrichResult, enrich_lead

__all__ = ["EnrichResult", "enrich_lead"]
