#!/usr/bin/env python3
"""用 terser minify app.js / lab.js / common.js，用 rcssmin minify style.css / lab.css。

对 static-site/ 生成 *.min.js + style.min.css + lab.min.css（不生成 source map，防线上泄露源码）。
保留原文件供开发，min 版上线引用（index.html 引用 .min.js / .min.css）。
可重复运行覆盖。幂等。

用法：
  python scripts/build_min.py

依赖：
  - JS: npx terser（首次运行 npx --yes terser 自动下载缓存，无需项目内 npm install）
  - CSS: rcssmin（pip install rcssmin，纯 Python 轻量 CSS 压缩器；未装时 CSS 跳过不崩）

失败处理：任一文件 minify 失败则退出码 1，已成功的文件仍保留。
  缺源/缺 rcssmin 视为跳过（非失败，退出码 0）。

deploy.sh 会在 export.py 后调用本脚本，确保上线前 min 文件总是新鲜。

【2026-08-18 B1 根治：min 源从 git HEAD 读，防脏工作区覆盖（16:30 事故）】
背景：某 agent 用 `git reset --soft` 只移 HEAD 没动工作区 → 工作区源停在旧版（M 脏）→ deploy.sh
安全网跑本脚本读工作区旧源 → 生成旧版 min → push 上 main 覆盖正确版。
根治：生成 min 的源一律优先从 **git HEAD** 读取（`git -C <repo> show HEAD:<相对路径>`），
工作区脏文件永远影响不了生成的 min。
- git 仓库路径解析：优先环境变量 GIT_REPO（deploy.sh 调用时传入）；否则检测 BASE 自身是否 git 仓库。
- git show 失败（非 git 环境 / 文件首次未 commit 到 HEAD）时 fallback 回读工作区源（保持原行为不崩），
  但打告警日志（"回退工作区"提示）。
"""
import os
import subprocess
import sys
import tempfile

# rcssmin 延迟导入（minify_css 内 try/except）：trade-data 的采集 venv 可能没装 rcssmin，
# 此时 CSS minify 跳过（不崩，与"缺源跳过"同理），JS 仍走 terser 不受影响。
# deploy.sh 视 build_min 失败为非阻断，但跳过可消除噪音 + 退出码 0。

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (源相对路径, 目标相对路径) -- 顺序：common 先于 app/lab（common.js 是公共函数库，app.js/lab.js 依赖 window._labCustom*）
# CSS 放最后（独立，与 JS 无依赖；terser 不可用时 CSS 仍能压缩，不受影响）
PAIRS = [
    ("static-site/common.js", "static-site/common.min.js"),
    ("static-site/purpose-notes.js", "static-site/purpose-notes.min.js"),
    ("static-site/kelly-review-notes.js", "static-site/kelly-review-notes.min.js"),
    ("static-site/kelly-reports-content.js", "static-site/kelly-reports-content.min.js"),
    ("static-site/app.js", "static-site/app.min.js"),
    ("static-site/lab.js", "static-site/lab.min.js"),
    ("static-site/style.css", "static-site/style.min.css"),
    ("static-site/lab.css", "static-site/lab.min.css"),
]


