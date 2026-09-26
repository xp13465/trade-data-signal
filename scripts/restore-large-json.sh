#!/bin/bash
# restore-large-json.sh —— 从 R2 私有桶 signal-backup large-json/ 前缀恢复大 JSON 快照
#
# 背景：7 个 >20MB 的 JSON(共 319MB)已移出 staticdata 备份 git(天天变化把备份变更量
#       顶到 >300MB 阈值导致天天 skip_oversize 不 commit)，改走 R2 私有桶 signal-backup
#       的 large-json/ 前缀版本化快照(gz 压缩，保留档位 = 日 14 天 + 周(周日)8 周 + 月(1号)12 月)。
#       staticdata 仓库只留小文件 + 上传/恢复脚本；需要还原本地文件用本脚本一键拉回。
# 用法：
#   bash scripts/restore-large-json.sh --list
#     列出 signal-backup 桶 large-json/ 下所有可用快照(按日期分组,显示每个日期有哪些文件+大小)。
#   bash scripts/restore-large-json.sh <文件名>
#     单个还原：默认取该文件最新快照,写回 <目标目录>/<原相对路径>。
#     例：bash scripts/restore-large-json.sh signal_kelly_trades.json
#         → <目标目录>/signal_kelly_trades.json
#     例：bash scripts/restore-large-json.sh signal_kelly_trades_parts/t2025.json
#         → <目标目录>/signal_kelly_trades_parts/t2025.json
#   bash scripts/restore-large-json.sh --date YYYY-MM-DD
#     还原该日期全部快照(也支持 --date=YYYY-MM-DD 等号形式)。
#   bash scripts/restore-large-json.sh --all
#     还原最新日期那一份的全部文件。
#   [--target <dir>] 可加在任意位置显式指定目标目录(默认见下)。
# 恢复目标：默认 = $STATICDATA_REPO/data/(环境变量 STATICDATA_REPO 仅测试用,缺省
#   /Users/linhuichen/code/trade-data)= 生产数据目录 trade-data/data/(用户 2026-09-25
#   拍板默认)——这些大 JSON 的生产"家"就是 trade-data/data,git 不再跟踪它们,但恢复
#   回生产原位最直接,与 db.py/export.py 读的库同源,不随 cwd 漂移。
#   ⚠️ 非默认目标目录(覆盖了 STATICDATA_REPO 或传 --target)会打印醒目警告：可能是
#   别的目录,直接覆盖有风险,测试临时目录也应看清再继续。
# 依赖：python3(调 scripts/upload_r2.py 的 s3_request,SigV4 签名+凭证复用,不新起连接)。
#       凭证从 .env / 环境变量读(upload_r2 模块 import 时 load_env)。
# 输出：<目标目录>/<原相对路径>(先下同目录 .tmp 再 os.replace 原子覆盖,读侧要么旧完整要么新完整;
#       覆盖前旧文件备份为 <文件>.bak-<时间戳>(copy2 副本,旧文件在原子替换前始终在位,无短暂缺失窗口);
#       gzip 解压;若 docs/large-json-backup-manifest.md 有该完整 R2 key(含日期)的 sha256 则比对,
#       不匹配即中止(中止发生在备份旧文件之前,不碰原文件))。
# 安全：只读 signal-backup 桶 large-json/ 前缀(GET/LIST)，绝不写、绝不删除 R2 上任何对象。
#       恢复写入前校验 rel 路径(非空/不含 .. 段/不以 / 开头/realpath 落在目标根内),非法跳过并汇总。
# 复现命令：见 docs/large-json-backup-manifest.md 与 docs/backup-restore.md「八、大 JSON 私有桶备份与恢复」。

set -euo pipefail
cd "$(dirname "$0")/.."   # 定位到仓库根(供 scripts/ 模块导入与 docs/ 相对引用；恢复目标由 --target/STATICDATA_REPO 决定)

MODE="${1:-}"
if [ -z "$MODE" ]; then
  echo "用法: bash scripts/restore-large-json.sh <文件名|--list|--date YYYY-MM-DD|--all> [--target <dir>]" >&2
  echo "  例: bash scripts/restore-large-json.sh signal_kelly_trades.json" >&2
  exit 2
fi

# 全部逻辑走 python(复用 upload_r2.s3_request 签名/凭证；文件级原子写/备份/校验也在此闭环)。
# --list 只读查询；单文件/--date/--all 只读 R2 + 写本地目标目录。
python3 - "$@" <<'PYEOF'
import sys, gzip, os, re, hashlib, shutil, datetime, urllib.parse

# stdout 重定向到文件时块缓冲,会与 stderr 输出顺序颠倒(skipped 汇总跑到进度前),强制行缓冲
sys.stdout.reconfigure(line_buffering=True)

