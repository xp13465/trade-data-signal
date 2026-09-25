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
#     单个还原：默认取该文件最新快照,写回 data/<原相对路径>。
#     例：bash scripts/restore-large-json.sh signal_kelly_trades.json
#         → data/signal_kelly_trades.json
#     例：bash scripts/restore-large-json.sh signal_kelly_trades_parts/t2025.json
#         → data/signal_kelly_trades_parts/t2025.json
#   bash scripts/restore-large-json.sh --date YYYY-MM-DD
#     还原该日期全部快照。
#   bash scripts/restore-large-json.sh --all
#     还原最新日期那一份的全部文件。
# 依赖：python3(调 scripts/upload_r2.py 的 s3_request,SigV4 签名+凭证复用,不新起连接)。
#       凭证从 .env / 环境变量读(upload_r2 模块 import 时 load_env)。
# 输出：data/<原相对路径>(先下同目录 .tmp 再 os.replace 原子覆盖,读侧要么旧完整要么新完整;
#       覆盖前旧文件备份为 <文件>.bak-<时间戳>;gzip 解压;若 docs/large-json-backup-manifest.md
#       有该 key 的 sha256 则比对,不匹配即中止)。
# 安全：只读 signal-backup 桶 large-json/ 前缀(GET/LIST)，绝不写、绝不删除 R2 上任何对象。
# 复现命令：见 docs/large-json-backup-manifest.md 与 docs/backup-restore.md「八、大 JSON 私有桶备份与恢复」。

set -euo pipefail
cd "$(dirname "$0")/.."   # 定位到仓库根(trade/)，data/ 在其下

MODE="${1:-}"
if [ -z "$MODE" ]; then
  echo "用法: bash scripts/restore-large-json.sh <文件名|--list|--date YYYY-MM-DD|--all>" >&2
  echo "  例: bash scripts/restore-large-json.sh signal_kelly_trades.json" >&2
  exit 2
fi

# 全部逻辑走 python(复用 upload_r2.s3_request 签名/凭证；文件级原子写/备份/校验也在此闭环)。
# --list 只读查询；单文件/--date/--all 只读 R2 + 写本地 data/。
python3 - "$@" <<'PYEOF'
import sys, gzip, os, re, hashlib, shutil, datetime, urllib.parse

try:
    sys.path.insert(0, "scripts")
    import upload_r2  # import 时 load_env() 载入凭证
except SystemExit as e:
    sys.exit(f"✗ 无法加载 R2 凭证模块(upload_r2): {e}")
except KeyError as e:
    sys.exit(f"✗ R2 凭证缺失(.env 缺 {e})：请确认 trade/.env 含 R2_S3_ENDPOINT / R2_S3_ACCESS_KEY_ID / R2_S3_SECRET_ACCESS_KEY")

BUCKET = upload_r2.BACKUP_BUCKET
PREFIX = "large-json/"


def _list_all(prefix=PREFIX):
    """分页列出 prefix 下全部 (key, size_bytes)。list-type=2 超过 1000 用 continuation-token 续页。"""
    out = []
    token = ""
    while True:
        q = "list-type=2" + f"&prefix={urllib.parse.quote(prefix, safe='')}"
        if token:
            q += f"&continuation-token={urllib.parse.quote(token, safe='')}"
        status, data = upload_r2.s3_request("GET", "", query=q, bucket=BUCKET)
        if status != 200:
            sys.exit(f"✗ 列出 {BUCKET}/{prefix} 失败 status={status} {data.decode('utf-8', errors='replace')[:300]}")
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
    """large-json/<date>/<rel>.gz -> (date, rel) 或 None(非本前缀)。"""
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
    return (date, rel_gz[:-3])


def load_manifest_sha():
    """读 docs/large-json-backup-manifest.md,返回 {rel_path: sha256_hex}。
    文件缺失返回 {}；行内含 large-json/ key 且含 64-hex 才记(宽松,列格式由核心侧自动生成)。"""
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
                    m[p[1]] = hs[0]
    return m


def human(n):
    return f"{n/1024/1024:.1f}MB" if n >= 1024 * 1024 else f"{n/1024:.1f}KB"


