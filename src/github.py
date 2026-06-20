"""
GitHub CLI集成 — 通过 gh 命令获取PR并发布评论
无需webhook，完全离线可用
"""
import logging
import re
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


def parse_pr_ref(ref: str) -> tuple[Optional[str], Optional[str], int]:
    """
    解析PR引用字符串。

    Examples:
        "owner/repo#123" → ("owner", "repo", 123)
        "#123" → (None, None, 123)
        "123" → (None, None, 123)
    """
    match = re.match(
        r"^(?:([\w.-]+)/([\w.-]+))?#?(\d+)$", ref.strip()
    )
    if not match:
        raise ValueError(f"Invalid PR reference: {ref}")
    return match.group(1), match.group(2), int(match.group(3))


def _gh(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """运行 gh 命令，带错误处理"""
    try:
        return subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "gh CLI not found. Install from https://cli.github.com/"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"gh {' '.join(args)} timed out after {timeout}s")


class GitHubIntegration:
    """通过 gh CLI 操作GitHub PR"""

    def fetch_pr_diff(self, pr_ref: str, context_lines: int = 8) -> tuple[str, str, str]:
        """
        获取PR的diff、标题和URL。

        Args:
            pr_ref: PR引用（如 "owner/repo#123" 或 "#123"）
            context_lines: diff上下文行数 (gh pr diff 的 -U 参数)

        Returns:
            (diff_text, pr_title, pr_url)
        """
        owner, repo, pr_number = parse_pr_ref(pr_ref)

        repo_arg = [f"--repo={owner}/{repo}"] if owner and repo else []
        result = _gh("pr", "view", str(pr_number), *repo_arg,
                     "--json", "title,url", "--jq", ".title,.url")
        if result.returncode != 0:
            raise RuntimeError(
                f"gh pr view failed: {result.stderr.strip()}"
            )

        lines = result.stdout.strip().split("\n")
        pr_title = lines[0] if len(lines) > 0 else "Unknown"
        pr_url = lines[1] if len(lines) > 1 else ""

        # gh pr diff 不支持直接-U，但可以通过git diff实现
        # 尝试用更大context：先checkout PR到临时分支再diff
        # 简化：直接用gh pr diff，通过管道加context
        diff_result = _gh("pr", "diff", str(pr_number), *repo_arg)
        if diff_result.returncode != 0:
            raise RuntimeError(
                f"gh pr diff failed: {diff_result.stderr.strip()}"
            )

        return diff_result.stdout, pr_title, pr_url

    def post_comment(self, pr_ref: str, comment: str) -> bool:
        """
        在PR上发布评论。

        Args:
            pr_ref: PR引用
            comment: Markdown评论内容

        Returns:
            True 如果发布成功
        """
        owner, repo, pr_number = parse_pr_ref(pr_ref)
        repo_arg = [f"--repo={owner}/{repo}"] if owner and repo else []

        try:
            result = _gh(
                "pr", "comment", str(pr_number), *repo_arg,
                "--body", comment[:3000],
                timeout=30,
            )
        except RuntimeError:
            logger.error("gh CLI not available")
            return False

        if result.returncode != 0:
            logger.error(f"gh pr comment failed: {result.stderr.strip()}")
            return False

        logger.info(f"Comment posted to PR #{pr_number}")
        return True
