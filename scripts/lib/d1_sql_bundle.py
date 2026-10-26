# -*- coding: utf-8 -*-
"""D1 导入包打包器（一表一文件 + 单条语句字节封顶）。

为什么有这个模块（2026-10-26，D1 同步提速改造的依据）:
  · 旧做法: 每 80 行一个 SQL 文件, 逐文件 `wrangler d1 execute --file` ⇒ 单表 347~354 次调用,
    实测 6.35 秒/次、合计 37~44 分钟; 而 D1 侧真正执行只有 11~13 毫秒/批(占 0.19%),
    99.8% 时间是进程冷启动 + import 握手。⇒ 合并成「一个表一个文件、一次导入」。
  · 官方上限: `d1 execute --file` 单文件 5 GiB(文件先 PUT 到 R2 再 ingest);
    **单条 SQL 语句 100,000 字节**, 超了报 `statement too long: SQLITE_TOOBIG`。
    旧做法只按「80 行」切批, 不控字节 ⇒ 实测最大单条 78,105 字节, 离上限只剩 22% 余量,
    某只基金长文本变长就会整包失败。本模块改为**按实际字节切批**(默认单条 ≤ 60,000,
    留 40% 余量), 并在写盘前**硬断言** max_stmt_bytes < 90,000, 超了直接失败退出,
    绝不上传半个包。

口径:
  · 缩进/换行固定为 `head + "\\n" + ",\\n".join(rows) + ";"`, 字节数按 UTF-8 实际编码计算
    (中文基金名/文本按 3 字节/字算, 不用字符数近似 —— 近似会低估, 正是超限的来源)。
  · 「单行本身就超软上限」时: 该行**独立成一条语句**(不与其他行混批), 记入 oversize_single_row;
    再由 `assert_limits()` 拿硬上限兜底。这是任务书证据用例 3 的行为。
  · 本模块只做纯计算/写盘, 不连 D1、不调 wrangler, 可在本机/CI 无副作用测试。
"""
from __future__ import annotations

import os

DEFAULT_MAX_STMT_BYTES = 60_000   # 软上限: 切批目标(官方硬上限 100,000 的 60%)
DEFAULT_ASSERT_MAX_BYTES = 90_000  # 硬断言: 超过即生成失败(留 10% 于官方上限之下)


class BundleTooLargeError(RuntimeError):
    """单条语句超过硬上限(近距离逼近 D1 的 SQLITE_TOOBIG) ⇒ 生成阶段直接失败。"""


def utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


