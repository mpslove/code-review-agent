"""
AST模式匹配检测器集 — 每个检测器是一个独立class，继承BaseDetector

检测清单（面试能讲的编译技术）：
1. MutableDefaultArgs     — 可变默认参数 `def foo(x=[])`
2. BareExcept             — 裸except `except:`
3. DangerousFunctions     — eval/exec/pickle/subprocess(shell=True)
4. SQLInjectionPattern    — f-string拼接到SQL
5. PathTraversal          — os.path.join + 用户输入
6. HardcodedSecrets       — 硬编码密码/密钥（正则匹配）
7. UnusedVariable         — 变量定义了但未使用
8. ResourceLeak           — open() 未用with
9. AssertInProduction     — 非测试文件中的assert
| 10. CompareWithSelf     — `if x == x` 恒真模式
| 11. DictMutateDuringIter — 遍历字典时修改字典（RuntimeError）
| 12. ConsecutiveTaskSubmit — 连续提交任务到队列/worker无等待（时序假设错误）
| 13. SwallowedFilterException — try/except中异常被静默吞掉，返回原始值（错误隐藏）
"""

import ast
import os
import re
from typing import Optional

from .base import BaseDetector, Finding, Severity


# ──────────────────────────────────────────────
# 1. 可变默认参数检测
# ──────────────────────────────────────────────
class MutableDefaultArgsDetector(BaseDetector):
    """检测函数定义中的可变默认参数（list/dict/set）"""
    name = "mutable-default-args"
    description = "Detects mutable objects used as default arguments"

    _MUTABLE_TYPES = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.SetComp, ast.DictComp)

    def run(self, file_path: str, source: str) -> list[Finding]:
        findings = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return findings

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for default in node.args.defaults + node.args.kw_defaults:
                    if isinstance(default, ast.Constant):
                        if isinstance(default.value, (list, dict, set)):
                            line = default.lineno
                            name = default.value
                            findings.append(Finding(
                                detector=self.name,
                                severity=Severity.WARNING,
                                file=file_path, line=line,
                                message=f"Mutable default argument {name!r} in '{node.name}' — shared across all calls",
                                suggestion="Use `None` and assign inside the function: `def foo(x=None): if x is None: x = []`",
                            ))
                    elif isinstance(default, self._MUTABLE_TYPES):
                        line = getattr(default, 'lineno', 0)
                        findings.append(Finding(
                            detector=self.name,
                            severity=Severity.WARNING,
                            file=file_path, line=line,
                            message=f"Mutable default argument in '{node.name}' — shared across all calls",
                            suggestion="Use `None` as default and initialize inside the function body",
                        ))
        return findings


# ──────────────────────────────────────────────
# 2. 裸except检测
# ──────────────────────────────────────────────
class BareExceptDetector(BaseDetector):
    """检测裸except: 语句（会吞掉所有异常包括KeyboardInterrupt）"""
    name = "bare-except"
    description = "Detects bare `except:` clauses"

    def run(self, file_path: str, source: str) -> list[Finding]:
        findings = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return findings

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    # Skip if it's just `except Exception:` — that's fine
                    parent = getattr(node, 'parent', None)
                    findings.append(Finding(
                        detector=self.name,
                        severity=Severity.WARNING,
                        file=file_path, line=node.lineno,
                        message="Bare `except:` catches ALL exceptions including KeyboardInterrupt/SystemExit",
                        suggestion="Use `except Exception:` instead of bare `except:`, or specify the exact exception type",
                    ))
        return findings


