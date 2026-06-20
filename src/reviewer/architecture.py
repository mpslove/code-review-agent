from .base import BaseReviewer
from .output_schema import Category
from .prompts import ARCHITECTURE_PROMPT


class ArchitectureReviewer(BaseReviewer):
    @property
    def category(self) -> Category:
        return Category.ARCHITECTURE

    @property
    def system_prompt(self) -> str:
        return ARCHITECTURE_PROMPT
