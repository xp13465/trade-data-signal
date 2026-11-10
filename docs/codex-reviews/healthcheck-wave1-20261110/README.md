# HC01-04修复与交接

HC01：过滤无效突破价格，高低方向独立校验，超大JSON整数边界已修复；HC02：HTML构造边界转义描述，保留正常通知与阈值输出；HC03：严重/警告优先全部可见，unknown预览及全部展开可达；HC04：手机异常紧凑提示与详情可达，通知模态层级已修复，恢复时移除提示。

两项R2独审均PASS、0未解决项，六实施文件与最终childhead逐blob一致。当前状态：已实现、独审与CI通过、待Claude审合部署；未上线。

已测实现head：`0f53c97ad2142f4303e3579b427bedecb7549feb`；最终交接head/hash见native packet。

基线：`f35437a699d199076b5654dcde58780be89ee6b4`。新固定头CI：PASS。

## 复核记录

告警与UI初审FAIL保留为历史：超大JSON整数OverflowError、手机详情遮挡通知modal均在原范围完成返修。两项R2独审PASS，0未解决项；对应报告路径和固定head见verification.json。实现集成头0f53c97ad2142f4303e3579b427bedecb7549feb的六文件与两最终childhead逐blob一致，最终Linux CI通过。最终文档交接head/hash由native packet固定，本文不自指。

## 范围与旧审计入口

仅HC01-04本次实施；HC05-22仍独立待办。旧22项审计已在codex/healthcheck-20261110-evening发布，固定head 87ecfdc1，不在当前main。可读入口：[旧审计README](/Users/linhuichen/code/trade/.claude/worktrees/codex-healthcheck-20261110-evening/docs/codex-reviews/healthcheck-20261110-evening/README.md)。

## 问题、行为与依据

HC01：无效价格可能误报。本次实现使用有限正数校验，高低方向独立过滤，原查询结果内各需至少10个有效历史样本；SQL窗口20、双NOT NULL、严格大于/小于及高方向优先不变。第一版新增超大整数OverflowError，已修复并经告警R2复核。

HC02：描述中的HTML字符可能导致正文丢条。仅构造HTML时escape(desc, quote=False)，原payload、共享notify转换器及正常阈值/通知输出保持；不声称所有实体文本均保真。

HC03：关注项截断可能隐藏严重/警告。按critical、warning、unknown稳定排序，优先展示全部严重/警告和unknown预览，details可展开其余；不将unknown或running升级为OK。

HC04：手机隐藏时间容器连带隐藏异常入口。新增独立紧凑详情入口，复用健康来源与采集时间，恢复或缺health时移除，缺时间明确未知；不放大全局按钮。第一版展开详情遮挡通知modal，320/390已实证；现已修复并经UI R2复核。

## 证据与原始测试计数

本轮测试与独审结果见本节；文档生成器不执行这些测试，以下复现命令为复跑入口。这里记录已完成的原始测试、独审与负控，未把复跑入口计作额外执行结果。

告警第一版历史：红测53 failed, 70 passed in 1.07s；绿测123 passed in 0.86s，600组正常输入对比一致。最终告警R2：156 passed in 1.59s，90独立checks、6组超大JSON反例、真实9条描述1→9重放；旧helper变异24失败，原测试预期未放宽，作者600正常输入一致。独审覆盖完整base..head，0未解决项。

UI第一版历史86新增断言+20既有回归；最终作者R2为102新增浏览器断言+20既有回归。UI独审R2在390/320共12组模态层级、真实关闭及详情键盘返回验证通过，旧z10000负控4组重现；app/ops/index等blob未变承接HC03，两独审均0未解决项。报告为同证据目录alerts-review-r2.json/md、alerts-readiness-r2.json/md与ui-review-r2.json/md。

新浏览器mjs通过本地命令运行，现有Linux CI不执行该文件；102项浏览器断言不计入Python全量数字。使用完整HTML/CSS，但bootstrap禁用，是受控页面结构/组件验证，不称完整业务页实测；未覆盖实体手机、WebKit或所有业务页。手机异常时header从42px到59.5px，增加17.5px提示行；通知按钮30×21px不变，桌面header62px不变（独审数值），不是整个手机布局零变化。

旧218历史CI run42822266274 success：4398 tests/0fail/0error/7skip，两个job及全量step success；公开日志403，无原始末行。最终实现头0f53c97ad2142f4303e3579b427bedecb7549feb的Linux CI run42824543468通过：4431 tests/0fail/0error/7skip（换算4424 passed，以原计数为主），两个job及完整回归step均success，不含浏览器102断言。公开原始日志403，无原始末行；证据ci-verification-r2.json/md，运行链接：https://github.com/xp13465/trade-data-signal/actions/runs/42824543468。integration-verification-r2.json已读取核对，六文件与两最终childhead逐blob一致；不使用旧integration冒称新头一致。各类检查范围不同，不将计数相加为全项目测试数。

## 影响面和未上线边界

