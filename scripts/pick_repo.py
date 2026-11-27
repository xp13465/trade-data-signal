#!/usr/bin/env python3
"""pick_repo.py - 部署源树(写/上传)与 git 仓统一 helper(防再犯机制 E, 2026-08-18)

背景(2026-08-18 冲突覆盖根因报告 docs/conflict-overwrite-rootcause-2026-08-18.md #3/#4):
  项6/fetch_news 两次「写部署源树路径错」——upload 子进程用 env.setdefault("REPO",...) 不覆盖
  已有值, 导致按 env.REPO=trade-data 拼错源目录(旧实体目录), deploy rsync 反覆盖线上。
  根因: 各脚本各自实现 REPO 解析(重复 pick_repo), 且子进程 env 用 setdefault 不强制覆盖,
  部署链读到与写入位置不一致的目录 → rsync clobber。

本模块统一「部署源树/上传源树」repo 解析, 所有写部署源树 + R2 上传 + staticdata 同步入口统一走它:
  - pick_repo():  部署源树(trade-data, launchd 主数据/上传源树), 写 static-site/data 的目标
  - data_root():  数据根(读侧唯一权威入口, #384): env REPO(读侧守卫) → 布局派生
  - sentiment_db(): 部署数据树的 sentiment.db 单源(<repo>/data/sentiment.db), 供各读者统一调用
  - code_root():  代码根(env GIT_REPO → 脚本所在仓库; #384 从 pick_git_repo 抽名)
  - pick_git_repo(): trade git 仓库(deploy.sh commit/push 目标, 兼容保留 = code_root())
  - force_env():  env 强制覆盖 REPO/GIT_REPO(不用 setdefault), 确保子进程解析到同一 repo
  - guard_deploy_source_tree(): 写源树守卫——目标必须 = trade-data(上传源树), 误写 trade(git 仓)
    即报错(§23.11 发现问题绝不静默, 立即阻断, 不静默继续)。

目录语义:
  - trade-data(/Users/linhuichen/code/trade-data) = 部署源树/上传源树(launchd 主数据, 非 git 仓)
  - trade(/Users/linhuichen/code/trade) = git 仓库(deploy.rsync trade-data -> trade, commit+push)
  - 云上单仓(/home/ubuntu/code/trade-data-signal, REPO=GIT_REPO 同路径): 部署源树 == git 仓,
    MAIN_REPO/REPO/GIT_REPO 均由 env 注入同一路径, guard 单仓判定直接放行(2026-09-12)。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# ── 两个根(#384 批1, 2026-11-27) ──────────────────────────────────────────────
# 代码根 CODE_ROOT = 本仓物理路径(resolve, 恒折叠 symlink);
# INVOKED_ROOT = 实际被调用的路径(absolute, 不折叠 —— 经 <数据根>/scripts symlink 调用时 = 数据根)。
# 两者对应 bash scripts/lib/repo_paths.sh 的 _real_dir / _raw_dir, 派生算法严格同构(§1.3)。
CODE_ROOT = Path(__file__).resolve().parent.parent      # trade/scripts/pick_repo.py -> trade
INVOKED_ROOT = Path(__file__).absolute().parent.parent  # 经 trade-data/scripts symlink 调用 -> trade-data
# git 仓库: deploy.sh commit/push 目标(兼容旧名; candidate_repos 消费, 冻结不动)
GIT_REPO_DEFAULT = CODE_ROOT


def _derive_data_root(code_root: Path | str, invoked_root: Path | str) -> Path:
    """按布局确定性推导数据根(#384 §1.3, 与 scripts/lib/repo_paths.sh:43-76 严格同构)。

    候选 A: 经 <数据根>/scripts symlink 调用 —— 前提 = scripts 目录**本身**是 symlink
            (#208 修正: 祖先 symlink 不算, 否则误判为 A 静默推出代码根);
    候选 B: 代码根的兄弟目录 trade-data 存在 → 该兄弟目录;
    回退:   代码根本身(真单仓)。
    """
    code = Path(code_root)
    invoked = Path(invoked_root)  # 不 resolve: A 候选靠 absolute 路径与 scripts symlink 识别
    if (invoked / "scripts").is_symlink() and invoked.resolve() != code.resolve():
        return invoked
    sibling = code.parent / "trade-data"
    if sibling.is_dir():
        return sibling
    return code


def code_root() -> Path:
    """代码根: env GIT_REPO 有效目录优先, 否则脚本所在仓库(原 pick_git_repo body)。"""
    env_g = os.environ.get("GIT_REPO", "").strip()
    if env_g:
        p = Path(env_g).resolve()
        if p.is_dir():
            return p
    return CODE_ROOT.resolve()


_DERIVED_DATA_ROOT = _derive_data_root(CODE_ROOT, INVOKED_ROOT)

# 部署源树(上传源树, 非 git 仓): launchd/update_all 写主数据的位置。
# #384 批1: 默认由布局派生(原为写死 mac 路径 —— Linux 无 env 时该路径不存在, candidate_repos
# 退化到代码仓陈旧库); env MAIN_REPO 仍最高优先。
MAIN_REPO = Path(os.environ.get("MAIN_REPO", "").strip() or str(_DERIVED_DATA_ROOT))


def candidate_repos() -> list[Path]:
    """候选 repo 列表(去重, 保序): env 注入(REPO/GIT_REPO)优先, 再 MAIN_REPO, 再 git 仓。

    云上单仓(REPO=GIT_REPO)下 env 注入的 repo 排最前; 本机双仓无 env 时顺序
    = MAIN_REPO(trade-data) → git 仓(trade), 行为不变。"""
    out: list[Path] = []
    for c in ([os.environ.get("REPO", ""), os.environ.get("GIT_REPO", ""),
               str(MAIN_REPO), str(GIT_REPO_DEFAULT)]):
        if not c:
            continue
        p = Path(c).resolve()
        if p not in out:
            out.append(p)
    return out


def pick_git_repo() -> Path:
    """返回 trade git 仓库(env GIT_REPO 优先, 否则脚本所在仓库)。兼容保留, 委托 code_root()。"""
    return code_root()


def pick_repo() -> Path:
    """部署源树(写/上传)repo。

    云上单仓/显式 REPO env 注入时直接信任 env 指定仓(不按 date 猜, 防回退到 macOS 硬编码仓);
    无 env 时挑 static-site/data/overview.json.date 最新者(本机双仓老路径, 同日期优先 trade-data)。

    launchd/update_all 从 trade-data(部署源树)跑, 手动从 trade 跑。写 + R2 上传 + staticdata
    同步统一落到本函数选中的同一树, 保证部署链读到新版不 clobber(2026-08-18 断点根因)。
    仅当 trade-data 不存在/不可用时才回退其他候选(dev 环境无 trade-data)。"""
    env_repo = os.environ.get("REPO", "").strip()
    if env_repo:
        p = Path(env_repo).resolve()
        if p.is_dir():
            return p
    best, best_date = None, ""
    for r in candidate_repos():
        ov = r / "static-site" / "data" / "overview.json"
        if not ov.exists():
            continue
        d = _read_overview_date(ov)
        if d > best_date:  # 严格大于: 同日期保留先出现者(env/trade-data 在前)
            best_date, best = d, r
    if best is None:
        best = candidate_repos()[0]
    return best


def data_root() -> Path:
    """数据根(读侧唯一权威入口, #384 §1.3/§1.4, 2026-11-27)。

    与写侧 pick_repo() 的分工: pick_repo() 是「写/上传哪棵树」的既有契约(按 overview 日期选,
    冻结不动); data_root() 是「读哪棵数据树」的确定性推导 —— 不猜日期、不把代码仓当数据候选。

    env REPO 有效目录 → 经读侧守卫(复用 guard_deploy_source_tree 同一判据)后采用;
    否则按布局派生(候选 A symlink / 候选 B 兄弟 trade-data / 单仓回退代码根)。

    §1.4 读侧守卫: env REPO 解析到代码仓、而独立部署树存在 → SystemExit(响亮失败)。
    为什么不在错配时 warn 放行: 放行仍会读到代码仓里的陈旧库(= 静默用坏数据, §23.11)。
    """
    env_repo = os.environ.get("REPO", "").strip()
    if env_repo:
        p = Path(env_repo)
        if p.is_dir():
            return guard_deploy_source_tree(p)
    return _derive_data_root(CODE_ROOT, INVOKED_ROOT)


def sentiment_db(repo: Path | None = None) -> Path:
    """部署数据树单源 sentiment.db 路径(2026-11-27 #383; 默认根 #384 改走 data_root())。

    返回 (repo 显式指定 或 data_root()) / "data" / "sentiment.db" —— 只认部署数据树,
    不再遍历候选仓逐个打开 MAX(date) 挑最新。根因: candidate_repos() 把 git 仓
    (GIT_REPO/GIT_REPO_DEFAULT)也当数据候选, 云上 C(trade-data-signal)是 10-28 起冻结的
    陈旧镜像, 每日被各读者只读打开(刷新 -shm); 且 C 与 mac 镜像同旧, 镜像兜底=喂 1 个月旧数据。
    库缺失/损坏时返回路径本身, 由调用方 sqlite3.connect(mode=ro) 响亮报错(不再静默回退旧库)。
    """
    return (repo if repo is not None else data_root()) / "data" / "sentiment.db"


def _read_overview_date(ov: Path) -> str:
    import json
    try:
        return str(json.loads(ov.read_text(encoding="utf-8")).get("date", ""))
    except Exception:
        return ""


def _alert_guard_blocked(msg: str) -> None:
    """守卫阻断时主动告警(飞书/邮件, 参考 scripts/notify.py CLI)。

    P3-1 增强(2026-08-19): guard 触发 SystemExit 阻断时, launchd 下仅 stderr traceback 进日志,
    可能静默失败一段时间。这里调 notify.py 发告警; 告警本身失败不阻断阻断逻辑(§23.11
    阻断是主, 告警是辅——不能因告警失败而放行阻断, 也不能因告警异常反伤主流程)。"""
    script = Path(__file__).resolve().parent / "notify.py"
    subject = "[防再犯E守卫] 写部署源树目标错误(SystemExit 阻断)"
    try:
        subprocess.run(
            [sys.executable, str(script), subject, msg, "--severe"],
            capture_output=True, timeout=60,
        )
    except Exception:
        # 告警失败不阻断阻断本身(不影响 SystemExit 已触发的阻断语义)
        pass


def _is_single_repo() -> bool:
    """单仓判定: 部署源树 == git 仓(无 trade/trade-data 之分)。

    云上单仓(REPO=GIT_REPO 同路径)或 MAIN_REPO env 直接指向 git 仓时成立;
    此时写 git 仓即写源树, 无需守卫误写拦截。

    单仓判定必须排除「独立源树 trade-data 仍存在」的情况(2026-09-12 F1):
    macOS 双仓下 REPO=GIT_REPO=trade 若 trade-data 仍在, 仍是误写 git 仓, 不算单仓。"""
    repo = os.environ.get("REPO", "").strip()
    git = os.environ.get("GIT_REPO", "").strip()
    if (repo and git and Path(repo).resolve() == Path(git).resolve()
            and (MAIN_REPO.resolve() == Path(git).resolve() or not MAIN_REPO.exists())):
        return True
    return MAIN_REPO.resolve() == pick_git_repo().resolve()


def guard_deploy_source_tree(repo: Path | str) -> Path:
    """写源树守卫(§23.11): 写部署源树的目标必须 = trade-data(上传源树)。

    若解析出的 repo == trade(git 仓) 而 trade-data 存在 → 误写 git 仓(会把 trade-data 新版
    clobber 回旧版的老 bug), 立即报错阻断, 绝不静默继续。返回规范化 repo(合法时)。
    云上单仓(部署源树 == git 仓)下写 git 仓即写源树, 直接放行。
    """
    repo = Path(repo).resolve()
    git = pick_git_repo().resolve()
    # 只有「解析到 git 仓」才需要守卫检查; 若本来就是 trade-data 或非 git 仓目录, 直接放行
    if repo != git:
        return repo
    # 单仓(部署源树 == git 仓): 写 git 仓即写源树, 无需误写拦截
    if _is_single_repo():
        return repo
    # repo == git 仓(trade): 若 trade-data(部署源树)存在, 则本次写目标是 git 仓 = 误写
    trade_data = MAIN_REPO.resolve()
    if trade_data.exists() and trade_data.is_dir():
        msg = (
            f"✗ 写部署源树目标错误: pick_repo() 解析到 git 仓 {git}(/trade), 而非部署源树 "
            f"{trade_data}(/trade-data)。误写 git 仓会导致 deploy rsync 把 trade-data 新版 "
            f"clobber 回旧版(2026-08-18 断点根因, §23.11 发现问题绝不静默)。"
            f"请检查 REPO/GIT_REPO 环境变量与数据写入逻辑。"
        )
        _alert_guard_blocked(msg)
        raise SystemExit(msg)
    # trade-data 不存在(dev 环境) → 回退 git 仓合法
    return repo


def force_env(env: dict, repo: Path | str, git_repo: Path | str | None = None) -> dict:
    """env 强制覆盖 REPO/GIT_REPO(不用 setdefault, 同 fetch_news 818 根修)。

    子进程(upload_r2/staticdata_sync)常因 env 已有值而 setdefault 不覆盖 → 解析到与写入位置
    不一致的目录(读旧版/读空目录)。这里强制覆盖, 确保上传/staticdata 源目录 = 写部署源树。
    """
    repo = guard_deploy_source_tree(repo)
    env = dict(env)
    env["REPO"] = str(repo)
    env["GIT_REPO"] = str(git_repo if git_repo is not None else pick_git_repo())
    return env


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="打印部署源树/git 仓 repo(防再犯机制 E 统一 helper)")
    ap.add_argument("--mode", choices=["deploy", "git"], default="deploy",
                    help="deploy=部署源树(写/上传, 默认); git=git 仓库")
    args = ap.parse_args()
    if args.mode == "git":
        print(pick_git_repo())
        return 0
    try:
        r = guard_deploy_source_tree(pick_repo())
    except SystemExit as e:
        print(str(e), file=os.sys.stderr)
        return 1
    print(r)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