# ──────────────────────────────────────────────
# 3. 危险函数调用检测
# ──────────────────────────────────────────────
class DangerousFunctionsDetector(BaseDetector):
    """检测危险函数调用：eval/exec/pickle/subprocess(shell=True)"""
    name = "dangerous-functions"
    description = "Detects dangerous function calls that may lead to code injection"

    _DANGEROUS = {
        "eval": "Can execute arbitrary Python expressions",
        "exec": "Can execute arbitrary Python code",
        "pickle.loads": "Unsafe deserialization — can execute arbitrary code",
        "pickle.load": "Unsafe deserialization — can execute arbitrary code",
        "yaml.load": "Unsafe YAML deserialization — use yaml.safe_load instead",
        "subprocess.Popen": "Check for shell=True — can lead to command injection",
        "os.system": "Command injection risk — prefer subprocess.run with shell=False",
        "os.popen": "Command injection risk — prefer subprocess.run with shell=False",
        "input": "In Python 2, input() evaluates as code; in Python 3, it's safe",
    }

    def run(self, file_path: str, source: str) -> list[Finding]:
        findings = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return findings

        for node in ast.walk(tree):
            # Direct call like eval(...)
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    name = func.id
                    if name in self._DANGEROUS:
                        # Check if subprocess.Popen has shell=True
                        if name in ("subprocess.Popen",):
                            continue  # handled by keyword check below
                        findings.append(Finding(
                            detector=self.name,
                            severity=Severity.ERROR if name in ("eval", "exec", "pickle.loads", "pickle.load", "yaml.load") else Severity.WARNING,
                            file=file_path, line=node.lineno,
                            message=f"Dangerous function `{name}()`: {self._DANGEROUS[name]}",
                            suggestion=f"Avoid `{name}()` — use a safer alternative",
                        ))
                elif isinstance(func, ast.Attribute):
                    # Call like obj.method()
                    full_name = ""
                    if isinstance(func.value, ast.Name):
                        full_name = f"{func.value.id}.{func.attr}"
                    elif isinstance(func.value, ast.Attribute):
                        # subprocess.Popen
                        inner = func.value
                        if isinstance(inner.value, ast.Name):
                            full_name = f"{inner.value.id}.{inner.attr}.{func.attr}"
                    if full_name in self._DANGEROUS:
                        findings.append(Finding(
                            detector=self.name,
                            severity=Severity.ERROR,
                            file=file_path, line=node.lineno,
                            message=f"Dangerous function `{full_name}()`: {self._DANGEROUS[full_name]}",
                            suggestion=f"Avoid `{full_name}()` — use a safer alternative",
                        ))
                    # Check subprocess.Popen / subprocess.run for shell=True
                    if isinstance(func.value, ast.Name) and func.value.id in ("subprocess",):
                        if func.attr in ("Popen", "run", "call", "check_call", "check_output"):
                            shell_keywords = [kw for kw in node.keywords if kw.arg == "shell"]
                            for kw in shell_keywords:
                                if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                                    findings.append(Finding(
                                        detector=self.name,
                                        severity=Severity.ERROR,
                                        file=file_path, line=node.lineno,
                                        message="subprocess call with shell=True — command injection risk",
                                        suggestion="Use shell=False (default) and pass command as a list: subprocess.run(['cmd', 'arg1'])",
                                    ))

        return findings


# ──────────────────────────────────────────────
# 4. SQL注入模式检测
# ──────────────────────────────────────────────
# Regex-based: detect f-strings or %-formatting in SQL query strings
_SQL_KEYWORDS_RE = re.compile(
    r'(select|insert|update|delete|drop|create|alter|truncate)',
    re.IGNORECASE
)
_SQL_FORMAT_RE = re.compile(
    r"""(?:f['\"]|['\"]\s*%|\.format\(|\.format_map\(|f['\"])"""
)