# 恢复侧快速失败：覆盖默认 30s 为更短超时(网络不可达时快速报错,不吞分钟级)。
# ⚠️ 必须在 import upload_r2 之前设置(模块级常量在 import 时读取)；load_env() setdefault 不覆盖已设值。
# 用 min 而非 setdefault：若调用环境已有更大值(如云上 systemd 为上传设 600),恢复侧仍必须快速失败;
# 已有更小值(网络好想更快失败)则尊重。非法值回退 10。
try:
    _r2_tmo = int(os.environ.get("R2_UPLOAD_HTTP_TIMEOUT") or "10")
except ValueError:
    _r2_tmo = 10
os.environ["R2_UPLOAD_HTTP_TIMEOUT"] = str(min(_r2_tmo, 10))

try:
    sys.path.insert(0, "scripts")
    import upload_r2  # import 时 load_env() 载入凭证
except SystemExit as e:
    sys.exit(f"✗ 无法加载 R2 凭证模块(upload_r2): {e}")
except KeyError as e:
    sys.exit(f"✗ R2 凭证缺失(.env 缺 {e})：请确认 trade/.env 含 R2_S3_ENDPOINT / R2_S3_ACCESS_KEY_ID / R2_S3_SECRET_ACCESS_KEY")

BUCKET = upload_r2.BACKUP_BUCKET
PREFIX = "large-json/"
# 默认恢复根 = 生产数据目录(用户 2026-09-25 拍板；测试用 STATICDATA_REPO 覆盖,默认必须是生产目录)
DEFAULT_PRODUCTION_REPO = "/Users/linhuichen/code/trade-data"


def _list_all(prefix=PREFIX):
    """分页列出 prefix 下全部 (key, size_bytes)。list-type=2 超过 1000 用 continuation-token 续页。"""
    out = []
    token = ""
    while True:
        q = "list-type=2" + f"&prefix={urllib.parse.quote(prefix, safe='')}"
        if token:
            q += f"&continuation-token={urllib.parse.quote(token, safe='')}"
        try:
            status, data = upload_r2.s3_request("GET", "", query=q, bucket=BUCKET)
        except Exception as e:
            sys.exit(f"✗ 列出 {BUCKET}/{prefix} 网络调用失败(快速失败,已设 {os.environ.get('R2_UPLOAD_HTTP_TIMEOUT')}s 超时): {type(e).__name__}: {e}")
        if status != 200:
            sys.exit(f"✗ 列出 {BUCKET}/{prefix} 失败 status={status} {data.decode('utf-8', errors='replace')[:200]}")
        text = data.decode("utf-8", errors="replace")
        keys = re.findall(r"<Key>([^<]+)</Key>", text)
        sizes = re.findall(r"<Size>(\d+)</Size>", text)
        for k, s in zip(keys, sizes):
            out.append((k, int(s)))
        if "<IsTruncated>true</IsTruncated>" not in text:
            break
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
        if not m:
            break
        token = m.group(1)
    return out


def parse_key(key):
    """large-json/<date>/<rel>.gz -> (date, rel) 或 None(非本前缀/格式或路径非法)。
    路径安全第一道校验在此层：rel 非空、不以 / 开头、不含 .. 段、非绝对路径(P1-2 修复)。"""
    if not key.startswith(PREFIX):
        return None
    rest = key[len(PREFIX):]
    parts = rest.split("/", 1)
    if len(parts) != 2:
        return None
    date, rel_gz = parts
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return None
    if not rel_gz.endswith(".gz"):
        return None
    rel = rel_gz[:-3]
    if not rel or rel.startswith("/") or rel.startswith("\\"):
        return None
    norm = os.path.normpath(rel)
    if os.path.isabs(norm) or norm == ".." or norm.startswith(".." + os.sep):
        return None
    return (date, rel)


def load_manifest_sha():
    """读 docs/large-json-backup-manifest.md,返回 {完整 R2 key(含日期): sha256_hex}。
    map 键=完整 key,与 restore_one 查的 key 一一对应 —— 同 rel 不同日期各占一条,多日期快照
    不串日期(P1-1 修复)。文件缺失返回 {}；行内含 large-json/ key 且含 64-hex 才记
    (宽松,列格式由核心侧自动生成)。"""
    mp = "docs/large-json-backup-manifest.md"
    if not os.path.exists(mp):
        return {}
    text = open(mp, encoding="utf-8").read()
    m = {}
    for line in text.splitlines():
        if "large-json/" not in line:
            continue
        hs = re.findall(r"([0-9a-f]{64})", line)
        if not hs:
            continue
        for cell in [c.strip() for c in line.split("|")]:
            if cell.startswith(PREFIX):
                p = parse_key(cell)
                if p:
                    m[cell] = hs[0]  # 键=完整 R2 key(含日期+后缀)
    return m


