#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_embedded_py_name_order.py - 扫 .sh 内嵌 Python 的「模块级先使用后定义」。

## 为什么有这个守卫(2026-10-26, P1 事故)

schedule_monitor.sh 的内嵌 Python 里, 阈值常量 MISSED_CONTINUOUS_THRESHOLD 定义在
模块尾部, 而模块级 `for t in TASKS:` 漏跑检查先使用它。Python 模块级是顺序执行的,
所以任何任务首次漏跑必抛 NameError, 整轮监控中止; 脚本末尾 `exit 0` 又让 systemd
恒报 success ⇒ 崩溃完全静默 26 天(2026-09-29 引入, 崩 22 次, 13 次真漏跑被吞)。

已有测试全是「抽片段 exec + 手工注入命名空间」, 常量缺失被掩盖, 没人整段跑一遍。
本守卫补的就是这个洞: **直接按 shell 里 heredoc 的顺序读真源码, 按模块级执行顺序
检查「名字先被读、后才有模块级绑定」**。

## 检查口径

- 只看 `.sh` 文件里 **heredoc 内嵌的 Python**(`python <<'PYEOF'` / `"$PY" - <<'PYEOF'`
  / `cat > x.py <<'PY'` 等), 不看不含 heredoc 的 `python -c` 单行。
- 「模块级执行」= 模块体 + 模块级的 if/for/while/with/try 各分支 + class 体;
  **函数/lambda 体不算**(定义时不执行, 后续再引用是合法的)。
- 判定: 模块级读到一个名字时, 它既没在前面绑定过, 又**在后面某处有模块级绑定**
  ⇒ 命中「先使用后定义」(这正是会 NameError 的形态)。
- 三种本工具无法静态判定的情形**必须显式登记**(带原因), 不许静默放过:
  ① `from x import *` ② `exec()/eval()/compile()` 动态执行 ③ 非 Python 的 heredoc;
  另: heredoc 声明为 Python 但 ast 解析失败(多为未加引号的分隔符被 shell 展开)也算
  ③ 类, 必须登记。
- 允许名单里登记了却扫不到的条目同样报错(防过期死条目)。

用法:
    python3 scripts/check_embedded_py_name_order.py --root .
退出码: 0 = 干净; 1 = 有命中; 2 = 用法错误。
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple

# ── heredoc 识别 ─────────────────────────────────────────────────────────────
# 排除 <<<(herestring); 分隔符可加引号(加引号 = 禁止 shell 展开, 常见于 Python 块)。
HEREDOC_RE = re.compile(
    r'(?<!<)<<(?P<dash>-?)[ \t]*(?P<q>["\']?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)(?P=q)'
)

# 分隔符本身就强烈暗示 Python(用于 `py=$(cat <<'PYEOF'` 这种命令里看不到解释器的情形)
PY_TAGS = {"PYEOF", "PY", "PYTHON", "PY3", "PYTHON3"}

# 常见「解释器放在变量里」的写法: "$PY" / "${PY}" / "$REPO/.venv/bin/python"
PY_CMD_VARS = {"PY", "PYTHON", "PY3", "PYTHON3", "PYBIN", "VENV_PY", "PYTHON_BIN"}

# match 语句只在 Python 3.10+ 有节点类型; 低版本退化成空元组(= 永远不匹配)
AST_MATCH = getattr(ast, "Match", ())

SKIP_DIR_NAMES = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".claude", "data", "staticdata", "build", "dist",
}

# ── 显式允许名单(每条必须写原因; 登记了但扫不到的条目会报「过期」) ───────────
# 键 = (仓库相对路径, heredoc 分隔符, 同文件同分隔符的第 n 个, 从 1 开始)
NON_PYTHON_ALLOWLIST: Dict[Tuple[str, str, int], str] = {
    ("scripts/build_echarts.sh", "ENTRY", 1): "生成 entry.js(前端 JS 图表入口), 非 Python",
    ("scripts/claude-inbox-consumer.sh", "EOF", 1): "拼 LLM 提示词纯文本, 非代码",
    ("scripts/codex-review-request.sh", "EOF", 1): "写临时 signal JSON 载荷, 非 Python",
    ("scripts/staticdata_backup_async.sh", "EOF", 1): "喂 while read 的文件清单, 非 Python",
    ("scripts/staticdata_sync.sh", "EOF", 1): "喂 while read 的文件清单, 非 Python",
    # 以下三处是测试自己造的最小 bash 包装脚本(内联生成后 exec), 非 Python
    ("scripts/tests/test_resolve_repo.sh", "EOS", 1): "造 t4_wrapper.sh(bash 三行包装), 测 resolve_repo fail-loud",
    ("scripts/tests/test_resolve_repo.sh", "EOS", 2): "造 t6.sh(bash 变量集合探针), 测无副作用",
    ("scripts/tests/test_resolve_repo.sh", "EOS", 3): "造 t6b.sh(bash export 语义探针), 测子 shell 可见性",
}