class SQLInjectionDetector(BaseDetector):
    """检测SQL查询字符串中是否使用了格式化/拼接"""
    name = "sql-injection"
    description = "Detects SQL injection vulnerabilities via string formatting in SQL queries"

    def run(self, file_path: str, source: str) -> list[Finding]:
        findings = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return findings

        for node in ast.walk(tree):
            # Skip f-strings inside re.compile() / re.search() / re.match()
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in ("compile", "search", "match", "findall", "sub"):
                    if isinstance(func.value, ast.Name) and func.value.id == "re":
                        continue
                if isinstance(func, ast.Name) and func.id in ("compile", "search", "match"):
                    continue

            # f-string in SQL context
            if isinstance(node, ast.JoinedStr):
                # Check if this f-string is in a SQL-like string
                line_source = source.split('\n')[node.lineno - 1] if node.lineno <= len(source.split('\n')) else ""
                if _SQL_KEYWORDS_RE.search(line_source):
                    has_interpolation = any(
                        isinstance(v, ast.FormattedValue) for v in node.values
                    )
                    if has_interpolation:
                        findings.append(Finding(
                            detector=self.name,
                            severity=Severity.ERROR,
                            file=file_path, line=node.lineno,
                            message="SQL query uses f-string interpolation — SQL injection vulnerability",
                            suggestion="Use parameterized queries: `cursor.execute('SELECT ... WHERE x = ?', (param,))`",
                        ))

            # String concatenation with SQL
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str) and _SQL_KEYWORDS_RE.search(node.left.value):
                    findings.append(Finding(
                        detector=self.name,
                        severity=Severity.ERROR,
                        file=file_path, line=node.lineno,
                        message="SQL query built via string concatenation — SQL injection vulnerability",
                        suggestion="Use parameterized queries instead of string concatenation",
                    ))

            # .format() or % on SQL strings
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in ("format", "format_map"):
                    # Check if the caller contains SQL keywords
                    if isinstance(func.value, ast.Constant) and isinstance(func.value.value, str):
                        if _SQL_KEYWORDS_RE.search(func.value.value):
                            findings.append(Finding(
                                detector=self.name,
                                severity=Severity.ERROR,
                                file=file_path, line=node.lineno,
                                message="SQL query uses .format() — SQL injection vulnerability",
                                suggestion="Use parameterized queries instead of .format()",
                            ))

        return findings


# ──────────────────────────────────────────────
# 5. 路径遍历检测
# ──────────────────────────────────────────────
class PathTraversalDetector(BaseDetector):
    """检测os.path.join + 用户输入 导致的路径遍历"""
    name = "path-traversal"
    description = "Detects path traversal vulnerabilities"

    _SINK_FUNCS = {"open", "os.remove", "os.unlink", "shutil.rmtree", "os.rename",
                   "os.path.exists", "os.path.isfile", "os.path.isdir",
                   "Path.read_text", "Path.write_text", "Path.open",
                   "pathlib.Path"}

    def run(self, file_path: str, source: str) -> list[Finding]:
        findings = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return findings

        # Simple taint tracking: check if a variable from function parameter
        # flows into os.path.join or file open calls
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                params = {arg.arg for arg in node.args.args}
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        func = child.func
                        if isinstance(func, ast.Attribute):
                            # os.path.join(..., user_input, ...)
                            if func.attr in ("join", "open") and isinstance(func.value, ast.Attribute):
                                if getattr(func.value, 'attr', '') == 'path' and getattr(func.value.value, 'id', '') == 'os':
                                    for arg in child.args:
                                        if isinstance(arg, ast.Name) and arg.id in params:
                                            findings.append(Finding(
                                                detector=self.name,
                                                severity=Severity.ERROR,
                                                file=file_path, line=child.lineno,
                                                message=f"Path traversal: user input '{arg.id}' flows into os.path.join()",
                                                suggestion="Sanitize user input with os.path.basename() and verify with path.startswith(base_dir)",
                                            ))

        return findings


# ──────────────────────────────────────────────
# 6. 硬编码密钥/凭证检测
# ──────────────────────────────────────────────
_PASSWORD_PATTERNS = [
    (re.compile(r'(?i)(password|passwd|pwd|secret|api_key|apikey|token)\s*=\s*["\'](?![*])[^"\']{4,}["\']'),
     "Hardcoded credential detected"),
    (re.compile(r'(?i)(PASSWORD|SECRET_KEY|API_KEY|SECRET)\s*=\s*["\'][^"\']{8,}["\']'),
     "Hardcoded secret/key detected"),
    (re.compile(r'-----BEGIN (RSA |EC )?PRIVATE KEY-----'),
     "Private key embedded in source code"),
]