告警链涉及detect_breakout、去重落签、send_or_stage与pending重试、HTML转文本及通知导出消费；本轮不改共享通知、阈值、签结构和正常输出。旧零价pending/去重记录未清理，本次实现仅保障新检测，旧payload仍可能重试；Claude须按实际状态核验，不盲删。SQL不补查更早数据，未扩展百分比/净流入有效域策略。

UI影响Ops关注列表、筛选/展开及首页采集入口；HC08时间口径和HC11状态说明后续可能改同一ops.js，须保留本轮排序、unknown可达和源数组顺序。

版本仍20261108-a660，min未构建提交；由Claude main-merge统一构建和更新。未合主线、未部署、未证明线上改变；本地fixture无生产请求，不等于生产自然轮验收。

## Claude接力步骤

已实现、独审与CI通过、待Claude审合部署；未上线。本轮两项返修及独审R2已完成，不要求Claude重复返修。最终实现头CI证据已齐。最终接力：复核最终head → 正常main-merge统一build/bump → 部署验收。

最终交接head及报告hash见native packet；已测实现head为0f53c97ad2142f4303e3579b427bedecb7549feb。integration-verification-r2确认六实施文件与最终childhead一致，文档阶段仅改四件文档/生成脚本，代码blob保持一致；最终交接头由packet固定，不在本文写自指SHA。Claude核对packet及证据后正常main-merge，部署后验数据、前端与自然轮通知。旧零价pending/去重记录按实际状态核验，不盲删。

## 复现命令与限制

所有示例由Python子进程设置timeout；从指定工作树执行。本轮测试与独审结果见前节；文档生成器不执行这些测试，以下为复跑入口。复跑结果须另记运行head、范围和计数，不覆盖原始证据，不凭命令存在声称额外复跑。定向pytest使用AST/内存桩，不执行业务模块初始化。UI可省略私有fixture得到合成数据，但此时不能声称复现原177项快照及相同计数；不得把私有快照提交到文档。600组差分原始记录在alerts-normal-parity.json，其独立重跑脚本未列于此，须按原始记录复现。

```python
import os, subprocess
from pathlib import Path
w = Path('/Users/linhuichen/code/trade/.claude/worktrees/codex-ops-healthcheck-wave1-20261110')
d = w / 'docs/codex-reviews/healthcheck-wave1-20261110'
subprocess.run(['python3', str(d/'generate_report.py'), '--check'], cwd=w, timeout=15, check=True)
env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
subprocess.run(['python3', '-m', 'pytest', '-p', 'no:cacheprovider', 'scripts/tests/test_healthcheck_alerts_20261110.py', '-q'], cwd=w, env=env, timeout=90, check=True)
env.update(PLAYWRIGHT_MODULE='/Users/linhuichen/code/trade/scripts/playwright-accept/node_modules/playwright/index.js', HC_UI_EVIDENCE='/tmp/hc-wave1-reproduction')
subprocess.run(['node', 'ops/monitoring/tests/healthcheck-ui-20261110.mjs'], cwd=w, env=env, timeout=120, check=True)
subprocess.run(['python3', 'ops/monitoring/tests/smoke_schedule_running_ui.py'], cwd=w, env=env, timeout=90, check=True)
```

## 单段转交

请Claude接力：本次HC01-04修复与交接入口为/Users/linhuichen/code/trade/.claude/worktrees/codex-ops-healthcheck-wave1-20261110/docs/codex-reviews/healthcheck-wave1-20261110/README.md（同目录verification.json、generate_report.py、handoff.txt）；告警f2c5343及UI77ca93ac的R2独审均PASS、0未解决项，六实施文件与最终childhead逐blob一致，已测实现head=0f53c97ad2142f4303e3579b427bedecb7549feb，已实现、独审与CI通过，待Claude审合部署，未上线。最终交接head/hash由后续native packet提供，文档不自指；复核最终head→正常main-merge统一build/bump→部署验收，不重复已完成返修。旧22项审计packet=/tmp/codex-reports/handoffs/healthcheck-evening-20261110-v1.json（id healthcheck-evening-20261110-v1，固定head87ecfdc1c37705ab6b782a7f401c5e4696dae1ff），上一批alert-takeover final packet=/tmp/codex-reports/handoffs/alert-takeover-final-20261110-v1.json（id alert-takeover-final-20261110-v1，勿用active代替final）；按各包核验，不把queued当ACK。本次仅实施HC01-04，HC05-22仍独立待办。浏览器102断言+20既有回归为本地命令，Linux CI不执行新增mjs，Python全量数字不得混入浏览器断言；完整HTML/CSS但bootstrap禁用，不称完整业务页实测。手机异常提示行增加17.5px，通知按钮30×21和桌面header62px不变。旧零价pending/去重未清理，按实际状态核验勿盲删；版本仍20261108-a660，min由Claude统一构建。 本轮final预定id=healthcheck-wave1-final-20261110-v1，稳定master路径=/Users/linhuichen/code/trade/.git/codex-reports/healthcheck-wave1-20261110/final-master-v1.json；发布/ACK须查询，不宣称已发布。最终CI run42824543468：4431 tests/0fail/0error/7skip，不含浏览器102；两job与完整回归step success，日志403无原始末行。