# 键同 NON_PYTHON_ALLOWLIST; 覆盖 ① from x import * ② exec/eval/compile
UNVERIFIABLE_PY_ALLOWLIST: Dict[Tuple[str, str, int], str] = {}


class Heredoc:
    """一个 heredoc 块。line_no 是起始行的 1-based 行号, body 不含分隔符行。"""

    def __init__(self, path: Path, rel: str, line_no: int, tag: str, prefix: str,
                 body: List[str], nth: int):
        self.path = path
        self.rel = rel
        self.line_no = line_no
        self.tag = tag
        self.prefix = prefix
        self.body = body
        self.nth = nth

    @property
    def key(self) -> Tuple[str, str, int]:
        return (self.rel, self.tag, self.nth)


def _strip_shell_comment(line: str) -> str:
    """去掉行内 shell 注释(# 只在引号外、且前面是空白时才算注释起始)。"""
    out: List[str] = []
    quote: Optional[str] = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            out.append(ch)
            if ch == quote and (i == 0 or line[i - 1] != "\\"):
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def iter_heredocs(path: Path, rel: str) -> Iterator[Heredoc]:
    """按文件顺序产出 heredoc; 未闭合的块也会产出(交给调用方报错)。"""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    counts: Dict[str, int] = {}
    i = 0
    while i < len(lines):
        code = _strip_shell_comment(lines[i])
        m = HEREDOC_RE.search(code)
        if not m:
            i += 1
            continue
        tag = m.group("tag")
        dash = m.group("dash") == "-"
        counts[tag] = counts.get(tag, 0) + 1
        body: List[str] = []
        j = i + 1
        closed = False
        while j < len(lines):
            raw = lines[j]
            cmp_line = raw.lstrip("\t") if dash else raw
            if cmp_line.strip() == tag:
                closed = True
                break
            body.append(raw)
            j += 1
        yield Heredoc(path, rel, i + 1, tag, code[: m.start()], body, counts[tag])
        if not closed:
            # 未闭合: 已把剩余全部当 body 产出, 由调用方判错; 不静默截断。
            return
        i = j + 1


