from .base import BaseReviewer
from .output_schema import Category
from .prompts import SECURITY_PROMPT


class SecurityReviewer(BaseReviewer):
    @property
    def category(self) -> Category:
        return Category.SECURITY

    @property
    def system_prompt(self) -> str:
        return SECURITY_PROMPT
