from .base import BaseReviewer
from .output_schema import Category
from .prompts import PERFORMANCE_PROMPT


class PerformanceReviewer(BaseReviewer):
    @property
    def category(self) -> Category:
        return Category.PERFORMANCE

    @property
    def system_prompt(self) -> str:
        return PERFORMANCE_PROMPT
