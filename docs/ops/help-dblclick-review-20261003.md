# reviewer 独立审查: 帮助图标移动端双弹修复(feat/help-dblclick-20261003, commit 7975699ff)

- reviewed: `7975699ff`(base `11073b291`);reviewer 独立注入 git show 提取真实代码自测,未照抄 implementer 表格
- 改动分级:**B 级(逻辑/事件委托,全站鼠标事件共享委托层,有隐藏影响面)→ 完整 review**
- 结论:**需补 1 处同类漏修 + 自测证据不可独立复核(见 F1/F2);核心修复本身验证正确**

## F1(置信 100,必须补): 同类清单漏修 `#pfIndHelpBtn`(行业配置口径说明 ❓)移动端仍双弹

- trace:`static-site/app.js:22065`(`<span id="pfIndHelpBtn" ... title="行业配置口径说明">❓</span>`) + `app.js:22327`(`_helpBtn.addEventListener("click", _showIndHelpModal)`),位于 `renderPublicFund`(公募基金 subtab 行业配置卡)。linkage:不满足(修复报告自称「全站帮助类图标共 6 处(A-F)…6/6 修毕」,§23.2 同类清单应覆盖)
- 为什么漏:同类排查只 grep 了 `data-*-help`/`data-glossary`/`data-ice-note` **属性**,pfIndHelpBtn 是 **id 绑定 + title→term-pop 迁移路径**的帮助图标(全站 `cursor:help` 唯一一处 = 它,已穷举确认没有第二处 id 式)
- verifier:
  - command:`git show 7975699ff:static-site/app.js | grep -n "pfIndHelpBtn"`(22065 定义 + 22327 绑定,无 data-*-help 属性);`style.css` 查 z-index(.term-pop z-9999 > .rule-modal z-110 → 双弹同时可见,不是被 modal 盖住)
  - expected(按本修复自身根因定义):帮助图标 = term-pop + click modal 双绑定 → 移动端应单弹 modal
  - observed:**reviewer 独立 Playwright(注入 7975699ff 真实 `_initTermPop` + 该 span 结构 + click 弹 modal 计数, matchMedia(hover:none)=true, 模拟 mouseover→mousedown→mouseup→click):`pfIndHelpBtn: hoverPop=True clickPop=True pfModal=1` — term-pop 与 modal 同时弹,双弹复现**
- 建议修法(不改代码,仅建议):把 `#pfIndHelpBtn` 纳入排除集合(如给 span 加 `data-*-help` 属性并入 `_modalHelpSel`,或直接 `#pfIndHelpBtn` 选择器并入集合);或按 10-02 ice-note 先例在 mouseover/click 两处委托加一条排除

## F2(置信 90,证据缺口): 自测"修前双弹"对比证据当前状态不可独立复核

- trace:修复报告「复现」节 = `/tmp/helpdbl_test.py`(不入库)+ 其 before 引用 `git -C worktree show HEAD`;linkage:满足(影响自测可信度与 §5.4⑦)
- verifier:
  - command:`python3 /tmp/helpdbl_test.py`(在现分支状态重跑)
  - expected:复现报告中的修前 4 处双弹/hoverPop=True 对比表
  - observed:重跑 "before" 段全部 `hoverPop=None clickPop=None` —— 脚本 before 侧用**修前行号范围(7858-8188)截取当前 HEAD(=7975699ff 修复版)文件**,IIFE 截断缺 `})();` 语法错未注册,数据失效。脚本未入库、before 引用的是瞬态 HEAD,现仓库状态下无法复现"修前双弹"原始证据
- 判定:方法本身可信(真实代码提取注入,非复刻第二份实现,修后单弹我已独立复核成立);但**证据不可从分支独立复核**,需 implementer 补一份入库的、以 base `11073b291` 为 before 参照的可重跑脚本(现 `git show 11073b291:static-site/app.js` 即修前文件,完全可做)

## 正面验证(逐项)

1. **误伤面(5 属性 grep 全量)**:`data-overfit-help`(app.js 1673 term-tip 型 + 2363 父级 data-tip 型)/`data-ice-note`(7278)/`data-signal-help`(7837)/`data-strategy-help`(8400,`_appendStrategyHint` 注入,自带 data-tip+`__strategy`)/`data-glossary`(lab.js 803)全部只出现在「带 click modal 委托」的帮助图标上;html/common.js/purpose-notes.js/i18n.js/sw.js 零命中;纯 tooltip(term-tip 无 modal 属性)不携带这 5 属性 → 无非被静默掐掉的 tooltip
2. **overfit 两种用法**:term-tip 型(自身 data-tip)与父级 data-tip 型(2363 `❓完整指南` 挂子元素)均验证:移动端 tap 后 term-pop 不弹、modal 单弹(closest 命中子元素自身即可排除;点父级其余区域仍走纯 tooltip 单弹,设计行为)
3. **桌面端未受影响**:mouseover 排除带 `isTouch &&` 前缀,click 排除只在 `if (isTouch)` 块内注册;自测 D 组桌面 hover 全部仍弹(overfit/overfit2/ice/signal/strategy/glossary/plain)
4. **普通 tooltip 不被误伤**:自测 icon-plain 移动端 hoverPop=True clickPop=True modals=0(仅 term-pop 单弹,无 modal)
5. **同类清单抽样复核**:G(纯 data-tip tooltip)/H(common.js chip)/I(lab.js sig-kelly `data-no-pop`)分类成立 —— `findTipEl` 首行 `target.closest("[data-no-pop]")` 即 return null(lab.js 10295/11096/11121/11140/11197/11200/11220/11273/11349/11389/11392 全带 data-no-pop);J 不成立(漏 id 式,见 F1)
6. **5 处修后单弹逐项实测**(reviewer 独立注入 git show 提取真实代码):overfit/overfit2/ice/signal/strategy/glossary 移动端 tap 全部 `hoverPop=False clickPop=False modals=1` ✓;连续快速 tap 两次 = 两次点击各弹一次 modal(标准行为,非回归);tap 后再 hover 不弹 term-pop ✓
7. **§24 分工**:分支未 bump 版本串 ✓;`scripts/main-merge.sh` L206-238 含统一 build_min + bump_asset_version(机制 C) + §24⑤ 哈希==引用校验,L17/29 确认 9 源覆盖 → merge 时自动补,无缺口
8. **§21 公示**:diff 仅动 `_initTermPop` 事件委托(UI 交互),零算法/评分/权重/口径文案改动 → 无需公示 ✓

## 另 3 个低分项(<80)已滤

- lab.js:3012 `lab-rank-quality`(title 嵌 clickable rank 行,tap 时 term-pop+行详情 modal 同弹)— 同类候选但非本次 diff 引入、非典型「帮助图标」,pre-existing 走上报通道
- lab.js:12933 `lab-sigkelly-guide-trigger[data-guide]` — 自建 pop 系统无 data-tip,无 term-pop 参与,无需修 ✓(复核过,非漏)
- lab.js:12420 📌 pin-btn(title)— 功能按钮非帮助图标,pre-existing

## 结论

- 核心修复(4 处点名地 + ice-note 回归)经 reviewer 独立实测**全部单弹,桌面 hover 与普通 tooltip 行为不变**,可随本分支上线
- F1 同类漏修(`#pfIndHelpBtn` 移动端双弹)必须在 merge 前补上(或记录为已知问题由主控拍板);F2 建议补充入库可复跑脚本后再 merge 亦可接受(修后行为已验证)