class HardcodedSecretsDetector(BaseDetector):
    """检测源码中的硬编码密码/密钥"""
    name = "hardcoded-secrets"
    description = "Detects hardcoded passwords, API keys, and secrets in source code"

    def run(self, file_path: str, source: str) -> list[Finding]:
        findings = []
        lines = source.split('\n')
        for lineno, line in enumerate(lines, 1):
            for pattern, msg in _PASSWORD_PATTERNS:
                if pattern.search(line) and not line.strip().startswith('#'):
                    findings.append(Finding(
                        detector=self.name,
                        severity=Severity.ERROR,
                        file=file_path, line=lineno,
                        message=msg,
                        suggestion="Use environment variables or a secrets manager: `os.getenv('API_KEY')`",
                        code_snippet=line.strip()[:100],
                    ))
        return findings


# ──────────────────────────────────────────────
# 7. 未使用变量检测
# ──────────────────────────────────────────────
class UnusedVariableDetector(BaseDetector):
    """检测定义了但从未使用的变量（仅限于函数内）"""
    name = "unused-variable"
    description = "Detects variables that are assigned but never read"

    def run(self, file_path: str, source: str) -> list[Finding]:
        findings = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return findings

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined = set()  # variables assigned in this function
                referenced = set()  # variables read in this function
                for child in ast.walk(node):
                    if isinstance(child, ast.Assign):
                        for target in child.targets:
                            if isinstance(target, ast.Name):
                                defined.add(target.id)
                    elif isinstance(child, ast.AugAssign):
                        if isinstance(child.target, ast.Name):
                            defined.add(child.target.id)
                            referenced.add(child.target.id)
                    elif isinstance(child, ast.Name):
                        if isinstance(child.ctx, ast.Load):
                            referenced.add(child.id)
                # Skip function params, loop vars, common conventions
                skip = set()
                for child in ast.walk(node):
                    if isinstance(child, ast.FunctionDef):
                        skip.update(a.arg for a in child.args.args)
                    if isinstance(child, ast.For):
                        if isinstance(child.target, ast.Name):
                            skip.add(child.target.id)
                    if isinstance(child, ast.ExceptHandler):
                        if child.name:
                            skip.add(child.name)

                unused = (defined - referenced) - skip - {"self", "cls", "_"}
                for var in unused:
                    # Find the line of assignment
                    for child in ast.walk(node):
                        if isinstance(child, ast.Assign):
                            for target in child.targets:
                                if isinstance(target, ast.Name) and target.id == var:
                                    findings.append(Finding(
                                        detector=self.name,
                                        severity=Severity.INFO,
                                        file=file_path, line=target.lineno,
                                        message=f"Unused variable '{var}'",
                                        suggestion=f"Remove `{var}` or prefix with underscore if intentionally unused",
                                    ))

        return findings


# ──────────────────────────────────────────────
# 8. 资源泄漏检测
# ──────────────────────────────────────────────
class ResourceLeakDetector(BaseDetector):
    """检测open()调用未使用with语句（潜在的资源泄漏）"""
    name = "resource-leak"
    description = "Detects file/resource operations without context managers"

    def run(self, file_path: str, source: str) -> list[Finding]:
        findings = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return findings

        # Track all with statements to find open() calls inside them
        with_context_lines = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.With):
                for item in node.items:
                    if isinstance(item.context_expr, ast.Call):
                        func = item.context_expr.func
                        if isinstance(func, ast.Name) and func.id == "open":
                            for child in ast.walk(item.context_expr):
                                if isinstance(child, ast.Name):
                                    with_context_lines.add(item.lineno)

        # Find open() calls NOT inside a with statement
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "open":
                    if node.lineno not in with_context_lines:
                        # Check if this is an assignment (stored in a variable)
                        findings.append(Finding(
                            detector=self.name,
                            severity=Severity.WARNING,
                            file=file_path, line=node.lineno,
                            message="open() called outside a `with` statement — potential file descriptor leak",
                            suggestion="Use `with open(...) as f:` to ensure proper resource cleanup",
                        ))

        return findings


# ──────────────────────────────────────────────
# 9. assert在生产代码中检测
# ──────────────────────────────────────────────
class AssertInProductionDetector(BaseDetector):
    """检测非测试文件中的assert语句（assert在python -O时被移除）"""
    name = "assert-in-production"
    description = "Detects assert statements outside test files"

    def run(self, file_path: str, source: str) -> list[Finding]:
        findings = []
        # Skip test files
        if '/test' in file_path.replace('\\', '/') or file_path.startswith('test_'):
            return findings
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return findings
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                findings.append(Finding(
                    detector=self.name,
                    severity=Severity.WARNING,
                    file=file_path, line=node.lineno,
                    message="`assert` in non-test code — disabled when Python runs with -O",
                    suggestion="Use a proper if/raise instead: `if not condition: raise ValueError(...)`",
                ))
        return findings


