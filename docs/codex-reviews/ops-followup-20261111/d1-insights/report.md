HC09 query-analytics recovery is **partial**. Existing Cloudflare telemetry recovers table-level reads and time-correlated import totals for Nov 10 **16:02–16:09 CST**. Exact import write costs by table/statement remain unavailable in this result. No causal savings claim is supported.

| Table / operation | Stage | Queries | Rows read | Rows written | Evidence |
|---|---|---:|---:|---:|---|
| fund_score / SELECT | Hash prefetch | 6 | 28,456 | 0 | Direct query/table metrics |
| fund_score / SELECT | Count verification | 1 | 28,456 | 0 | Direct query/table metrics |
| fund_screener / SELECT | Hash prefetch | 6 | 28,476 | 0 | Direct query/table metrics |
| fund_screener / SELECT | Count verification | 1 | 28,476 | 0 | Direct query/table metrics |
| fund_score-associated import bundle | 16:04:08 CST | 1 write request | 4,009 | 4,390 | Database aggregate; time association only |
| fund_screener-associated import bundle | 16:08:53 CST | 1 write request | 56,301 | 31,762 | Database aggregate; time association only |

Three ALTER operations (two score, one screener) returned errors with zero recorded rows. Error strings remain private; these are not treated as a sync incident. Stage names above are inferred from query shape and inspected source; Cloudflare exposes neither a stage nor a table dimension. Table labels for the SELECT/ALTER rows come directly from query metadata.

The **17 query-detail records** sum to **113,864 reads and 0 writes**. Their totals match an ungrouped insights result and the 1,000-record limit was not reached. The **19 database timestamp groups** sum to **174,174 reads and 36,152 writes**, matching a separate minute grouping. The difference—**60,310 reads and all 36,152 writes**—is precisely the two write-request aggregates. Those aggregates precede verification at 16:04:14 and 16:08:58; supplied completion times are 16:04:14 and 16:08:59. The import association is strong temporal evidence, not direct per-table attribution: bundles may include main-table, index, schema and sync_meta/screener_meta work.

The parent's existing Nov10 partial daily artifact has 174,182 reads / 36,152 writes: this window accounts for all those writes and all but 8 reads. Nov9 daily 514,080 / 341,593 is a different workload/window and is not a matched savings baseline. Changed ratios 2003/28456 and 28148/28476 are content churn, not savings.

Access, schema and time filtering worked: four of the allowed six GraphQL requests returned HTTP 200 with no GraphQL errors. Both datasets are enabled; second and minute fields were accepted. The interval was half-open [08:02:00,08:09:00) UTC. Live limits were 10,000 records, 30 fields, 32-day maximum query duration and 90-day lookback; the general D1 guide states 31-day retention. Only this recent seven-minute interval was tested. [D1 metrics and insights](https://developers.cloudflare.com/d1/observability/metrics-analytics/), [account-specific settings](https://developers.cloudflare.com/analytics/graphql-api/features/discovery/settings/).

These are adaptive analytics observations/estimates, not invoices. Every returned average sample interval was 1; no multiplier was applied and confidence intervals were not requested. The missing write detail cannot be explained here as permission failure, truncation, zero writes, or proven delayed ingestion. Its coverage cause remains unresolved. [Sampling semantics](https://developers.cloudflare.com/analytics/graphql-api/sampling/).

Historical metadata is **already persisted at Cloudflare and partly recoverable**, so “nothing was persisted” is too broad. In the inspected local paths, hash parsing retains results only, count verification extracts only the count, and import output is overwritten by file/attempt rather than retained as structured cost history. This does not establish that no historical log elsewhere contains metadata. Exact source paths, lines and hashes are in report.json; runtime code identity and broader logs were outside scope.

The precise follow-up is to preserve metadata from **existing calls in the next normal scheduled run**, without an extra run: record run/script/code reference, table/stage/operation, UTC boundaries, attempt and status, and returned rows_read/rows_written/duration before parsers discard them. Store unavailable fields as null with a reason. Preserve each returned result separately; if an import exposes only bundle totals, retain that scope and affected table labels, never allocate all of it to the main table. Keep attempts and content-change counters separate. This complements the parent's daily collector; no collector, pipeline or production change was implemented.

Review verdict: PASS for this bounded inquiry; **HC09 exact table/stage write accounting remains incomplete**. No SQL, Wrangler command, application import, subagent, notification, publication or ACK was executed. All writes are inside this directory. Raw responses remain owner-only; the shareable report contains normalized labels and metrics only.
