"""
代码索引器 — 使用chromadb对代码进行语义索引
按函数/类边界分块
"""

import ast
import os
import uuid
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings


class CodeIndexer:
    """代码索引器 — 将仓库代码分块入库"""

    def __init__(self, project_root: str, persist_dir: str = "./data/chroma"):
        self.project_root = Path(project_root).resolve()
        self.client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name="code_review",
            metadata={"hnsw:space": "cosine"},
        )

    def _split_python_file(self, filepath: str) -> list[dict]:
        """
        按函数/类边界分块Python文件。

        Returns:
            [{"name": ..., "start_line": ..., "end_line": ..., "content": ...}]
        """
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()

        tree = ast.parse(source)

        chunks: list[dict] = []
        lines = source.splitlines()

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
            elif isinstance(node, ast.ClassDef):
                name = node.name
            else:
                continue

            start_line = node.lineno
            end_line = getattr(node, "end_lineno", node.lineno)
            content = "\n".join(lines[start_line - 1 : end_line])

            chunks.append(
                {
                    "name": name,
                    "start_line": start_line,
                    "end_line": end_line,
                    "content": content,
                }
            )

        return chunks

    def index_file(self, filepath: str) -> None:
        """索引单个文件，按函数/类边界分块"""
        filepath = str(Path(filepath).resolve())

        if not os.path.isfile(filepath):
            return

        rel_path = str(Path(filepath).relative_to(self.project_root))

        if filepath.endswith(".py"):
            try:
                chunks = self._split_python_file(filepath)
            except SyntaxError:
                return
        else:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            chunks = [
                {
                    "name": rel_path,
                    "start_line": 1,
                    "end_line": len(content.splitlines()),
                    "content": content,
                }
            ]

        ids: list[str] = []
        metadatas: list[dict] = []
        documents: list[str] = []

        for chunk in chunks:
            chunk_id = str(uuid.uuid4())
            ids.append(chunk_id)
            metadatas.append(
                {
                    "file": rel_path,
                    "name": chunk["name"],
                    "start_line": chunk["start_line"],
                    "end_line": chunk["end_line"],
                }
            )
            documents.append(chunk["content"])

        if documents:
            self.collection.add(
                ids=ids,
                metadatas=metadatas,
                documents=documents,
            )

    def index_project(self) -> None:
        """索引整个项目"""
        suffix = (
            ".py",
            ".js",
            ".ts",
            ".jsx",
            ".tsx",
            ".java",
            ".go",
            ".rs",
            ".c",
            ".cpp",
            ".h",
            ".hpp",
        )
        for root, _dirs, files in os.walk(self.project_root):
            for fname in files:
                if fname.endswith(suffix):
                    fpath = os.path.join(root, fname)
                    self.index_file(fpath)

    def search(self, query: str, top_k: int = 5) -> list[str]:
        """语义搜索相关代码片段"""
        results = self.collection.query(
            query_texts=[query],
            n_results=top_k,
        )

        output: list[str] = []
        if not results["documents"] or not results["metadatas"]:
            return output

        for i, doc in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i]
            header = f"{meta['file']}:{meta['name']} (L{meta['start_line']}-L{meta['end_line']})"
            output.append(f"{header}\n{doc}")

        return output