class Bundle:
    """按顺序累积 SQL 语句, 提供字节封顶的分批 INSERT 与统计/断言/写盘。"""

    def __init__(self, max_stmt_bytes: int = DEFAULT_MAX_STMT_BYTES,
                 assert_max_bytes: int = DEFAULT_ASSERT_MAX_BYTES):
        if max_stmt_bytes <= 0 or assert_max_bytes <= 0:
            raise ValueError("字节上限必须为正数")
        if max_stmt_bytes > assert_max_bytes:
            raise ValueError(
                "软上限(%d)不能大于硬上限(%d)" % (max_stmt_bytes, assert_max_bytes))
        self.max_stmt_bytes = max_stmt_bytes
        self.assert_max_bytes = assert_max_bytes
        self.statements: list[str] = []
        self.sizes: list[int] = []
        self.insert_statements = 0
        self.oversize_single_row = 0

    # ---------- 语句累积 ----------
    def add(self, statement: str) -> None:
        """加一条**完整**语句(自带结尾分号)。"""
        stmt = statement.rstrip()
        if not stmt.endswith(";"):
            stmt += ";"
        self.statements.append(stmt)
        self.sizes.append(utf8_len(stmt))

    def add_inserts(self, head: str, rows: list[str],
                    delete_stmt: str | None = None) -> None:
        """把若干「一行值元组 SQL」按字节软上限贪心装箱成多条 INSERT。

        head        : `INSERT INTO t (a, b) VALUES`(不含换行/分号)
        rows        : 每个元素形如 `('x', 1, NULL)`
        delete_stmt : 可选, 作为**第一条数据语句**插在最前(如 `DELETE FROM t;`)

        空行集**先报错、且不把 DELETE 入队**(2026-10-26 审查 L2): 否则调用方一旦
        吞掉异常继续写盘, 就会产出一个「只有 DELETE、没有 INSERT」的包 —— 导入即
        清空线上表。本模块从结构上让这种情况产不出半成品。
        """
        if not rows:
            raise ValueError("add_inserts 收到空行集: 生成段应在此之前报错, 不应静默产出空包")
        if delete_stmt:
            self.add(delete_stmt)
        batch: list[str] = []

        def flush() -> None:
            stmt = head + "\n" + ",\n".join(batch) + ";"
            size = utf8_len(stmt)
            if len(batch) == 1 and size > self.max_stmt_bytes:
                # 单行本身超软上限: 已独立成句(不与任何其他行混), 记数供日志告警
                self.oversize_single_row += 1
            self.statements.append(stmt)
            self.sizes.append(size)
            self.insert_statements += 1

        for row in rows:
            if not batch:
                batch.append(row)
                continue
            if self._insert_bytes(head, batch + [row]) > self.max_stmt_bytes:
                flush()
                batch = [row]
            else:
                batch.append(row)
        flush()

    @staticmethod
    def _insert_bytes(head: str, rows: list[str]) -> int:
        """精确预算: head + '\\n' + ',\\n'.join(rows) + ';' 的 UTF-8 字节数。"""
        return (utf8_len(head) + 1
                + sum(utf8_len(r) for r in rows)
                + 2 * (len(rows) - 1)
                + 1)

    # ---------- 统计 / 断言 / 写盘 ----------
    def max_stmt_bytes_actual(self) -> int:
        return max(self.sizes) if self.sizes else 0

    def total_bytes(self) -> int:
        # 语句之间用一个换行连接, 末尾一个换行
        if not self.statements:
            return 0
        return sum(self.sizes) + (len(self.statements) - 1) + 1

    def text(self) -> str:
        return "\n".join(self.statements) + "\n" if self.statements else ""

    def assert_limits(self) -> None:
        worst = self.max_stmt_bytes_actual()
        if worst >= self.assert_max_bytes:
            worst_idx = self.sizes.index(worst) + 1
            snippet = ""
            for stmt, size in zip(self.statements, self.sizes):
                if size == worst:
                    snippet = stmt[:200].replace("\n", " ")
                    break
            raise BundleTooLargeError(
                "单条 SQL 语句 %d 字节 ≥ 硬上限 %d 字节(第 %d 条语句)。"
                "Cloudflare D1 单语句上限 100,000 字节, 超限报 statement too long: "
                "SQLITE_TOOBIG(整个导入包会失败)。常见成因: 某只基金的长文本字段"
                "(strategy/benchmark_text 等)过长。请定位该行并缩短/拆分字段, "
                "不要直接调高上限。语句开头: %s" % (worst, self.assert_max_bytes, worst_idx, snippet))

    def write(self, path) -> int:
        """写盘(显式 newline='\\n', 保证跨平台字节数可复现); 返回文件字节数。"""
        data = self.text()
        with open(os.fspath(path), "w", encoding="utf-8", newline="\n") as f:
            f.write(data)
        return utf8_len(data)

    def stats(self) -> dict:
        return {
            "statements": len(self.statements),
            "insert_statements": self.insert_statements,
            "total_bytes": self.total_bytes(),
            "max_stmt_bytes": self.max_stmt_bytes_actual(),
            "soft_cap_bytes": self.max_stmt_bytes,
            "hard_cap_bytes": self.assert_max_bytes,
            "oversize_single_row_stmts": self.oversize_single_row,
        }