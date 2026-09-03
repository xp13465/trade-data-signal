#!/bin/bash
# kimi-proxy-switch.sh — kimi-k3 / v4-flash 双代理一键切换(只改 ~/.claude/settings.json,不碰 launchd)
#
# 用途:两个商汤轮换代理同时常驻(v4-flash 版 8899 / kimi-k3 版 8898),本脚本只改
#      ~/.claude/settings.json 的 ANTHROPIC_BASE_URL + 所有模型键,把 Claude 会话指到对应代理。
# 用法:
#   bash scripts/kimi-proxy-switch.sh kimi      # 切到 kimi-k3 代理(http://127.0.0.1:8898,model=kimi-k3)
#   bash scripts/kimi-proxy-switch.sh v4flash   # 切回 v4-flash 代理(http://127.0.0.1:8899,model=deepseek-v4-flash)
# 说明:
#   - 先备份当前 settings.json 到 settings.json.bak-kimi-switch-<日期> 再写(可回退,幂等可重复)。
#   - 只操作 env.ANTHROPIC_BASE_URL + 模型键(ANTHROPIC_MODEL/ANTHROPIC_DEFAULT_*_MODEL/
#     ANTHROPIC_DEFAULT_*_MODEL_NAME/CLAUDE_CODE_SUBAGENT_MODEL),其他键原样保留。
#   - 不 load/unload launchd:两个代理都常驻,靠 BASE_URL 切换;token 不动(两代理共用 SENSENOVA_KEY*)。

set -u

MODE="${1:-v4flash}"
TS=$(date +%Y%m%d-%H%M%S)
SETTINGS="$HOME/.claude/settings.json"
BAK="$SETTINGS.bak-kimi-switch-$TS"

# 各 mode 的 BASE_URL + 模型值
V4_URL="http://127.0.0.1:8899"
V4_MODEL="deepseek-v4-flash"
KIMI_URL="http://127.0.0.1:8898"
KIMI_MODEL="kimi-k3"

case "$MODE" in
  kimi)
    NEW_URL="$KIMI_URL"; NEW_MODEL="$KIMI_MODEL"; DESC="kimi-k3 代理(8898)"
    ;;
  v4flash)
    NEW_URL="$V4_URL"; NEW_MODEL="$V4_MODEL"; DESC="v4-flash 代理(8899)"
    ;;
  *)
    echo "未知 mode: $MODE (可用 kimi|v4flash)"; exit 1
    ;;
esac

if [ ! -f "$SETTINGS" ]; then
  echo "!! settings 不存在: $SETTINGS ,请人工确认"; exit 1
fi

echo "[1/3] 备份当前 settings 到 $BAK"
cp "$SETTINGS" "$BAK" && echo "  已备份"

echo "[2/3] 写入 $DESC (BASE_URL=$NEW_URL, MODEL=$NEW_MODEL)"
python3 - "$SETTINGS" "$NEW_URL" "$NEW_MODEL" << 'PYEOF'
import json, sys
settings_path, new_url, new_model = sys.argv[1], sys.argv[2], sys.argv[3]
with open(settings_path) as f:
    d = json.load(f)
env = d.setdefault("env", {})
# 改 BASE_URL 与所有模型键(含 *_MODEL_NAME),其余键原样保留
env["ANTHROPIC_BASE_URL"] = new_url
for k in list(env.keys()):
    if k.endswith("_MODEL") or k.endswith("_MODEL_NAME"):
        env[k] = new_model
with open(settings_path, "w") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
    f.write("\n")
print("  BASE_URL:", env["ANTHROPIC_BASE_URL"])
print("  MODEL:", env["ANTHROPIC_MODEL"])
print("  SUBAGENT_MODEL:", env.get("CLAUDE_CODE_SUBAGENT_MODEL"))
print("  模型键更新数:", sum(1 for k in env if k.endswith("_MODEL") or k.endswith("_MODEL_NAME")))
PYEOF

echo "[3/3] 完成"
echo "  已切到 ${DESC}。新开 Claude 会话即生效(当前会话的 BASE_URL 由启动时读取,需重启/新会话)。"
echo "  如需切回:bash scripts/kimi-proxy-switch.sh $([ "$MODE" = "kimi" ] && echo v4flash || echo kimi)"
exit 0