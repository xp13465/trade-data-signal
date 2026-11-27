> 归档自 /tmp/383-verify-report-20261127.md,2026-11-27;原始路径为临时文件,本副本为持久归档

# #383 只读核验报告:代码仓(C 根)旧 sentiment 库读者已消失

- 核验时间:2026-11-27 21:27–21:30(+0800)
- 方式:ssh 只读(stat/ls/grep/tail/lsof/ps),零外发、零写入云上、未改任何文件
- 结论:**PASS**(两项判定均通过)

## 判定 1:C 根旧库 shm mtime 是否仍停在基线

基线:mtime = 2026-11-26 21:15:01(判定标准:等于基线 ⇒ 无读者;前进到 2026-11-27 ⇒ 仍有读者)

实测(`stat -c '%y %s' /home/ubuntu/code/trade-data-signal/data/sentiment.db-shm`):
```
2026-11-26 21:15:01.338224946 +0800 32768
```
⇒ 与基线**逐纳秒一致**,未前进 ⇒ PASS。

同目录备查:
```
sentiment.db      2026-10-28 21:38:34.059645051 +0800 232124416
sentiment.db-wal  2026-10-28 21:40:00.807722144 +0800 0
```
(db/wal 也停在 10-28,无今晚写入迹象。)

补充只读证据(`lsof` / `ps`):无任何进程持有 C 根 sentiment.db / -shm / -wal(lsof 仅 tracefs 告警,无匹配行;ps grep 无匹配)。

## 判定 2:今晚 [brief_ledger] repo= 指向哪棵树

数据源:`/home/ubuntu/code/trade-data/data/logs/daily_brief.log`(mtime 2026-11-27 20:40:53,确为今晚写入)

运行证据:
```
2026-11-27 20:40:44  daily_brief_run.log 末行:20261127 ...(今晚正常完成)
L1652: [run_daily_brief] 开始 ledger 对账 brief_ledger 2026-11-27 20:40:53
L1653: [brief_ledger] repo=/home/ubuntu/code/trade-data db=/home/ubuntu/code/trade-data/data/sentiment.db
L1654: [brief_ledger] reconcile: rows=48 changed=1
```
⇒ repo=/home/ubuntu/code/trade-data(部署数据树 D),非代码仓 C 根 ⇒ PASS。

对照历史:L1616(2026-11-26)、L1579 同为 repo=/home/ubuntu/code/trade-data,口径一致。

## 失败项证据
无(判定 3 仅在 FAIL 时需给,本次不适用)。

## 复现命令
```
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 "stat -c '%y %s' /home/ubuntu/code/trade-data-signal/data/sentiment.db-shm"
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 "grep -n brief_ledger /home/ubuntu/code/trade-data/data/logs/daily_brief.log | tail -8"
```

## 边界维度自检(role-tester §5.3.1)
- 输入域(空/缺文件):文件存在已 ls 实证,不适用空值。
- 状态组合(盘中/盘后):判定时点在 21:27,今晚 20:40 任务已完成,不适用盘中干扰。
- 时序(跨日):基线为 11-26 21:15,今晚 11-27 20:40 任务跑完后 shm 未变 ⇒ 跨日翻滚无触碰。
- 回退路径:不适用(纯只读核验,无降级开关)。
- 并发/重入:lsof/ps 双重确认当前无持有者。
- 未被 shm 覆盖的读者(以 immutable/只读方式打开不写 shm)属本任务判定口径之外,已在 lsof 层补证无持有者。