def human(n):
    return f"{n/1024/1024:.1f}MB" if n >= 1024 * 1024 else f"{n/1024:.1f}KB"


def restore_one(date, rel, manifest_sha, target_root):
    """下载 large-json/<date>/<rel>.gz → 解压 → sha256 比对 → 备份旧文件 → 原子写回 <target_root>/<rel>。
    成功返回 None；任何需中止该对象的场景返回错误字符串(调用方汇总跳过清单,不中断其他文件)。"""
    key = f"{PREFIX}{date}/{rel}.gz"

    # 路径安全第二道(realpath 兜底,防 parse_key 漏网/未来改动)：解析后绝对路径必须落在目标根内
    out_path = os.path.join(target_root, rel)
    real_root = os.path.realpath(target_root)
    real_out = os.path.realpath(out_path)
    if not (real_out == real_root or real_out.startswith(real_root + os.sep)):
        return f"✗ 非法路径 rel={rel!r},目标 {real_out} 不在根目录 {real_root} 内,已跳过"

    try:
        status, data = upload_r2.s3_request("GET", key, bucket=BUCKET)
    except Exception as e:
        return f"✗ 下载网络调用失败 {BUCKET}/{key}(快速失败,已设 {os.environ.get('R2_UPLOAD_HTTP_TIMEOUT')}s 超时): {type(e).__name__}: {e}(已跳过,不中断其他文件)"
    if status != 200:
        return f"✗ 下载失败 {BUCKET}/{key} status={status}(已跳过,不中断其他文件)"
    try:
        payload = gzip.decompress(data)
    except Exception as e:
        return f"✗ gzip 解压失败 {key}: {e}"

    got = hashlib.sha256(payload).hexdigest()
    expect = manifest_sha.get(key)  # 完整 key(含日期)查 hash —— P1-1 修复,多日期不串
    if expect:
        if got != expect:
            return f"✗ sha256 不匹配 {key}: manifest={expect[:16]}… 实际={got[:16]}…,已中止(勿覆盖)"
        print(f"  sha256 ✓ {got[:16]}… 与 manifest 一致")
    else:
        print(f"  (manifest 无 {key} 记录,跳过 sha256 比对;本地 sha256 = {got[:16]}…)")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # 覆盖前备份旧文件(copy2 副本,旧文件在 os.replace 原子替换前始终在位,消除短暂缺失窗口)
    if os.path.exists(out_path):
        bak = f"{out_path}.bak-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(out_path, bak)
        print(f"  旧文件备份 → {bak}")

    # 原子写：先写同目录唯一 .tmp(pid+随机)再 os.replace(与 scripts/util_atomic.py 同语义,
    # 读侧要么旧完整要么新完整,绝不半截;os.replace 同分区原子替换;fsync 落盘防断电后指向空/截断)
    import random as _random
    tmp = f"{out_path}.{os.getpid()}.{_random.randint(100000, 999999)}.tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, out_path)
        os.chmod(out_path, 0o644)  # 新建文件默认受 umask 影响,统一修正为 0644 与现状产物一致
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    print(f"✓ 还原 {key} ({human(len(data))} 网络) → {out_path} ({human(len(payload))})")
    return None


def parse_args(argv):
    """手写参数解析：--list / <文件名> / --date[=] YYYY-MM-DD / --all,可任意位置加 --target[=] <dir>。
    返回 (mode, payload, target_root)；冲突/缺参直接 sys.exit 清晰报错。"""
    default_root = os.path.join(os.environ.get("STATICDATA_REPO", DEFAULT_PRODUCTION_REPO), "data")
    target_root = default_root
    mode = None
    payload = None
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--target":
            if i + 1 >= len(argv):
                sys.exit("✗ --target 需要目录参数")
            target_root = argv[i + 1]
            i += 2
        elif a.startswith("--target="):
            target_root = a[len("--target="):]
            i += 1
        elif a == "--list":
            if mode is not None:
                sys.exit("✗ 参数冲突:只能指定一种模式(--list/文件名/--date/--all)")
            mode = "list"; i += 1
        elif a == "--all":
            if mode is not None:
                sys.exit("✗ 参数冲突:只能指定一种模式(--list/文件名/--date/--all)")
            mode = "all"; i += 1
        elif a == "--date":
            if mode is not None:
                sys.exit("✗ 参数冲突:只能指定一种模式(--list/文件名/--date/--all)")
            if i + 1 >= len(argv):
                sys.exit("✗ --date 需要 YYYY-MM-DD 参数")
            mode = "date"; payload = argv[i + 1]; i += 2
        elif a.startswith("--date="):
            if mode is not None:
                sys.exit("✗ 参数冲突:只能指定一种模式(--list/文件名/--date/--all)")
            mode = "date"; payload = a[len("--date="):]; i += 1
        elif a.startswith("-"):
            sys.exit(f"✗ 未知参数 {a}")
        else:
            if mode is not None:
                sys.exit("✗ 参数冲突:只能指定一种模式(--list/文件名/--date/--all)")
            mode = "single"; payload = a; i += 1
    if mode is None:
        sys.exit("✗ 缺少模式参数: <文件名|--list|--date YYYY-MM-DD|--all> [--target <dir>]")
    return mode, payload, target_root


