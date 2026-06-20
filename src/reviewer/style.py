from .base import BaseReviewer
from .output_schema import Category
from .prompts import STYLE_PROMPT


class StyleReviewer(BaseReviewer):
    @property
    def category(self) -> Category:
        return Category.STYLE

    @property
    def system_prompt(self) -> str:
        return STYLE_PROMPT