# ──────────────────────────────────────────────
# 10. 自比较检测
# ──────────────────────────────────────────────
class CompareWithSelfDetector(BaseDetector):
    """检测 `if x == x` 恒真比较（usually a typo for x == y）"""
    name = "compare-with-self"
    description = "Detects comparisons where a variable is compared to itself"

    _COMPARE_OPS = {ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn}

    def run(self, file_path: str, source: str) -> list[Finding]:
        findings = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return findings
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                left = node.left
                for op, right in zip(node.ops, node.comparators):
                    if type(op) in self._COMPARE_OPS:
                        if isinstance(left, ast.Name) and isinstance(right, ast.Name) and left.id == right.id:
                            findings.append(Finding(
                                detector=self.name,
                                severity=Severity.WARNING,
                                file=file_path, line=node.lineno,
                                message=f"Comparison `{left.id} {self._op_name(op)} {right.id}` is always True — possible typo",
                                suggestion=f"Check the intended comparison: did you mean `{left.id} {self._op_name(op)} <other_variable>`?",
                            ))
        return findings

    @staticmethod
    def _op_name(op: ast.cmpop) -> str:
        mapping = {
            ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=",
            ast.Gt: ">", ast.GtE: ">=", ast.Is: "is", ast.IsNot: "is not",
            ast.In: "in", ast.NotIn: "not in",
        }
        for cls, name in mapping.items():
            if isinstance(op, cls):
                return name
        return "?"


# ──────────────────────────────────────────────
# 11. 圈复杂度检测
# ──────────────────────────────────────────────
class CyclomaticComplexityDetector(BaseDetector):
    """检测函数圈复杂度超过阈值（McCabe指标）
    
    圈复杂度 = 1 + 决策点数量（if/while/for/except/and/or/case）
    阈值: > 10 = 警告, > 20 = 错误
    """
    name = "cyclomatic-complexity"
    description = "Detects functions with high cyclomatic complexity (McCabe)"

    def run(self, file_path: str, source: str) -> list[Finding]:
        findings = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return findings

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                complexity = 1  # base
                for child in ast.walk(node):
                    if isinstance(child, (ast.If, ast.While, ast.Assert)):
                        complexity += 1
                    elif isinstance(child, ast.For):
                        complexity += 1
                    elif isinstance(child, ast.ExceptHandler):
                        if child.type is not None:
                            complexity += 1
                    elif isinstance(child, ast.BoolOp):
                        complexity += len(child.values) - 1  # each 'and'/'or'
                    elif isinstance(child, ast.Try):
                        complexity += 1
                    # Match/case (Python 3.10+)
                    elif isinstance(child, ast.Match):
                        complexity += len(child.cases)

                if complexity > 20:
                    sev = Severity.ERROR
                    msg = f"Extreme complexity"
                elif complexity > 10:
                    sev = Severity.WARNING
                    msg = f"High complexity"
                else:
                    continue

                doc = ast.get_docstring(node) or ""
                doc_first_line = doc.split('\n')[0][:60] if doc else ""
                findings.append(Finding(
                    detector=self.name,
                    severity=sev,
                    file=file_path, line=node.lineno,
                    message=f"{msg}: '{node.name}' has cyclomatic complexity {complexity} (threshold: 10)",
                    suggestion=f"Refactor '{node.name}' into smaller functions (complexity {complexity} > 10). "
                              f"Consider extracting switch/case blocks and nested conditionals.",
                    code_snippet=doc_first_line,
                ))
        return findings