def restore_one(date, rel, manifest_sha):
    """下载 large-json/<date>/<rel>.gz → 解压 → sha256 比对 → 备份旧文件 → 原子写回 data/<rel>。"""
    key = f"{PREFIX}{date}/{rel}.gz"
    status, data = upload_r2.s3_request("GET", key, bucket=BUCKET)
    if status != 200:
        sys.exit(f"✗ 下载失败 {BUCKET}/{key} status={status} {data.decode('utf-8', errors='replace')[:300]}")
    try:
        payload = gzip.decompress(data)
    except Exception as e:
        sys.exit(f"✗ gzip 解压失败 {key}: {e}")

    got = hashlib.sha256(payload).hexdigest()
    expect = manifest_sha.get(rel)
    if expect:
        if got != expect:
            sys.exit(f"✗ sha256 不匹配 {key}: manifest={expect[:16]}… 实际={got[:16]}…,已中止(勿覆盖)")
        print(f"  sha256 ✓ {got[:16]}… 与 manifest 一致")
    else:
        print(f"  (manifest 无 {rel} 记录,跳过 sha256 比对;本地 sha256 = {got[:16]}…)")

    out_path = os.path.join("data", rel)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # 覆盖前备份旧文件(可回滚;新文件写好前旧版仍以 .bak 存在)
    if os.path.exists(out_path):
        bak = f"{out_path}.bak-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        shutil.move(out_path, bak)
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


mode = sys.argv[1]
all_items = _list_all()  # [(key, size), ...]

if mode == "--list":
    by_date = {}
    for key, size in all_items:
        p = parse_key(key)
        if p:
            by_date.setdefault(p[0], []).append((p[1], size))
    print(f"{BUCKET}/{PREFIX} 可用快照(共 {len(all_items)} 个对象):")
    if not by_date:
        print("  (无快照)")
        sys.exit(0)
    for date in sorted(by_date, reverse=True):
        files = by_date[date]
        print(f"\n[{date}] {len(files)} 个文件:")
        for rel, size in sorted(files):
            print(f"  {human(size):>10}  {rel}")
    sys.exit(0)

if mode == "--all":
    dates = sorted({p[0] for k, s in all_items if (p := parse_key(k))}, reverse=True)
    if not dates:
        sys.exit("✗ large-json/ 下无快照")
    target_date = dates[0]
    print(f"还原最新日期 {target_date} 全部文件:")
    for k, _s in all_items:
        p = parse_key(k)
        if p and p[0] == target_date:
            restore_one(target_date, p[1], load_manifest_sha())
    sys.exit(0)

if mode == "--date":
    if len(sys.argv) < 3:
        sys.exit("✗ --date 需要 YYYY-MM-DD 参数")
    target_date = sys.argv[2]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", target_date):
        sys.exit(f"✗ 日期格式应为 YYYY-MM-DD,收到 {target_date}")
    items = [(k, p) for k, p in ((k, parse_key(k)) for k, _s in all_items) if p and p[0] == target_date]
    if not items:
        avail = sorted({p[0] for k, s in all_items if (p := parse_key(k))}, reverse=True)
        sys.exit(f"✗ {target_date} 无快照;可用日期: {avail or '(无)'}")
    print(f"还原 {target_date} 全部 {len(items)} 个文件:")
    for _k, p in sorted(items):
        restore_one(target_date, p[1], load_manifest_sha())
    sys.exit(0)

# 单文件模式:<文件名> 默认取最新快照(按日期降序取第一个匹配)
matches = []
for k, _s in all_items:
    p = parse_key(k)
    if p and p[1] == mode:
        matches.append((p[0], k))
if not matches:
    sys.exit(f"✗ 未找到 {mode} 的快照;可先 --list 查看,或带相对路径(如 signal_kelly_trades_parts/t2025.json)")
matches.sort(reverse=True)  # 日期降序,取最新
date, key = matches[0]
print(f"还原 {mode} 最新快照(日期 {date}):")
restore_one(date, mode, load_manifest_sha())
PYEOF
