# 命中率走势表补「配置快照」维度(2026-09-19)

## 目标(用户拍板三件)
1. 主表加「模型/端点」列(合并成一列,如 `flash-0731·商汤`)
2. 主表加「思考%」列(当天 thinking 字符占比,如 `93%`)
3. 新增「配置快照日志」区块,每行 = 日期|模型|端点|思考%|effort|来源,放 effort 等细节(不占主表)

## 现状
- 脚本 `scripts/token_cache_stats.py`:读 `~/.claude/projects/-Users-linhuichen-code-trade/*.jsonl` 的 `message.usage` 算命中率;`--append-daily` 每日 23:30 由 launchd `com.trade.token-cache-stats` 追加走势,幂等更新 `claude-work-mode/README.md` 的「命中率走势」表 + 「版本/改动日志」区块,追加完自动 commit+push main。
- 走势表原 5 列:日期/命中率/冷读input/claude版本/当日改动。
- 历史数据源:08-10~08-17 源 JSONL 已丢(README 已有行配置列标 "—");08-18 起有完整 JSONL。

## 四个配置维度数据来源
| 维度 | 来源 | 口径 |
|---|---|---|
| 模型 | JSONL `message.model` | 按当天 input token 加权取 top1,短名化(去 `deepseek-v4-`/provider 前缀/`:free` 后缀) |
| 思考% | JSONL content `type=thinking`/`type=text` 块 | 字符长度比,按天求和聚合后算比(JSONL 无 thinking token 数字;`output_tokens_details.thinking_tokens` 恒 0 不可靠) |
| 端点 | 历史 = 一次性时段表;当天 = 实时抓 settings BASE_URL + 代理进程 env + launchd label | 过渡日多端点标「混合」/主端点;09-12~09-17 pro-0813 存疑标「待确认」 |
| effort | 历史 "—";当天 = settings 模型 + 角色 skill 档位(implementer low / tester·reviewer·researcher max) | 不占主表,只进配置快照日志 |

### 端点时段表(一次性硬编码,未来端点切换由每日快照自动跟随)
| 时段 | 端点 |
|---|---|
| 08-18 | 方舟 plan |
| 08-19 | 官方直连(混合,上午方舟/10:39 后官方) |
| 08-20 | 官方直连 |
| 08-21~08-30 | opencode |
| 08-31 | openrouter 直连 |
| 09-01 | 商汤 rotate(混合) |
| 09-02~09-12 | 商汤 rotate |
| 09-13~09-17 | 待确认(settings mtime 09-17 22:24 ≠ JSONL 09-12 就 pro 主导) |
| 09-18~今 | 8899·商汤 rotate |

## 6 处改动点(scripts/token_cache_stats.py)
1. `_scan_rich(path)`:在现有 `grep '"usage"'` 快筛基础上,assistant 行额外解析 `message.model` + content 里 thinking/text 块字符。产出 `(day, cr, cc, inp, out, model, think_chars, text_chars)`。
2. `_aggregate_days(jsonl_dir)`:一次全扫聚合所有天(usage + model_tok input 加权 + think/text 字符),当天+历史回填共用一次扫描。
3. `_get_day_config(date_str, agg_day, is_today)`:历史查 `ENDPOINT_TABLE` + 聚合;当天实时抓 `_live_config()`(settings.json BASE_URL + lsof 端口查监听进程识别代理 + 角色档位)。返回 model/endpoint/think_pct/effort/source/model_endpoint。
4. `_write_config_snapshot(date_str)`:当天落盘去敏快照 `claude-work-mode/config-snapshots/YYYY-MM-DD.json`,只含 BASE_URL/MODEL/SUBAGENT 三字段,绝不落 token。
5. `_split_trend_table`/`_render_trend_table`:5 列→7 列,兼容旧行缺列(旧 5 列 → model_ep/think_pct 补 "—")。
6. `_render_cfglog` + `CFGLOG_MARK_START/END`:新增「配置快照日志」区块,复制 changelog 的 split/replace 模式,只列出有配置来源的日期。

## 去敏铁律
settings.json 有明文 `sk-` token,快照只取 BASE_URL/MODEL/SUBAGENT 三字段,绝不落 token(否则 git push 被 GitHub Push Protection 拦)。

## 自测结果
- `python3 -m py_compile scripts/token_cache_stats.py` 通过。
- 统计报告模式(自定义窗口 09-15~09-16)跑通。
- `--append-daily` dry 模式(`TOKEN_CACHE_STATS_DRY=1` + `TRADE_REPO_ROOT=<worktree>`)跑通,7 列渲染正确,旧行补 "—",历史回填正确,幂等无重复。
- 抽查:08-28 opencode 期 = `minimax-m2.7·opencode 79%`;09-15 商汤期 = `pro-0813·待确认 96%`;当天 09-19 = `pro-0813·8899·商汤rotate 93%`。
- 快照文件确认只含 date/model/subagent_model/base_url,无 token。
- `_live_config` 修一个 bug:lsof 头部行(`COMMAND PID...`)被当数据行导致代理识别失败,加 `parts[1].isdigit()` 过滤后正确识别 8899=商汤 rotate。

## 复现
- 统计报告模式:`python3 scripts/token_cache_stats.py <jsonl_dir> <start> <end>`
- 追加走势:`python3 scripts/token_cache_stats.py --append-daily [date]`(23:30 定时)
- 演练(写 README+快照不 push):`TOKEN_CACHE_STATS_DRY=1 TRADE_REPO_ROOT=<worktree> python3 scripts/token_cache_stats.py --append-daily`
- 数据源:`~/.claude/projects/-Users-linhuichen-code-trade/*.jsonl`(08-18 起完整;08-10~08-17 已丢)
- 数据截止:2026-09-19
- 关键口径:思考% = thinking 字符/(thinking+text) 字符,按天求和聚合(与命中率"先求和再算比"同构);模型 = input token 加权 top1