# ──────────────────────────────────────────────
# 12. 遍历字典时修改字典
# ──────────────────────────────────────────────
class DictMutateDuringIterDetector(BaseDetector):
    """检测在 `for k in dict:` 循环内部对同一个字典执行 `del dict[k]` 的操作
    
    在Python中，遍历字典时修改字典大小会抛出 RuntimeError: dictionary changed size during iteration
    """
    name = "dict-mutate-during-iter"
    description = "Detects dictionary mutation during iteration (RuntimeError)"

    def run(self, file_path: str, source: str) -> list[Finding]:
        findings = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return findings

        for node in ast.walk(tree):
            if not isinstance(node, (ast.For, ast.AsyncFor)):
                continue
            # Check if iterating over a dict — look at the iter target
            # Pattern: `for k in dict_var:` — the iter needs to resolve to a name
            iter_target = node.iter
            if not isinstance(iter_target, ast.Name):
                continue
            dict_var = iter_target.id

            # Now check if `del dict_var[k]` or `dict_var.pop(k)` appears in the loop body
            for child in ast.walk(node):
                # Pattern 1: del dict[k]
                if isinstance(child, ast.Delete):
                    for target in child.targets:
                        if isinstance(target, ast.Subscript):
                            if isinstance(target.value, ast.Name) and target.value.id == dict_var:
                                findings.append(Finding(
                                    detector=self.name,
                                    severity=Severity.ERROR,
                                    file=file_path, line=child.lineno,
                                    message=f"Modifying dict '{dict_var}' during iteration at line {child.lineno} — RuntimeError: dictionary changed size during iteration",
                                    suggestion=f"Use `list({dict_var}.keys())` for a snapshot copy: `for k in list({dict_var}.keys()):` or collect items to delete and delete outside the loop",
                                ))
                # Pattern 2: dict_var.pop(key) inside the loop
                if isinstance(child, ast.Call):
                    func = child.func
                    if isinstance(func, ast.Attribute) and func.attr == "pop":
                        if isinstance(func.value, ast.Name) and func.value.id == dict_var:
                            findings.append(Finding(
                                detector=self.name,
                                severity=Severity.ERROR,
                                file=file_path, line=child.lineno,
                                message=f"Calling '{dict_var}.pop()' during iteration at line {child.lineno} — RuntimeError: dictionary changed size during iteration",
                                suggestion=f"Use `list({dict_var}.items())` snapshot and filter: `for k, v in list({dict_var}.items()): if condition: del {dict_var}[k]`",
                            ))

        return findings


# ──────────────────────────────────────────────
# 13. 连续任务提交无等待
# ──────────────────────────────────────────────
class ConsecutiveTaskSubmitDetector(BaseDetector):
    """检测在同一个async函数中连续调用任务提交方法（.put/.delay/.enqueue/.submit）
    但调用之间没有await等待完成，隐含时序假设错误。
    
    典型错误：
        self.queue.put(task_a)
        self.queue.put(task_b)  # 假设task_a先执行，但实际可能并发
    正确做法：
        task = await pool.submit(...)
        result = await wait_for(task)
        self.queue.put(next_task)  # 确认前一个完成后才提交下一个
    """
    name = "consecutive-task-submit"
    description = "Detects consecutive task submissions without await between them (timing assumption error)"

    # 方法名黑名单 — 这些方法通常用于"提交/调度"异步任务
    _SUBMIT_METHODS = {"put", "delay", "enqueue", "submit", "schedule", "add_task", "dispatch"}

    def run(self, file_path: str, source: str) -> list[Finding]:
        findings = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return findings

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            # 收集函数体内所有 .put()/.delay() 等调用，按源码顺序
            submit_calls: list[tuple[int, ast.Call]] = []  # (lineno, call_node)
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    func = child.func
                    if isinstance(func, ast.Attribute):
                        if func.attr in self._SUBMIT_METHODS:
                            submit_calls.append((child.lineno, child))

            if len(submit_calls) < 2:
                continue

            # 按行号排序（ast.walk不保证顺序）
            submit_calls.sort(key=lambda x: x[0])

            # 检查相邻调用之间是否有 await 表达式
            for i in range(len(submit_calls) - 1):
                line_a, _ = submit_calls[i]
                line_b, call_b = submit_calls[i + 1]

                # 检查 line_a 和 line_b 之间是否有 await 语句
                has_await_between = False
                for child in ast.walk(node):
                    if isinstance(child, ast.Await):
                        # 检查这个 await 是否在两个 submit 调用之间
                        if line_a < child.lineno < line_b:
                            has_await_between = True
                            break

                if not has_await_between:
                    # 尝试获取方法名用于更精确的message
                    func_name = ""
                    func = call_b.func
                    if isinstance(func, ast.Attribute):
                        func_name = f".{func.attr}()"

                    findings.append(Finding(
                        detector=self.name,
                        severity=Severity.WARNING,
                        file=file_path, line=line_b,
                        message=f"Consecutive task submission{func_name} at line {line_b} without await between lines {line_a}-{line_b} — timing assumption may be violated in concurrent execution",
                        suggestion=f"Ensure the first task completes before submitting the next: add `await` or explicit completion check between the two submissions",
                    ))

        return findings


