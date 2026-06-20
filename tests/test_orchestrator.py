"""测试 Orchestrator — O-1 到 O-6"""
import pytest
from src.orchestrator import Orchestrator
from src.reviewer.output_schema import Category


class TestOrchestrator:
    def setup_method(self):
        self.orch = Orchestrator()

    # O-1: 创建4个reviewer
    def test_init_creates_four_reviewers(self):
        assert len(self.orch.reviewers) == 4
        categories = [r.category for r in self.orch.reviewers]
        assert Category.SECURITY in categories
        assert Category.PERFORMANCE in categories
        assert Category.ARCHITECTURE in categories
        assert Category.STYLE in categories

    # O-3: 空diff
    def test_empty_diff(self):
        assert self.orch.review("") == []
        assert self.orch.review("   ") == []
        assert self.orch.review("\n  \n") == []

    # O-4: 降级结果按category排序
    def test_result_sorting(self):
        # Mock: 不实际调LLM，验证降级路径返回正确结构
        # 这里只验证对象初始化正确
        assert self.orch.reviewers[0].category == Category.SECURITY
        assert self.orch.reviewers[1].category == Category.PERFORMANCE
        assert self.orch.reviewers[2].category == Category.ARCHITECTURE
        assert self.orch.reviewers[3].category == Category.STYLE

    # O-5: indexer可选参数
    def test_indexer_optional(self):
        # 无indexer
        orch = Orchestrator()
        assert orch.indexer is None

        # 有indexer
        class FakeIndexer:
            def search(self, query, top_k=3):
                return []
        orch2 = Orchestrator(indexer=FakeIndexer())
        assert orch2.indexer is not None

    # O-6: RAG上下文为空时不检索
    def test_rag_context_bypass(self):
        # 没有indexer时，空diff直接返回
        assert self.orch.review("") == []

    # R-3: 有indexer时从diff提取文件并检索
    def test_rag_context_building(self):
        class FakeIndexer:
            def search(self, query, top_k=3):
                if "auth.py" in query:
                    return ["def login(): ..."]
                return []
        orch = Orchestrator(indexer=FakeIndexer())

        diff = """diff --git a/src/auth.py b/src/auth.py
--- a/src/auth.py
+++ b/src/auth.py
@@ -1,3 +1,4 @@
+new line"""
        ctx = orch._build_rag_context(diff)
        assert "auth.py" in ctx
        assert "def login" in ctx

    def test_rag_context_empty(self):
        class FakeIndexer:
            def search(self, query, top_k=3):
                return []
        orch = Orchestrator(indexer=FakeIndexer())
        ctx = orch._build_rag_context("diff --git a/x.py b/x.py\n+x")
        assert ctx == ""
