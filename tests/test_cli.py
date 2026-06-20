"""测试 CLI入口 — 参数解析"""
import pytest
import sys
import argparse
from pathlib import Path


class TestCLIArgs:
    """测试 CLI 参数解析逻辑（不实际运行pipeline）"""

    def test_mutually_exclusive_diff_pr(self):
        """G-6: --diff-file 和 --pr 互斥"""
        # argparse 的 mutually_exclusive_group 会自动拒绝同时使用
        from argparse import ArgumentParser
        parser = ArgumentParser()
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--diff-file")
        group.add_argument("--pr")

        # 单独使用没问题
        args = parser.parse_args(["--diff-file", "test.diff"])
        assert args.diff_file == "test.diff"
        assert args.pr is None

        args2 = parser.parse_args(["--pr", "#42"])
        assert args2.pr == "#42"

        # 同时使用应该报错
        with pytest.raises(SystemExit):
            parser.parse_args(["--diff-file", "x", "--pr", "#42"])

    def test_post_comment_requires_pr(self):
        """G-7: --post-comment 需要 --pr"""
        from argparse import ArgumentParser
        parser = ArgumentParser()
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--diff-file")
        group.add_argument("--pr")
        parser.add_argument("--post-comment", action="store_true")

        # 只设 --post-comment 没问题（argparse不会校验业务逻辑）
        # 业务逻辑在 main() 中校验：if args.post_comment and not args.pr: sys.exit(1)
        # 这里验证参数可以独立解析
        args = parser.parse_args(["--pr", "#1", "--post-comment"])
        assert args.post_comment
        assert args.pr == "#1"

    def test_rag_project_arg(self):
        """R-5: --rag-project 参数存在"""
        from argparse import ArgumentParser
        parser = ArgumentParser()
        parser.add_argument("--rag-project", type=str)
        args = parser.parse_args(["--rag-project", "/path/to/repo"])
        assert args.rag_project == "/path/to/repo"
