# recent 调研结论（2026-11-04）

只读快照：main 58fabc61efdf35b1331a2ac09c737a9e6fee28be，提交时间2026-11-02 09:17:06 +08；本地观察时间2026-11-04 14:46+08起，工作区git status --porcelain为空。本轮无云端数据库或首跑日志取证。未执行FOF SQLite复现（已交reliability），未跑内存/长区间回填测试、业务测试、构建或浏览器。未改仓库、未发通知、未操作生产。

1. 确证：#329–331对应实现已补/#332文档已补，状态仍待办。
   - 状态：docs/pending-features-index.md:498-501。
   - #329 app/collector/fund_pct.py:115、:131：64个基准日的LRU上限；实际内存和长区间峰值未测。
   - #330 scripts/backfill_fund_nav_pct_252.py:252、:264：integrity_check与内容抽样（_VERIFY_SAMPLE_N=50，:71）；未实测生产备份恢复效果。
   - #331 scripts/backfill_fund_nav_null_days_251.py:47、:197：import并调用calc_pct，原脚本第二份公式收敛。
   - #332 docs/ops/fund-nav-pct-rootfix-20261028.md:139：补了position_estimate观察项；不是已完成线上观察的证据。
   - 复核命令（本轮已运行同等范围）：git log --since=2026-10-21 --until=2026-11-05 --format="%h %cs %s" -- app/collector/fund_pct.py scripts/backfill_fund_nav_pct_252.py scripts/backfill_fund_nav_null_days_251.py docs/ops/fund-nav-pct-rootfix-20261028.md；git show --stat --oneline 8d1dc0f7a；git show --stat --oneline ee46abef6；以及上述源码逐段nl/rg核读。
   - 观测：11-01两次提交对应上述实现/文档，当前台账四行仍是10-28待办。
   - 风险/建议：重复派修、把待观察误当未开发；只更新实施/文档落地状态与commit证据，运行效果未验证项继续单列。
   - 验收：四条记录与现有实现一致，#332明确“观察项已补、实测结果待补”，不得把静态核对改写成根治已验。

2. 证据缺口/真正待办：#333应分别验收批1运行效果与批2/3。
   - docs/ops/333-fix-plan.md:81-83仍为11-02“今晚首跑观察点”；TASKS.md:13与docs/pending-features-index.md:502相同。
   - docs/ops/333-fix-plan.md:70手动小样written=8，但记录明确8次upsert全no-op，不能证明漏值已修复。
   - docs/ops/333-fix-plan.md:55-57：批2份额清理/定开封闭识别；批3十月及更早回填/prev跨日派生；skip差集明确归批2，不另报新发现。
   - 本轮所读记录没有11-02/03自然跑结果；缺云端证据，不据此认定首跑失败或漏值仍在。
   - 建议：补两晚实际触发的journal/文件日志、批次成功/失败及剩余量、FOF/QDII近两个已发布交易日非空率；历史回填单独记录范围、前后NULL数及非空未覆盖校验。
   - 云端建议复核（本轮未执行）：journalctl -u trade-fof-nav-collect.service --since "2026-11-02 21:10"；结合data/logs/fof_nav_collect_*.log和权威public_fund.db只读SQL。一次性systemctl status不能替代两晚历史。
   - 验收：批1效果有真实新增非空值与覆盖范围证据，批2/3独立保留状态；单凭enabled/退出0/手动no-op样本不能结案。

3. 建议（模式归纳，不是新运行bug）：将当前任务状态收敛为一份记录，交接与ops保留证据指针。
   - TASKS.md:14仍声明main=d223e228f，而本地实际HEAD=58fabc61e；#329-332是另一个实施和状态手工复制后失步的实例。
   - 已有进展去重：#356内容指纹已经在static-site/export.py:923-982落地（含indicators.yaml与util_atomic）；不要重复建议“改mtime哈希”，pending-index:527也已纠正该旧RCA。
   - 建议沿用pending-index作为唯一当前状态；每项分别记录实现commit、自然跑验证时间/证据、残余子项。TASKS只指向该项和本次交接，不再复制“main当前SHA/已完成”结论。历史ops原文保留并加新结论指针。
   - 验收：随机抽329-333，能从唯一状态记录区分“实现已补/观察待验/批次待做”，不需翻多份历史长行来决定下一步，也不会重复派已合入实现。