def classify(hd: Heredoc) -> str:
    """'python' / 'other'。只看起始行的命令与重定向前缀 + 分隔符暗示。"""
    tokens = [t for t in re.split(r"[\s;|&()]+", hd.prefix.strip()) if t]
    for tok in tokens:
        bare = tok.strip("\"'")
        base = bare.rsplit("/", 1)[-1].lower()
        if "python" in base:
            return "python"
        if re.fullmatch(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", bare):
            if bare.strip("${}") in PY_CMD_VARS:
                return "python"
    # 重定向写入 *.py(先写文件后执行)
    if re.search(r">>?\s*[\"']?[^\s\"']*\.py[\"']?", hd.prefix):
        return "python"
    if hd.tag.upper() in PY_TAGS:
        return "python"
    return "other"


# ── 模块级执行顺序分析 ───────────────────────────────────────────────────────
class _State:
    def __init__(self, future_annotations: bool):
        self.bound: Set[str] = set()
        self.all_bindings: Set[str] = set()
        self.issues: List[str] = []          # 人读描述(已带 heredoc 内行号)
        self.star_imports: List[int] = []    # ast 行号
        self.dynamic_calls: List[int] = []   # ast 行号
        self.future_annotations = future_annotations
        self.mode = "collect"                # collect / check
        self.line_base = 0                   # heredoc 起始行号(换真文件行号用)

    def load(self, name: str, lineno: Optional[int]) -> None:
        if self.mode != "check" or name in self.bound:
            return
        if name in self.all_bindings:
            self.issues.append(
                f"模块级先使用后定义: `{name}` 在第 {self.link(lineno)} 行被读取, "
                f"但模块级绑定在后面才出现(执行到此处必 NameError)"
            )

    def bind(self, name: str, binding: bool = True) -> None:
        if self.mode == "collect":
            self.all_bindings.add(name)
        elif binding:
            self.bound.add(name)

    def link(self, lineno: Optional[int]) -> str:
        return "?" if lineno is None else str(self.line_base + lineno)


def _target_names(node: ast.AST, out: Set[str]) -> None:
    if isinstance(node, ast.Name):
        out.add(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for e in node.elts:
            _target_names(e, out)
    elif isinstance(node, ast.Starred):
        _target_names(node.value, out)


class EmbeddedModuleChecker:
    """对一个 heredoc 的 Python 源码做「模块级先使用后定义」检查。"""

    def __init__(self, hd: Heredoc):
        self.hd = hd
        self.state: Optional[_State] = None

    # 内部:两个 pass 都走同一套走法, 差异只由 state.mode 控制
    def run(self) -> Optional[_State]:
        src = "\n".join(self.hd.body) + "\n"
        try:
            tree = ast.parse(src, filename=f"{self.hd.rel}:{self.hd.line_no}")
        except SyntaxError as exc:
            return None  # 由调用方按「无法解析, 需登记」处理
        future = any(
            isinstance(n, ast.ImportFrom) and n.module == "__future__"
            and any(a.name == "annotations" for a in n.names)
            for n in tree.body
        )
        # pass 1: 收集全模块的模块级绑定(含出现在后面的), 供 pass 2 判「后面才定义」
        collect = _State(future)
        collect.mode = "collect"
        collect.line_base = self.hd.line_no
        self._walk_stmts(tree.body, collect, class_scope=False)

        # pass 2: 按执行顺序走, 读到还没绑定的名字且它最终会被绑定 ⇒ 命中
        check = _State(future)
        check.mode = "check"
        check.line_base = self.hd.line_no
        check.all_bindings = collect.all_bindings
        self._walk_stmts(tree.body, check, class_scope=False)

        self.state = check
        return self.state

    # ---- 语句 ----
    def _walk_stmts(self, stmts: Sequence[ast.stmt], st: _State, class_scope: bool) -> None:
        for s in stmts:
            self._walk_stmt(s, st, class_scope)

    def _walk_stmt(self, s: ast.stmt, st: _State, class_scope: bool) -> None:
        if isinstance(s, ast.Assign):
            self._expr(s.value, st)
            for t in s.targets:
                self._target(t, st, class_scope)

        elif isinstance(s, ast.AnnAssign):
            self._annotation(s.annotation, st)
            if s.value is not None:
                self._expr(s.value, st)
            self._target(s.target, st, class_scope)

        elif isinstance(s, ast.AugAssign):
            self._expr(s.target, st)          # 先读
            self._expr(s.value, st)
            self._target(s.target, st, class_scope)

        elif isinstance(s, ast.Expr):
            self._expr(s.value, st)

        elif isinstance(s, (ast.For, ast.AsyncFor)):
            self._expr(s.iter, st)
            self._target(s.target, st, class_scope)
            self._walk_stmts(s.body, st, class_scope)
            self._walk_stmts(s.orelse, st, class_scope)

        elif isinstance(s, ast.While):
            self._expr(s.test, st)
            self._walk_stmts(s.body, st, class_scope)
            self._walk_stmts(s.orelse, st, class_scope)

        elif isinstance(s, ast.If):
            self._expr(s.test, st)
            self._walk_stmts(s.body, st, class_scope)
            self._walk_stmts(s.orelse, st, class_scope)

        elif isinstance(s, (ast.With, ast.AsyncWith)):
            for item in s.items:
                self._expr(item.context_expr, st)
                if item.optional_vars is not None:
                    self._target(item.optional_vars, st, class_scope)
            self._walk_stmts(s.body, st, class_scope)

        elif isinstance(s, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            self._walk_stmts(s.body, st, class_scope)
            for h in s.handlers:
                if h.type is not None:
                    self._expr(h.type, st)
                if h.name:
                    st.bind(h.name, binding=not class_scope)
                self._walk_stmts(h.body, st, class_scope)
            self._walk_stmts(s.orelse, st, class_scope)
            self._walk_stmts(s.finalbody, st, class_scope)

        elif isinstance(s, ast.FunctionDef) or isinstance(s, ast.AsyncFunctionDef):
            # 装饰器/默认值/注解在定义时求值; 函数体延后执行 ⇒ 不进来。
            for d in s.decorator_list:
                self._expr(d, st)
            for d in list(s.args.defaults) + [x for x in s.args.kw_defaults if x is not None]:
                self._expr(d, st)
            self._annotation(s.returns, st)
            for a in list(s.args.posonlyargs) + list(s.args.args) + list(s.args.kwonlyargs):
                if a.annotation is not None:
                    self._annotation(a.annotation, st)
            if s.args.vararg is not None and s.args.vararg.annotation is not None:
                self._annotation(s.args.vararg.annotation, st)
            if s.args.kwarg is not None and s.args.kwarg.annotation is not None:
                self._annotation(s.args.kwarg.annotation, st)
            st.bind(s.name, binding=not class_scope)

        elif isinstance(s, ast.ClassDef):
            for d in s.decorator_list:
                self._expr(d, st)
            for b in s.bases:
                self._expr(b, st)
            for kw in s.keywords:
                self._expr(kw.value, st)
            # class 体立即执行, 但体内赋值进的是类命名空间 ⇒ 不绑到模块名
            self._walk_stmts(s.body, st, class_scope=True)
            st.bind(s.name, binding=not class_scope)

        elif isinstance(s, ast.Import):
            for a in s.names:
                st.bind((a.asname or a.name.split(".")[0]), binding=not class_scope)

        elif isinstance(s, ast.ImportFrom):
            if any(a.name == "*" for a in s.names):
                st.star_imports.append(s.lineno)
            else:
                for a in s.names:
                    st.bind((a.asname or a.name), binding=not class_scope)

        elif isinstance(s, ast.Delete):
            for t in s.targets:
                self._expr(t, st)

        elif isinstance(s, ast.Assert):
            self._expr(s.test, st)
            if s.msg is not None:
                self._expr(s.msg, st)

        elif isinstance(s, ast.Raise):
            if s.exc is not None:
                self._expr(s.exc, st)
            if s.cause is not None:
                self._expr(s.cause, st)

        elif isinstance(s, ast.Return):
            if s.value is not None:
                self._expr(s.value, st)

        elif isinstance(s, AST_MATCH):
            self._expr(s.subject, st)
            for case in s.cases:
                names: Set[str] = set()
                _pattern_names(case.pattern, names)
                for n in names:
                    st.bind(n, binding=not class_scope)
                if case.guard is not None:
                    self._expr(case.guard, st)
                self._walk_stmts(case.body, st, class_scope)

        elif isinstance(s, ast.Global) or isinstance(s, ast.Nonlocal):
            pass

        else:
            # Pass / Break / Continue / 其它: 无名字副作用
            for child in ast.iter_child_nodes(s):
                if isinstance(child, ast.expr):
                    self._expr(child, st)

    # ---- 目标 / 表达式 ----
    def _target(self, node: ast.AST, st: _State, class_scope: bool) -> None:
        if isinstance(node, ast.Name):
            st.bind(node.id, binding=not class_scope)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for e in node.elts:
                self._target(e, st, class_scope)
        elif isinstance(node, ast.Starred):
            self._target(node.value, st, class_scope)
        elif isinstance(node, ast.Attribute):
            self._expr(node.value, st)
        elif isinstance(node, ast.Subscript):
            self._expr(node.value, st)
            self._expr(node.slice, st)
        else:
            self._expr(node, st)

    def _annotation(self, node: Optional[ast.AST], st: _State) -> None:
        if node is None or st.future_annotations:
            return
        self._expr(node, st)

    def _expr(self, node: Optional[ast.AST], st: _State, local: Optional[Set[str]] = None) -> None:
        if node is None:
            return
        local = local or set()

        if isinstance(node, ast.Name):
            if node.id not in local:
                st.load(node.id, node.lineno)

        elif isinstance(node, ast.Attribute):
            self._expr(node.value, st, local)

        elif isinstance(node, ast.Subscript):
            self._expr(node.value, st, local)
            self._expr(node.slice, st, local)

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in {"exec", "eval", "compile"}:
                st.dynamic_calls.append(node.lineno)
            self._expr(node.func, st, local)
            for a in node.args:
                self._expr(a, st, local)
            for kw in node.keywords:
                self._expr(kw.value, st, local)

        elif isinstance(node, ast.Lambda):
            for d in list(node.args.defaults) + [x for x in node.args.kw_defaults if x is not None]:
                self._expr(d, st, local)
            # 函数体延后执行, 不检查

        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            inner = set(local)
            for gen in node.generators:
                _target_names(gen.target, inner)
            for gen in node.generators:
                self._expr(gen.iter, st, inner)
                for cond in gen.ifs:
                    self._expr(cond, st, inner)
            self._expr(node.elt, st, inner)

        elif isinstance(node, ast.DictComp):
            inner = set(local)
            for gen in node.generators:
                _target_names(gen.target, inner)
            for gen in node.generators:
                self._expr(gen.iter, st, inner)
                for cond in gen.ifs:
                    self._expr(cond, st, inner)
            self._expr(node.key, st, inner)
            self._expr(node.value, st, inner)

        elif isinstance(node, ast.NamedExpr):
            self._expr(node.value, st, local)
            if isinstance(node.target, ast.Name):
                st.bind(node.target.id)

        else:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.expr):
                    self._expr(child, st, local)
                elif isinstance(child, ast.comprehension):
                    # 正常情况下已被上面三类推导式分支吃掉
                    continue


def _pattern_names(node: ast.AST, out: Set[str]) -> None:
    """收集 match 模式里的捕获名(其余子表达式由 pattern 内部结构兜住)。"""
    for child in ast.walk(node):
        if isinstance(child, ast.MatchAs) and child.name:
            out.add(child.name)
        elif isinstance(child, ast.MatchStar) and child.name:
            out.add(child.name)
        elif isinstance(child, ast.MatchMapping) and child.rest:
            out.add(child.rest)


# ── 主流程 ──────────────────────────────────────────────────────────────────
def iter_shell_files(root: Path) -> Iterator[Path]:
    for p in sorted(root.rglob("*.sh")):
        rel_parts = p.relative_to(root).parts
        if any(part in SKIP_DIR_NAMES for part in rel_parts[:-1]):
            continue
        if p.is_file() and not p.is_symlink():
            yield p


def check_root(root: Path) -> Tuple[int, List[str], List[Heredoc]]:
    problems: List[str] = []
    seen: List[Heredoc] = []
    n_shell = n_py = 0

    for path in iter_shell_files(root):
        n_shell += 1
        rel = str(path.relative_to(root))
        for hd in iter_heredocs(path, rel):
            seen.append(hd)
            kind = classify(hd)
            if kind == "other":
                if hd.key not in NON_PYTHON_ALLOWLIST:
                    problems.append(
                        f"{rel}:{hd.line_no} 未登记的非 Python heredoc(分隔符 {hd.tag}#{hd.nth})"
                        f" —— 请确认它是什么语言/用途, 登记进 NON_PYTHON_ALLOWLIST 并写原因"
                    )
                continue

            n_py += 1
            checker = EmbeddedModuleChecker(hd)
            st = checker.run()
            if st is None:
                if hd.key not in NON_PYTHON_ALLOWLIST:
                    problems.append(
                        f"{rel}:{hd.line_no} 声明为 Python 的 heredoc 无法 ast 解析"
                        f"(常见原因: 分隔符未加引号被 shell 展开) —— 需登记进 "
                        f"NON_PYTHON_ALLOWLIST 说明原因"
                    )
                continue

            if st.star_imports or st.dynamic_calls:
                if hd.key not in UNVERIFIABLE_PY_ALLOWLIST:
                    kinds = []
                    if st.star_imports:
                        kinds.append("from-import *")
                    if st.dynamic_calls:
                        kinds.append("exec/eval/compile 动态执行")
                    problems.append(
                        f"{rel}:{hd.line_no} 内嵌 Python 含无法静态判定的写法"
                        f"({'; '.join(kinds)}) —— 需登记进 UNVERIFIABLE_PY_ALLOWLIST 说明原因"
                    )

            for msg in st.issues:
                problems.append(f"{rel}:{hd.line_no} 起的内嵌 Python: {msg}")

    # 允许名单里登记了却扫不到的条目 = 死条目, 同样报出来
    keys_seen = {hd.key for hd in seen}
    for key, reason in sorted(NON_PYTHON_ALLOWLIST.items()):
        if key not in keys_seen:
            problems.append(
                f"允许名单过期: NON_PYTHON_ALLOWLIST[{key[0]} 分隔符={key[1]}#{key[2]}] "
                f"扫不到对应 heredoc(原因记录: {reason})"
            )
    for key, reason in sorted(UNVERIFIABLE_PY_ALLOWLIST.items()):
        if key not in keys_seen:
            problems.append(
                f"允许名单过期: UNVERIFIABLE_PY_ALLOWLIST[{key[0]} 分隔符={key[1]}#{key[2]}] "
                f"扫不到对应 heredoc(原因记录: {reason})"
            )

    print(f"扫描 {n_shell} 个 .sh / 内嵌 Python 块 {n_py} 个 / 命中 {len(problems)} 处")
    return (0 if not problems else 1), problems, seen


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="扫 .sh 内嵌 Python 的模块级先使用后定义")
    ap.add_argument("--root", default=".", help="仓库根目录(默认当前目录)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: --root 不是目录: {root}", file=sys.stderr)
        return 2

    rc, problems, _ = check_root(root)
    for msg in problems:
        print(f"FAIL {msg}")
    if problems:
        print(f"\n共 {len(problems)} 处需修/需登记。")
    return rc


if __name__ == "__main__":
    sys.exit(main())