# ──────────────────────────────────────────────
# 14. 过滤器/处理函数中异常被静默吞掉
# ──────────────────────────────────────────────
class SwallowedFilterExceptionDetector(BaseDetector):
    """检测在try/except块中，异常被静默吞掉并返回原始值的模式
    
    典型错误：
        try:
            result = fn(value)
        except Exception:
            result = value  # 异常被吞掉，返回原始值
    正确做法：记录日志并重新raise，或返回有意义的错误标记
    """
    name = "swallowed-filter-exception"
    description = "Detects try/except blocks that silently return original value on exception"

    def run(self, file_path: str, source: str) -> list[Finding]:
        findings = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return findings

        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue

            for handler in node.handlers:
                if handler.type is None:
                    continue  # bare except, handled by other detector
                
                # Check if the except body contains a simple assignment
                # that returns the original input value
                body = handler.body
                if not body:
                    continue

                for stmt in body:
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if isinstance(target, ast.Name):
                                assigned_var = target.id
                                # Check if the assigned value is a simple Name
                                if isinstance(stmt.value, ast.Name):
                                    original_var = stmt.value.id
                                    # Check if this is a pattern like:
                                    # result = value  (swallowing exception, returning original)
                                    if assigned_var != original_var:
                                        # Look for variable names that suggest "result/output"
                                        continue

                                    findings.append(Finding(
                                        detector=self.name,
                                        severity=Severity.WARNING,
                                        file=file_path, line=handler.lineno,
                                        message=f"Exception silently swallowed at line {handler.lineno}: assigning original '{original_var}' back in except block — errors hidden from caller",
                                        suggestion=f"Log the exception before returning: add `logger.error(...)` before assignment, or use `raise` to propagate the error",
                                    ))

                    # Also check: `result = str(value)` as fallback
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if isinstance(target, ast.Name):
                                assigned = target.id
                                val = stmt.value
                                # Pattern: result = str(value) where value is from the try scope
                                if isinstance(val, ast.Call):
                                    func = val.func
                                    if isinstance(func, ast.Name) and func.id == "str":
                                        if val.args and isinstance(val.args[0], ast.Name):
                                            findings.append(Finding(
                                                detector=self.name,
                                                severity=Severity.WARNING,
                                                file=file_path, line=handler.lineno,
                                                message=f"Exception silently swallowed: returning 'str({val.args[0].id})' as fallback at line {handler.lineno} — type/semantic error hidden",
                                                suggestion=f"Do not silently swallow exceptions: log the error and either re-raise or return an explicit error value",
                                            ))

        return findings


# ──────────────────────────────────────────────
# 全部检测器注册
# ──────────────────────────────────────────────
ALL_DETECTORS: list[BaseDetector] = [
    MutableDefaultArgsDetector(),
    BareExceptDetector(),
    DangerousFunctionsDetector(),
    SQLInjectionDetector(),
    PathTraversalDetector(),
    HardcodedSecretsDetector(),
    UnusedVariableDetector(),
    ResourceLeakDetector(),
    AssertInProductionDetector(),
    CompareWithSelfDetector(),
    CyclomaticComplexityDetector(),
    DictMutateDuringIterDetector(),
    ConsecutiveTaskSubmitDetector(),
    SwallowedFilterExceptionDetector(),
]
