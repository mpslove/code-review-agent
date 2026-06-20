"""
Diff解析器 — 解析git diff输出
"""

import re
from typing import Any


def parse_diff(diff_text: str) -> list[dict[str, Any]]:
    """
    解析git diff，返回变更文件列表。

    Returns:
        [{"file": "src/main.py", "added_lines": [(10, "code"), ...], "removed_lines": [...]}]
    """
    if not diff_text or not diff_text.strip():
        return []

    results: list[dict[str, Any]] = []
    file_blocks = re.split(r"(?=^diff --git )", diff_text.strip(), flags=re.MULTILINE)

    for block in file_blocks:
        if not block.strip():
            continue

        file_match = re.search(r"^\+\+\+ b/(.+)", block, re.MULTILINE)
        if not file_match:
            continue
        filepath = file_match.group(1)

        added_lines: list[tuple[int, str]] = []
        removed_lines: list[tuple[int, str]] = []
        current_lineno_new = 0
        current_lineno_old = 0

        for line in block.splitlines():
            # 解析hunk头 @@ -old,count +new,count @@
            hunk_match = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if hunk_match:
                current_lineno_old = int(hunk_match.group(1))
                current_lineno_new = int(hunk_match.group(2))
                continue

            if line.startswith("+") and not line.startswith("+++"):
                added_lines.append((current_lineno_new, line[1:]))
                current_lineno_new += 1
                # 新增行不影响旧文件行号
            elif line.startswith("-") and not line.startswith("---"):
                removed_lines.append((current_lineno_old, line[1:]))
                current_lineno_old += 1
                # 删除行不影响新文件行号
            elif line.startswith("\\"):
                continue
            else:
                current_lineno_old += 1
                current_lineno_new += 1

        results.append(
            {
                "file": filepath,
                "added_lines": added_lines,
                "removed_lines": removed_lines,
            }
        )

    return results


def get_changed_files(diff_text: str) -> list[str]:
    """提取变更的文件路径列表"""
    if not diff_text or not diff_text.strip():
        return []

    files = []
    for match in re.finditer(r"^\+\+\+ b/(.+)", diff_text, re.MULTILINE):
        files.append(match.group(1))
    return files


def get_diff_stats(diff_text: str) -> dict[str, int]:
    """返回 {files_changed: int, additions: int, deletions: int}"""
    parsed = parse_diff(diff_text)
    files_changed = len(parsed)
    additions = sum(len(item["added_lines"]) for item in parsed)
    deletions = sum(len(item["removed_lines"]) for item in parsed)
    return {
        "files_changed": files_changed,
        "additions": additions,
        "deletions": deletions,
    }


def extract_context(diff_text: str, filepath: str, line_start: int, radius: int = 8) -> str:
    """
    从diff中提取指定文件、指定行号附近的代码上下文。
    
    用于聚焦审查时展示问题行周围的代码。
    
    Args:
        diff_text: 完整diff
        filepath: 文件路径（如 src/main.py）
        line_start: 行号
        radius: 前后各取多少行
        
    Returns:
        上下文代码字符串，包含行号标注
    """
    # 提取该文件的diff块
    file_diff = _extract_file_block(diff_text, filepath)
    if not file_diff:
        return f"(无法提取 {filepath} 的diff上下文)"
    
    lines = file_diff.split('\n')
    output_lines = []
    current_new = 0
    found_target = False
    
    for line in lines:
        hunk_match = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if hunk_match:
            current_new = int(hunk_match.group(2))
            output_lines.append(line)
            continue
        
        if line.startswith('\\'):
            continue
            
        # 计算当前行在新文件中的行号
        if line.startswith('-'):
            continue  # 删除行不计入新文件行号
        elif line.startswith('+'):
            current_new += 1
        else:
            current_new += 1
        
        if abs(current_new - line_start) <= radius:
            output_lines.append(line)
            if current_new == line_start:
                found_target = True
    
    if not found_target:
        return f"(行 {line_start} 不在diff变更范围内)"
    
    return '\n'.join(output_lines)