def _resolve_git_repo():
    """返回 git 仓库根路径，或 None。

    优先级：环境变量 GIT_REPO（deploy.sh 从 trade-data 跑时传 trade 仓库）→ 检测 BASE 自身是否 git 仓库
    （build_min.py 在 trade 本地跑时，BASE=trade，直接可用）。返回前校验仓库确实存在 .git。
    """
    env = os.environ.get("GIT_REPO")
    if env and os.path.isdir(os.path.join(env, ".git")):
        return env
    try:
        r = subprocess.run(
            ["git", "-C", BASE, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            top = r.stdout.strip()
            if top and os.path.isdir(os.path.join(top, ".git")):
                return top
    except Exception:
        pass
    return None


def _read_source(src_rel, base=BASE, repo=None):
    """读源内容：优先从 git HEAD（根治脏工作区覆盖），失败 fallback 工作区文件。

    base: 工作区源目录根（默认 build_min.BASE）；repo: git 仓库根（默认自动解析）。
    返回 (content_bytes, source_desc)：
      - git HEAD 成功: (bytes, "git HEAD")
      - git 仓库存在但 git show 失败(文件未 commit 到 HEAD): (worktree_bytes, "worktree[git show失败回退]") 并告警
      - 非 git 环境: (worktree_bytes, "worktree")  # 首次部署无 git，正常
      - 源彻底不存在: (None, None)
    """
    if repo is None:
        repo = _resolve_git_repo()
    if repo:
        try:
            r = subprocess.run(
                ["git", "-C", repo, "show", f"HEAD:{src_rel}"],
                capture_output=True, timeout=60,
            )
            if r.returncode == 0:
                return r.stdout, f"git HEAD ({repo})"
            # git show 失败（如新文件首次未 commit 到 HEAD）→ fallback 工作区 + 告警
            print(f"  · 告警: {src_rel} 不在 git HEAD，回退读工作区源（新文件未 commit?）")
        except Exception as e:
            print(f"  · 告警: git show {src_rel} 异常({e})，回退读工作区源")
    # fallback 工作区
    path = os.path.join(base, src_rel)
    if not os.path.exists(path):
        return None, None
    with open(path, "rb") as f:
        return f.read(), f"worktree ({path})"


def _check_terser():
    """确认 npx terser 可用，返回版本字符串或 None。"""
    r = subprocess.run(
        ["npx", "--yes", "terser", "--version"],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def _print_result(src_rel, dst_rel, src_sz, dst_sz):
    """打印单个文件 minify 成功结果。src_sz 为源内容字节数（git HEAD 或工作区）。"""
    pct = (1 - dst_sz / src_sz) * 100 if src_sz else 0
    print(f"  ✓ {src_rel} ({src_sz:,}B) -> {dst_rel} ({dst_sz:,}B, -{pct:.1f}%)")
    return True


def _minify_js_content(content: bytes, src_name: str):
    """对 JS 内容跑 terser minify（不生成 source map，防线上泄露源码），返回 min bytes。

    content 来自 git HEAD（或 fallback 工作区）。在临时目录跑 terser（输入/输出均在临时目录，
    只处理传入的 content，不读工作区 src 文件），最后返回 min 内容字节。
    返回 None 表示 terser 失败。
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_src = os.path.join(tmp, src_name)
        tmp_dst_name = "out.min.js"
        with open(tmp_src, "wb") as f:
            f.write(content)
        # terser 在临时目录内运行：输入 src_name -> 输出 tmp_dst_name（无 sourceMappingURL 注释、无 .map）
        # 2026-08-15 P0 mangle 根治(防 "c is not a function" 系统性冲突):
        #   terser mangle 用"最短名池"($,_,A,B,...a,b,...)重命名局部标识符, 大型压缩文件(37+处用 $ 作普通变量)
        #   会撞车——函数被改名成单字符与既有变量遮蔽 → 运行时出现单字符函数调用冲突(曾 "$ is not a function",
        #   加 reserved=['$'] 又把 _isSellSig 改名转成 C/c, 打地鼠)。根治配置:
        #   ① keep_fnames: 保留所有真函数名(函数声明/命名字函数名不参与 mangle), 整类消除"函数被改名单字符撞变量";
        #   ② 首页关键 const-arrow 布尔助手已改 function 声明(_isSellSig/_isSellRow/_isAiFadeHit): 单语句被 compress
        #      内联掉, 多语句被 keep_fnames 保名, 二者都不留可撞车的单字符函数调用。
        #   ⚠️ keep_fnames 不保护 const x = ()=>{} 这种箭头绑定(已实证 rename 照旧), 故新增布尔助手应写 function 声明。
        # 不再用 reserved=['$'](打地鼠, 只把冲突转移); keep_fnames + fn声明 从机制上根治。
        cmd = [
            "npx", "--yes", "terser", src_name,
            "--compress", "--mangle", "keep_fnames",
            "-o", tmp_dst_name,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp, timeout=300)
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()[:400]
            return None, err
        with open(os.path.join(tmp, tmp_dst_name), "rb") as f:
            return f.read(), None


def _minify_css_content(content: bytes):
    """对 CSS 内容用 rcssmin 压缩（去 /* */ 注释/多余空白/合并，不改 CSS 规则），返回 min bytes。"""
    import rcssmin
    return rcssmin.cssmin(content.decode("utf-8")).encode("utf-8")


def build_pairs_in_memory(base=BASE, repo=None):
    """对全部 PAIRS 从 git HEAD（fallback 工作区）读源并生成 min，返回 {dst_rel: min_bytes}。

    供 main 写文件与 check_version_consistency.py 内容校验复用（B2：同一套生成逻辑，杜绝两处算法分叉）。
    base: 工作区源目录根（默认 build_min.BASE）；repo: git 仓库根（默认自动解析）。
    返回 dict；单个文件生成失败/缺源跳过的不在 dict 中。告警在内部打印。
    """
    out = {}
    for src_rel, dst_rel in PAIRS:
        content, _desc = _read_source(src_rel, base=base, repo=repo)
        if content is None:
            # 缺源跳过（非失败）：trade-data 架构下 static-site/app.js 等源不在采集仓库，
            # build_min 作为 deploy 的安全网，缺源不应致退出码 1。返回 None 区别 minify 真失败。
            print(f"  · 跳过（源不存在）：{src_rel}")
            continue
        try:
            if src_rel.endswith(".css"):
                min_content = _minify_css_content(content)
            else:
                min_content, terser_err = _minify_js_content(content, os.path.basename(src_rel))
                if min_content is None:
                    print(f"  ✗ terser 失败 [{src_rel}]: {terser_err}")
                    continue
        except ImportError:
            print(f"  · 跳过 CSS（rcssmin 未装）：{src_rel}")
            continue
        out[dst_rel] = min_content
        _print_result(src_rel, dst_rel, len(content), len(min_content))
    return out


def main():
    print("=== build_min: JS(terser) + CSS(rcssmin) ===")
    repo = _resolve_git_repo()
    if repo:
        print(f"  min 源来源: git HEAD ({repo})   [B1 根治: 工作区脏文件不影响 min]")
    else:
        print("  min 源来源: 工作区 (非 git 环境，无 git HEAD 可读，保持原行为)")
    has_js = any(src.endswith(".js") for src, _ in PAIRS)
    if has_js:
        ver = _check_terser()
        if not ver:
            print("✗ terser 不可用（npx --yes terser --version 失败）")
            print("  排查：npx 是否在 PATH、是否联网首次下载 terser")
            return 1
        print(f"  terser {ver} 可用")

    out = build_pairs_in_memory()
    if not out:
        print("✗ 无任何文件生成成功")
        return 1
    for dst_rel, content in out.items():
        dst = os.path.join(BASE, dst_rel)
        with open(dst, "wb") as f:
            f.write(content)

    print(f"完成（built={len(out)}）。记得跑 bump_asset_version.py 刷新 ?v= 版本号。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
