# TASKS.md 完成度校验报告

> 生成：2026-08-28 21:41（scripts/tasks_verify.py）

## 统计
- TASKS.md 共 5 个 ## 小节 / hash 引用 15 个（去重后）
- 不在 origin/main 的 hash：4 个；其中查无此 commit（悬空）：0 个

## ① 悬空 hash 但功能在 main / 需人工确认（建议更新 hash 或归档）

（无）


## ② 漏标（已上线仍标待办，建议改标 ✅ + 归档）

（无）


## ③ 状态超前（标题写已归档但实际未在 TASKS-done.md）

（无）


> 说明：① 的「功能词命中」为启发式判断（git grep origin/main 标题关键词），可能漏判/误判，
> 人工确认后：hash 确实过期 → 更新 TASKS 或跑 tasks_archive.py 归档；功能真未上线 → 改标待办。
> ②/③ 由 tasks_archive.py 按标题 done 标记自动归档，漏标项需人工/后续轮次改标后归档。
