#!/usr/bin/env python3
"""shadow_track_md.py - 把影子模式 JSON 渲染成项目下 md 追踪总表(用户直接可查,不做前端/命令看板)。

定义:影子模式 7 天验证期间,用户不敲命令、不开前端,直接打开 docs/ai-predict-shadow-track.md
就能跟踪每天影子 lean/依据/次日实际方向/是否命中。本模块把 data/brief_shadow.json(单一事实源,
含全部历史行,append/update 语义不丢历史)渲染为 md 追踪总表,双向维护(**维护 docs/ai-predict-shadow-track.md**):

  - gen_daily_brief.record_shadow 落盘当日影子后调用本模块 → md 出现当日行(lean/basis 有值,次日待回填)
  - aggregate_shadow._reconcile 回填 actual 后调用本模块 → md 当日行"次日实际/命中"列更新

幂等与不丢历史(§5.3 核心保留):md 完全由 JSON 全量重新渲染,JSON 是唯一事实源(从不删历史行)。
  - 重跑 gen_daily_brief/aggregate_shadow 只产生「新增当日行或回填当日列」的 md diff,不覆盖重建丢历史
  - 手改 md 会被下次运行重新渲染覆盖,勿手改(JSON 才是权威)。

用法:由 gen_daily_brief.py / aggregate_shadow.py 内部 import 调用;也可单独
  python scripts/shadow_track_md.py  (用 trade-data 部署源树的影子 JSON 直接渲染一次)
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

SHADOW_FILE = "brief_shadow.json"
TRACK_MD = "docs/ai-predict-shadow-track.md"

_HEADER = [
    "# AI 预测影子模式 7 天验证追踪总表(自动生成,勿手改)",
    "",
    "> 影子模式 = 线上输出完全不变,后台把「方向锚/归因会预测什么方向」按日旁路落盘,",
    "> 次日真实盘后回填实际方向,聚算命中率供拍板开/不开/改(契约见 "
    "`docs/ai-predict/ai-predict-shadow-validate-20260820.md`)。",
    "> 本表由 `data/brief_shadow.json` 自动渲染,每日维护两份落点(gen_daily_brief 当日写入 + "
    "aggregate_shadow 对账回填),**手改此 md 会被覆盖,以 JSON 为准**。",
    "",
]


def _load_shadow(shadow_path: Path) -> list[dict]:
    try:
        obj = json.loads(shadow_path.read_text(encoding="utf-8"))
        if isinstance(obj, list):
            return obj
    except Exception:
        pass
    return []


def _basis_one(basis: list) -> str:
    """basis 因子列表 → 一行摘要。"""
    if not basis:
        return "-"
    return "；".join(str(b) for b in basis)


def _hit_mark(lean: str, direction: str | None) -> str:
    """命中标记:flat 空转单列标注,不参与命中判定。"""
    if direction is None:
        return "-"  # 待回填
    if lean == "flat":
        return "空转(不计)"  # flat 无方向,命中意义弱,单列标注
    return "✅ 命中" if lean == direction else "❌ 未中"


def render_shadow_md(shadow_path: Path, track_md: Path) -> tuple[str, int]:
    """渲染 md 追踪总表并写盘。返回(写入路径文本, 当日/全部行数)。幂等:只反映 JSON 全量。"""
    rows = _load_shadow(shadow_path)
    # 按日期倒序(最新在前,用户一眼看到最近进度)——JSON 本身已按 date 旧→新追加
    rows_sorted = sorted(rows, key=lambda r: (r.get("date") or ""), reverse=True)

    lines = list(_HEADER)
    lines.append("| 日期 | 影子lean(方向) | 影子依据(basis) | 次日实际方向 | 命中? | 备注 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for r in rows_sorted:
        date = r.get("date") or "-"
        lean = r.get("pred_shadow") or "?"
        strength = r.get("strength") or ""
        lean_s = f"{lean}({strength})" if strength else lean
        basis = _basis_one(r.get("basis") or [])
        actual = r.get("actual") or {}
        direction = actual.get("actual_direction")
        direction_s = direction if direction is not None else "待回填"
        hit = _hit_mark(lean, direction)
        note = []
        if actual.get("next_date"):
            note.append(f"对比日={actual['next_date']}")
        if actual.get("actual_sh_pct") is not None:
            note.append(f"sh={actual['actual_sh_pct']:.2f}%")
        if not note:
            note.append("等待下一交易日回填")
        lines.append(f"| {date} | {lean_s} | {basis} | {direction_s} | {hit} | {'；'.join(note)} |")

    lines.append("")
    lines.append("## 说明")
    lines.append("")
    lines.append("- **这是什么**：影子模式把「方向锚/归因会预测什么方向」按日落盘，7 天验证期收集真实方向对账样本，"
                 "不注入线上、不改变任何线上输出。")
    lines.append("- **怎么维护的**：`gen_daily_brief` 当日记录影子 → md 当日行（lean/basis 有值，次日待回填）；"
                 "`aggregate_shadow` 次日回填实际 → md 当日行“次日实际/命中”更新。md 由 `data/brief_shadow.json` 全量渲染，幂等不覆盖历史。")
    lines.append("- **7 天后看哪个脚本聚算定论**：`python scripts/aggregate_shadow.py`（回填+聚算命中率并按 lean/因子分组），"
                 "把结果交给用户拍板影子模式开/不开/改。")
    lines.append("- **诚实标注**：影子探针样本稀疏（7 天验证期），命中率仅累积参考，**不构成显著统计意义**（§5.1 诚实标注）；"
                 "lean=flat 为无方向空转，单列标注不参与命中判定；实际方向以 `index_daily` 最新交易日 sh 涨跌幅按 "
                 "HIT_THRESHOLD=0.5 判定（与 `_actual_direction` 同口径）。")
    lines.append("")

    content = "\n".join(lines)
    track_md.parent.mkdir(parents=True, exist_ok=True)
    track_md.write_text(content, encoding="utf-8")
    return str(track_md), len(rows)


def update_shadow_track_md(repo_data_root: Path, git_repo_root: Path, silent: bool = False) -> int:
    """从部署源树 data/brief_shadow.json 渲染 md 到 git 仓库 docs/。返回行数(0=无记录)。"""
    shadow_path = repo_data_root / "data" / SHADOW_FILE
    track_md = git_repo_root / TRACK_MD
    if not shadow_path.exists():
        if not silent:
            print(f"[shadow_track_md] 影子文件不存在({shadow_path}),跳过 md 渲染。")
        return 0
    path_txt, n = render_shadow_md(shadow_path, track_md)
    if not silent:
        print(f"[shadow_track_md] 已渲染影子追踪 md({n} 行): {path_txt}")
    return n


def _resolve_roots() -> tuple[Path, Path]:
    """解析部署源树数据根 + git 仓库根。

    - git_root = 本脚本上级的上级(trade),md 写 trade/docs/ 用户可查且 git 跟踪
    - data_root = trade-data 部署源树(影子 JSON 写/读的单一事实源,launchd 主数据),
                带 REPO/GIT_REPO env 覆盖、回退 trade 侧(读旧镜像也能渲染)。
    """
    git_root = Path(__file__).resolve().parent.parent
    data_root = git_root
    import os
    for env_name in ("REPO", "GIT_REPO"):
        e = os.environ.get(env_name)
        if e and Path(e).resolve().is_dir():
            data_root = Path(e).resolve()
            break
    main_trade_data = Path("/Users/linhuichen/code/trade-data")
    if main_trade_data.exists():
        data_root = main_trade_data
    return data_root, git_root


if __name__ == "__main__":
    from pathlib import Path
    _dr, _gr = _resolve_roots()
    update_shadow_track_md(_dr, _gr, silent=False)