mode, payload, target_root = parse_args(sys.argv)

if mode == "date":
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", payload):
        sys.exit(f"✗ 日期格式应为 YYYY-MM-DD,收到 {payload}")

# 非默认目标打印醒目警告(默认 = 当前 env 下 STATICDATA_REPO/data → 生产数据目录 trade-data/data)
default_root = os.path.join(os.environ.get("STATICDATA_REPO", DEFAULT_PRODUCTION_REPO), "data")
if target_root != default_root:
    print(f"⚠️ 警告:目标目录 = {target_root}", file=sys.stderr)
    print(f"   这不是默认的生产数据目录 trade-data/data(默认 {default_root})。", file=sys.stderr)
    print("   该目录可能是测试临时目录或别的位置,直接覆盖有风险,请确认后继续。", file=sys.stderr)

print(f"恢复目标目录: {target_root}")

all_items = _list_all()  # [(key, size), ...]

# 预解析一次(供 --list 计数、--all/--date/单文件匹配、非法对象跳过清单)
parsed_all = []      # [(key, size, (date, rel))]
bad_keys = []        # 本前缀但 parse_key 失败(格式/路径非法)
for key, size in all_items:
    p = parse_key(key)
    if p:
        parsed_all.append((key, size, p))
    elif key.startswith(PREFIX):
        bad_keys.append(key)

if mode == "list":
    by_date = {}
    for _key, size, p in parsed_all:
        by_date.setdefault(p[0], []).append((p[1], size))
    n_bad = len(bad_keys)
    extra = f",{n_bad} 个对象格式/路径非法已排除" if n_bad else ""
    print(f"{BUCKET}/{PREFIX} 可用快照(共 {len(all_items)} 个对象,其中 {len(parsed_all)} 个可用{extra}):")
    if not by_date:
        print("  (无可用快照)")
        sys.exit(0)
    for date in sorted(by_date, reverse=True):
        files = by_date[date]
        print(f"\n[{date}] {len(files)} 个文件:")
        for rel, size in sorted(files):
            print(f"  {human(size):>10}  {rel}")
    sys.exit(0)

# 恢复类模式(单文件/--date/--all):manifest 只读一次缓存(顺手修 8),逐文件 restore,收集跳过清单
manifest_sha = load_manifest_sha()

if mode == "all":
    dates = sorted({p[0] for _k, _s, p in parsed_all}, reverse=True)
    if not dates:
        sys.exit("✗ large-json/ 下无可用快照")
    target_date = dates[0]
    print(f"还原最新日期 {target_date} 全部文件:")
    target_pairs = [(target_date, p[1], key) for key, _s, p in parsed_all if p[0] == target_date]
elif mode == "date":
    target_date = payload
    items = [(key, p) for key, _s, p in parsed_all if p[0] == target_date]
    if not items:
        avail = sorted({p[0] for _k, _s, p in parsed_all}, reverse=True)
        sys.exit(f"✗ {target_date} 无可用快照;可用日期: {avail or '(无)'}")
    print(f"还原 {target_date} 全部 {len(items)} 个文件:")
    target_pairs = [(target_date, p[1], key) for key, p in sorted(items)]
else:  # single
    matches = []
    for key, _s, p in parsed_all:
        if p[1] == payload:
            matches.append((p[0], key))
    if not matches:
        sys.exit(f"✗ 未找到 {payload} 的快照;可先 --list 查看,或带相对路径(如 signal_kelly_trades_parts/t2025.json)")
    matches.sort(reverse=True)  # 日期降序,取最新
    date, key = matches[0]
    print(f"还原 {payload} 最新快照(日期 {date}):")
    target_pairs = [(date, payload, key)]

skipped = []
for date, rel, key in target_pairs:
    err = restore_one(date, rel, manifest_sha, target_root)
    if err:
        skipped.append((key, err))

for k in bad_keys:
    skipped.append((k, "✗ 对象格式/路径非法,已跳过"))
if skipped:
    print(f"\n⚠️ 共 {len(skipped)} 个对象被跳过:", file=sys.stderr)
    for key, err in skipped:
        print(f"  - {key}: {err}", file=sys.stderr)
    # 恢复不完整=失败：任何对象被跳过(网络失败/非法路径/sha 不匹配等)都以非 0 退出,
    # 让调用方(人工/定时)能感知恢复未完整完成,不静默当成功。
    sys.exit(1)
PYEOF
