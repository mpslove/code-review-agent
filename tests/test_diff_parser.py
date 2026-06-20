"""测试 Diff Parser"""
from src.tools.diff_parser import parse_diff, get_changed_files, get_diff_stats


class TestDiffParser:
    def test_parse_single_file(self):
        diff = """diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,4 @@
 old line
+new line
 old line"""
        result = parse_diff(diff)
        assert len(result) == 1
        assert result[0]["file"] == "src/main.py"
        assert len(result[0]["added_lines"]) == 1
        assert result[0]["added_lines"][0][1] == "new line"

    def test_parse_empty(self):
        assert parse_diff("") == []
        assert parse_diff("   ") == []

    def test_get_changed_files(self):
        diff = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1 +1,2 @@
+x
diff --git a/b.py b/b.py
--- a/b.py
+++ b/b.py
@@ -1 +1,2 @@
+y"""
        files = get_changed_files(diff)
        assert files == ["a.py", "b.py"]

    def test_get_changed_files_empty(self):
        assert get_changed_files("") == []

    def test_get_diff_stats(self):
        diff = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,3 +1,4 @@
-old
+new
+new2
 old"""
        stats = get_diff_stats(diff)
        assert stats["files_changed"] == 1
        assert stats["additions"] == 2
        assert stats["deletions"] == 1

    def test_get_diff_stats_empty(self):
        stats = get_diff_stats("")
        assert stats == {"files_changed": 0, "additions": 0, "deletions": 0}