def _extract_file_block(diff_text: str, filepath: str) -> str:
    """从完整diff中提取单个文件的diff块"""
    # 方法1: diff --git a/path b/path
    escaped = re.escape(filepath)
    m = re.search(
        rf'diff --git a/{escaped} b/{escaped}\n.*?(?=\ndiff --git |\Z)',
        diff_text, re.DOTALL
    )
    if m:
        return m.group(0)
    
    # 方法2: +++ b/path
    m = re.search(
        rf'\+\+\+ b/{escaped}\n(.*?)(?=\ndiff --git |\n--- |\Z)',
        diff_text, re.DOTALL
    )
    return m.group(1) if m else ""


def enrich_diff_hunks(diff_text: str, context_radius: int = 6) -> str:
    """
    增强diff：扩大每个hunk的上下文行数。
    
    GitHub API默认-U3（前后3行），这里尝试扩展。
    注意：如果diff已经是-U8生成的，这个函数不会有太大效果。
    真正的扩大需要从源头（gh pr diff -U N）做。
    
    这里做的是：在每个hunk头标记建议查看的周围函数/类名。
    """
    if not diff_text:
        return diff_text
    
    lines = diff_text.split('\n')
    enriched = []
    
    for line in lines:
        enriched.append(line)
        # 在每个hunk头后添加结构提示
        hunk_match = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@\s*(.*)", line)
        if hunk_match:
            func_hint = hunk_match.group(3).strip()
            if func_hint:
                enriched.append(f"  📍 所在函数/类: {func_hint}")
    
    return '\n'.join(enriched)


def extract_file_structure(diff_text: str) -> dict[str, list[str]]:
    """
    从diff中提取每个文件的函数/类结构概览。
    
    通过hunk header中的函数名推断。
    
    Returns:
        {"src/main.py": ["function handle_request", "class AuthMiddleware"], ...}
    """
    structure = {}
    current_file = None
    
    for line in diff_text.split('\n'):
        file_match = re.match(r'^\+\+\+ b/(.+)', line)
        if file_match:
            current_file = file_match.group(1)
            structure.setdefault(current_file, [])
            continue
        
        if current_file:
            hunk_match = re.match(r"^@@ .+ @@\s*(.+)", line)
            if hunk_match:
                func_name = hunk_match.group(1).strip()
                if func_name and len(func_name) > 2:
                    structure[current_file].append(func_name)
    
    return {k: v for k, v in structure.items() if v}


def analyze_test_coverage(diff_text: str) -> dict:
    """
    分析代码变更与测试覆盖的对应关系。
    
    Returns:
        {
            "changed_functions": [("file", "function_name"), ...],
            "test_functions": [("test_file", "test_name"), ...],
            "missing_tests": [("file", "function_name"), ...],
        }
    """
    changed_funcs = []
    test_funcs = []
    
    current_file = None
    
    for line in diff_text.split('\n'):
        # 追踪当前文件
        file_match = re.match(r'^\+\+\+ b/(.+)', line)
        if file_match:
            current_file = file_match.group(1)
            continue
        
        if not current_file:
            continue
        
        # 检测函数定义
        func_match = re.match(r'^\+.*\bdef\s+(\w+)\s*\(', line)
        if func_match:
            name = func_match.group(1)
            if current_file.startswith('test') or 'test' in current_file.lower():
                test_funcs.append((current_file, name))
            elif not name.startswith('_') or name == '__init__':
                changed_funcs.append((current_file, name))
        
        # 检测类定义
        class_match = re.match(r'^\+.*\bclass\s+(\w+)', line)
        if class_match:
            name = class_match.group(1)
            if not (current_file.startswith('test') or 'test' in current_file.lower()):
                changed_funcs.append((current_file, name))
    
    # 交叉比对：只标记全新文件中的函数
    # 已有文件的函数可能有已有测试，diff里看不到
    new_files = set()
    new_file_pattern = r'new file mode.*?\n.*?\+\+\+ b/(.+)'
    for m in re.finditer(new_file_pattern, diff_text, re.DOTALL):
        new_files.add(m.group(1))
    
    missing = []
    covered = []
    
    def normalize(name):
        return name.lower().replace('_', '')
    
    test_names = {normalize(tn) for _, tn in test_funcs}
    
    for fpath, fname in changed_funcs:
        norm = normalize(fname)
        matched = any(norm in tn for tn in test_names)
        
        if fpath in new_files and not matched:
            missing.append((fpath, fname))
        else:
            covered.append((fpath, fname))
    
    return {
        "changed_functions": changed_funcs,
        "test_functions": test_funcs,
        "missing_tests": missing,
        "covered": covered,
    }
