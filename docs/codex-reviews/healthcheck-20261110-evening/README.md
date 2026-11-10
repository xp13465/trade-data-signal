# 晚间体检入口

先读 [report.md](report.md)，实施范围与全部字段见 [tasks.md](tasks.md)。[handoff.txt](handoff.txt) 可直接交Claude复核。本轮完成六路只读体检、综合报告、22项建议任务及离线复现材料。清单中新业务修复尚未实施，后续按明确分工认领+独立复核。

固定事实：[snapshot.json](snapshot.json)；输入摘要指纹：[evidence-manifest.json](evidence-manifest.json)。原始证据仅私有本机留存。

在本目录运行：

```sh
python3 generate_tasks.py
python3 generate_tasks.py --check
```

正常运行仅从同目录tasks.json确定性重建中文字段标签的tasks.md；--check只校验22个唯一编号、production_done全false及渲染全文一致，不写任何文件，不一致时非零退出。脚本使用标准库、离线、不读私有目录。report.md为依据snapshot人工整合的固定报告；重建任务清单不代表重新完成生产验收。任务状态权威为pending-index，tasks.json仅本报告固定输入；HC号不取代全局编号，拟owner并非已认领。发布/head状态另记回执，不写自指hash。

文档已完成，发布与回执见独立交接包。生产修复尚未实施。
