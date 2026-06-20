"""测试 GitHubIntegration — G-3, G-4, G-5 边界情况"""
import pytest
from unittest.mock import patch, MagicMock
from src.github import GitHubIntegration, parse_pr_ref, _gh


class TestGitHubIntegration:
    def setup_method(self):
        self.gh = GitHubIntegration()

    # G-5: gh不存在时的错误处理
    def test_gh_not_found(self):
        with patch("src.github.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("gh not found")
            with pytest.raises(RuntimeError, match="not found"):
                _gh("pr", "view", "1")

    # G-5b: post_comment 处理 FileNotFoundError
    def test_post_comment_gh_not_found(self):
        with patch("src.github.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("gh not found")
            result = self.gh.post_comment("#1", "test comment")
            assert result is False

    # G-4: post_comment 正常流程
    def test_post_comment_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("src.github.subprocess.run", return_value=mock_result):
            result = self.gh.post_comment("#1", "test comment")
            assert result is True

    # G-4b: post_comment 失败
    def test_post_comment_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error: not found"
        with patch("src.github.subprocess.run", return_value=mock_result):
            result = self.gh.post_comment("#1", "test comment")
            assert result is False
