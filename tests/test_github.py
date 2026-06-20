"""测试 GitHub CLI集成 — G-1 到 G-2"""
import pytest
from src.github import parse_pr_ref


class TestParsePrRef:
    # G-1: owner/repo#123
    def test_full_ref(self):
        owner, repo, num = parse_pr_ref("owner/repo#123")
        assert owner == "owner"
        assert repo == "repo"
        assert num == 123

    # G-1b: owner/repo#456
    def test_full_ref_large(self):
        owner, repo, num = parse_pr_ref("my-org/my-repo#9999")
        assert owner == "my-org"
        assert repo == "my-repo"
        assert num == 9999

    # G-2: #123
    def test_short_ref(self):
        owner, repo, num = parse_pr_ref("#123")
        assert owner is None
        assert repo is None
        assert num == 123

    # G-2b: bare number
    def test_bare_number(self):
        owner, repo, num = parse_pr_ref("42")
        assert owner is None
        assert repo is None
        assert num == 42

    # Edge: invalid format
    def test_invalid_ref(self):
        with pytest.raises(ValueError):
            parse_pr_ref("not-a-ref")

        with pytest.raises(ValueError):
            parse_pr_ref("")

        with pytest.raises(ValueError):
            parse_pr_ref("owner/repo")
