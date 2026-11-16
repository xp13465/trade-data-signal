-- D1 free-tier daily write quota (2026-11-16 A2): 0006 fixed the read amplification of
-- the observation triggers but kept the per-check write amplification — its ON CONFLICT
-- predicate compared observation timestamps only, so all 186 checks were rewritten every
-- 15-minute ingest round (~194 rows/round, ~18.6k rows/day) even when nothing changed.
-- This forward-only migration keeps the exact 0005/0006 semantics (effective status,
-- severe recovery-validation policy, missing-from-snapshot handling, head election) and
-- changes only WHEN a per-check row is written:
--
--   * a check row is written only when its CONTENT changes. Content = name, effective
--     status, effective summary, category, reported_status, observation_status,
--     evidence (this is where business: valid_until lives) and the derived problem_open.
--     Volatile observation metadata (observed_ms / observed_at / collected_ms /
--     snapshot_id / updated_ms) is NOT content and no longer forces a write.
--   * the strict per-check clock guard is retained: a content change carried by an
--     OLDER observation still may not overwrite a newer elected observation (the
--     0001/0005 "a fresh envelope cannot regress a check's observation" contract).
--   * a check that disappears from the latest snapshot is marked unknown exactly once
--     (status<>'unknown'), not rewritten every round. The worker's /state keeps
--     classifying missing checks from snapshot membership ("not a recovery").
--   * ops_runs.counts_json is only rewritten when the elected counts actually change
--     (a duplicate no-op write saved per round).
--
-- 0006 stays untouched because it is already applied in production
-- (D1 d1_migrations applied_at 2026-11-13 01:31:09, measured in
-- /tmp/monitor-quota-rca-20261116.md §3.1).
--
-- Deployment order (see DEPLOY.md §7): deploy the matching worker/ops.js FIRST, then
-- apply this migration. The new worker is compatible with the old 0006 trigger (it only
-- derives per-check freshness from ops_head), but the old worker is NOT compatible with
-- this trigger: it still expires checks via observed_ms, which this migration stops
-- refreshing every round, producing a false-unknown storm. Rollback below restores the
-- exact 0006 trigger; 0007 only changes write frequency, never stored content, so no
-- backfill is needed in either direction.

DROP TRIGGER ops_run_insert;
CREATE TRIGGER ops_run_insert AFTER INSERT ON ops_runs BEGIN
  INSERT INTO ops_check_state(collector_id,check_id,name,status,observed_ms,collected_ms,snapshot_id,updated_ms,problem_open,summary,observation_json)
    SELECT NEW.collector_id,json_extract(c.value,'$.id'),json_extract(c.value,'$.name'),c.effective_status,
      json_extract(c.value,'$._observed_ms'),NEW.collected_ms,NEW.snapshot_id,NEW.received_ms,
      CASE WHEN c.effective_status IN ('warning','critical') THEN 1 ELSE 0 END,
      CASE WHEN c.effective_status<>json_extract(c.value,'$.status') THEN
        CASE WHEN c.prior_problem_open=1 THEN 'Recovery invocation not verified; original problem remains open'
          ELSE 'Natural invocation not verified; execution health remains unknown' END
        ELSE json_extract(c.value,'$.summary') END,
      c.value
    FROM (
      SELECT c.value, previous.problem_open AS prior_problem_open, CASE WHEN json_extract(c.value,'$.status')='ok'
        AND json_extract(c.value,'$.id') IN ('cloud-service:trade-public-fund-daily.service','cloud-service:trade-overfit-monitor.service')
        THEN CASE WHEN json_extract(c.value,'$.evidence.execution_state')='completed'
          AND json_type(c.value,'$.evidence.exit_code')='integer'
          AND json_extract(c.value,'$.evidence.exit_code')=0
          AND json_extract(c.value,'$.evidence.unit_result')='success'
          AND json_type(c.value,'$.evidence.invocation_id')='text'
          AND length(json_extract(c.value,'$.evidence.invocation_id'))=32
          AND json_extract(c.value,'$.evidence.invocation_id') NOT GLOB '*[^0-9a-f]*'
          AND json_type(c.value,'$.evidence.last_start_utc')='text'
          AND json_type(c.value,'$.evidence.last_exit_utc')='text'
          AND json_extract(c.value,'$.evidence.last_start_utc') GLOB '????-??-??T??:??:??*'
          AND json_extract(c.value,'$.evidence.last_exit_utc') GLOB '????-??-??T??:??:??*'
          AND (json_extract(c.value,'$.evidence.last_start_utc') GLOB '*Z' OR json_extract(c.value,'$.evidence.last_start_utc') GLOB '*[+-]??:??')
          AND (json_extract(c.value,'$.evidence.last_exit_utc') GLOB '*Z' OR json_extract(c.value,'$.evidence.last_exit_utc') GLOB '*[+-]??:??')
          AND julianday(json_extract(c.value,'$.evidence.last_start_utc')) IS NOT NULL
          AND julianday(json_extract(c.value,'$.evidence.last_exit_utc')) IS NOT NULL
          AND ((previous.recovery_failure_ms IS NULL AND COALESCE(previous.problem_open,0)=0)
            OR (json_extract(c.value,'$.evidence.invocation_id')<>COALESCE(previous.recovery_failure_invocation,'')
              AND ROUND((julianday(json_extract(c.value,'$.evidence.last_start_utc'))-2440587.5)*86400000)>COALESCE(previous.recovery_failure_ms,previous.observed_ms)))
          AND julianday(json_extract(c.value,'$.evidence.last_exit_utc'))>=julianday(json_extract(c.value,'$.evidence.last_start_utc'))
          AND ROUND((julianday(json_extract(c.value,'$.evidence.last_exit_utc'))-2440587.5)*86400000)<=json_extract(c.value,'$._observed_ms') THEN 'ok' ELSE 'unknown' END
        ELSE json_extract(c.value,'$.status') END AS effective_status
      FROM json_each(NEW.snapshot_json,'$.checks') c LEFT JOIN ops_check_state previous
        ON previous.collector_id=NEW.collector_id AND previous.check_id=json_extract(c.value,'$.id')
    ) c
    WHERE NOT EXISTS(SELECT 1 FROM ops_head WHERE id=1 AND
      (collected_ms>NEW.collected_ms OR (collected_ms=NEW.collected_ms AND snapshot_id>=NEW.snapshot_id)))
    ON CONFLICT(collector_id,check_id) DO UPDATE SET
      name=excluded.name,status=excluded.status,observed_ms=excluded.observed_ms,collected_ms=excluded.collected_ms,
      snapshot_id=excluded.snapshot_id,updated_ms=excluded.updated_ms,summary=excluded.summary,
      observation_json=excluded.observation_json,
      problem_open=CASE WHEN excluded.status='ok' THEN 0 WHEN excluded.status IN ('warning','critical') THEN 1 ELSE ops_check_state.problem_open END
    WHERE (excluded.observed_ms>ops_check_state.observed_ms OR
        (excluded.observed_ms=ops_check_state.observed_ms AND excluded.collected_ms>ops_check_state.collected_ms))
      AND (excluded.name IS NOT ops_check_state.name
        OR excluded.status IS NOT ops_check_state.status
        OR excluded.summary IS NOT ops_check_state.summary
        OR json_extract(excluded.observation_json,'$.category') IS NOT json_extract(ops_check_state.observation_json,'$.category')
        OR json_extract(excluded.observation_json,'$.reported_status') IS NOT json_extract(ops_check_state.observation_json,'$.reported_status')
        OR json_extract(excluded.observation_json,'$.observation_status') IS NOT json_extract(ops_check_state.observation_json,'$.observation_status')
        OR json_extract(excluded.observation_json,'$.evidence') IS NOT json_extract(ops_check_state.observation_json,'$.evidence')
        OR (CASE WHEN excluded.status='ok' THEN 0 WHEN excluded.status IN ('warning','critical') THEN 1 ELSE ops_check_state.problem_open END) IS NOT ops_check_state.problem_open);
  UPDATE ops_check_state SET status='unknown',summary='Missing from latest snapshot; coverage unknown; not a recovery',
    collected_ms=NEW.collected_ms,updated_ms=NEW.received_ms
    WHERE collector_id=NEW.collector_id AND status<>'unknown' AND check_id NOT IN
      (SELECT json_extract(value,'$.id') FROM json_each(NEW.snapshot_json,'$.checks'))
    AND NOT EXISTS(SELECT 1 FROM ops_head WHERE id=1 AND
      (collected_ms>NEW.collected_ms OR (collected_ms=NEW.collected_ms AND snapshot_id>=NEW.snapshot_id)));
  -- ACK/history counts describe the atomically elected states, not an unverified
  -- producer claim of recovery. Duplicates retain these first-ingest counts; an
  -- unchanged recomputation is not rewritten (content-change-only write contract).
  UPDATE ops_runs SET counts_json=(
    SELECT json_object('ok',SUM(s.status='ok'),'warning',SUM(s.status='warning'),
      'critical',SUM(s.status='critical'),'unknown',SUM(s.status='unknown'))
    FROM json_each(NEW.snapshot_json,'$.checks') c JOIN ops_check_state s
      ON s.collector_id=NEW.collector_id AND s.check_id=json_extract(c.value,'$.id')
  ) WHERE snapshot_id=NEW.snapshot_id AND counts_json IS NOT (
    SELECT json_object('ok',SUM(s.status='ok'),'warning',SUM(s.status='warning'),
      'critical',SUM(s.status='critical'),'unknown',SUM(s.status='unknown'))
    FROM json_each(NEW.snapshot_json,'$.checks') c JOIN ops_check_state s
      ON s.collector_id=NEW.collector_id AND s.check_id=json_extract(c.value,'$.id')
  ) AND NOT EXISTS(SELECT 1 FROM ops_head WHERE id=1 AND
    (collected_ms>NEW.collected_ms OR (collected_ms=NEW.collected_ms AND snapshot_id>=NEW.snapshot_id)));
  INSERT INTO ops_watchdog(id,status,changed_ms)
    SELECT 1,'fresh',NEW.received_ms WHERE NOT EXISTS(SELECT 1 FROM ops_head WHERE id=1 AND
      (collected_ms>NEW.collected_ms OR (collected_ms=NEW.collected_ms AND snapshot_id>=NEW.snapshot_id)))
    ON CONFLICT(id) DO UPDATE SET status='fresh',changed_ms=excluded.changed_ms WHERE ops_watchdog.status<>'fresh';
  INSERT INTO ops_head VALUES(1,NEW.snapshot_id,NEW.collected_ms)
    ON CONFLICT(id) DO UPDATE SET snapshot_id=excluded.snapshot_id,collected_ms=excluded.collected_ms
    WHERE excluded.collected_ms>ops_head.collected_ms OR (excluded.collected_ms=ops_head.collected_ms AND excluded.snapshot_id>ops_head.snapshot_id);
END;

-- ============================================================================
-- ROLLBACK (reversible). Do NOT uncomment inside a migration run; wrangler applies
-- every statement in this file when the migration runs. To roll back 0007, deploy the
-- previous worker/ops.js first (it expects every round to refresh observed_ms), then run
-- the SQL below manually via `wrangler d1 execute OPS_DB --remote --config <config>
-- --file <this-extracted-sql>`. It restores the exact 0006 trigger verbatim. No table
-- data is touched: 0007 never changes stored content, only write frequency.
--
-- DROP TRIGGER ops_run_insert;
-- CREATE TRIGGER ops_run_insert AFTER INSERT ON ops_runs BEGIN
--   INSERT INTO ops_check_state(collector_id,check_id,name,status,observed_ms,collected_ms,snapshot_id,updated_ms,problem_open,summary,observation_json)
--     SELECT NEW.collector_id,json_extract(c.value,'$.id'),json_extract(c.value,'$.name'),c.effective_status,
--       json_extract(c.value,'$._observed_ms'),NEW.collected_ms,NEW.snapshot_id,NEW.received_ms,
--       CASE WHEN c.effective_status IN ('warning','critical') THEN 1 ELSE 0 END,
--       CASE WHEN c.effective_status<>json_extract(c.value,'$.status') THEN
--         CASE WHEN c.prior_problem_open=1 THEN 'Recovery invocation not verified; original problem remains open'
--           ELSE 'Natural invocation not verified; execution health remains unknown' END
--         ELSE json_extract(c.value,'$.summary') END,
--       c.value
--     FROM (
--       SELECT c.value, previous.problem_open AS prior_problem_open, CASE WHEN json_extract(c.value,'$.status')='ok'
--         AND json_extract(c.value,'$.id') IN ('cloud-service:trade-public-fund-daily.service','cloud-service:trade-overfit-monitor.service')
--         THEN CASE WHEN json_extract(c.value,'$.evidence.execution_state')='completed'
--           AND json_type(c.value,'$.evidence.exit_code')='integer'
--           AND json_extract(c.value,'$.evidence.exit_code')=0
--           AND json_extract(c.value,'$.evidence.unit_result')='success'
--           AND json_type(c.value,'$.evidence.invocation_id')='text'
--           AND length(json_extract(c.value,'$.evidence.invocation_id'))=32
--           AND json_extract(c.value,'$.evidence.invocation_id') NOT GLOB '*[^0-9a-f]*'
--           AND json_type(c.value,'$.evidence.last_start_utc')='text'
--           AND json_type(c.value,'$.evidence.last_exit_utc')='text'
--           AND json_extract(c.value,'$.evidence.last_start_utc') GLOB '????-??-??T??:??:??*'
--           AND json_extract(c.value,'$.evidence.last_exit_utc') GLOB '????-??-??T??:??:??*'
--           AND (json_extract(c.value,'$.evidence.last_start_utc') GLOB '*Z' OR json_extract(c.value,'$.evidence.last_start_utc') GLOB '*[+-]??:??')
--           AND (json_extract(c.value,'$.evidence.last_exit_utc') GLOB '*Z' OR json_extract(c.value,'$.evidence.last_exit_utc') GLOB '*[+-]??:??')
--           AND julianday(json_extract(c.value,'$.evidence.last_start_utc')) IS NOT NULL
--           AND julianday(json_extract(c.value,'$.evidence.last_exit_utc')) IS NOT NULL
--           AND ((previous.recovery_failure_ms IS NULL AND COALESCE(previous.problem_open,0)=0)
--             OR (json_extract(c.value,'$.evidence.invocation_id')<>COALESCE(previous.recovery_failure_invocation,'')
--               AND ROUND((julianday(json_extract(c.value,'$.evidence.last_start_utc'))-2440587.5)*86400000)>COALESCE(previous.recovery_failure_ms,previous.observed_ms)))
--           AND julianday(json_extract(c.value,'$.evidence.last_exit_utc'))>=julianday(json_extract(c.value,'$.evidence.last_start_utc'))
--           AND ROUND((julianday(json_extract(c.value,'$.evidence.last_exit_utc'))-2440587.5)*86400000)<=json_extract(c.value,'$._observed_ms') THEN 'ok' ELSE 'unknown' END
--         ELSE json_extract(c.value,'$.status') END AS effective_status
--       FROM json_each(NEW.snapshot_json,'$.checks') c LEFT JOIN ops_check_state previous
--         ON previous.collector_id=NEW.collector_id AND previous.check_id=json_extract(c.value,'$.id')
--     ) c
--     WHERE NOT EXISTS(SELECT 1 FROM ops_head WHERE id=1 AND
--       (collected_ms>NEW.collected_ms OR (collected_ms=NEW.collected_ms AND snapshot_id>=NEW.snapshot_id)))
--     ON CONFLICT(collector_id,check_id) DO UPDATE SET
--       name=excluded.name,status=excluded.status,observed_ms=excluded.observed_ms,collected_ms=excluded.collected_ms,
--       snapshot_id=excluded.snapshot_id,updated_ms=excluded.updated_ms,summary=excluded.summary,
--       observation_json=excluded.observation_json,
--       problem_open=CASE WHEN excluded.status='ok' THEN 0 WHEN excluded.status IN ('warning','critical') THEN 1 ELSE ops_check_state.problem_open END
--     WHERE excluded.observed_ms>ops_check_state.observed_ms OR
--       (excluded.observed_ms=ops_check_state.observed_ms AND excluded.collected_ms>ops_check_state.collected_ms);
--   UPDATE ops_check_state SET status='unknown',summary='Missing from latest snapshot; coverage unknown; not a recovery',
--     collected_ms=NEW.collected_ms,updated_ms=NEW.received_ms
--     WHERE collector_id=NEW.collector_id AND check_id NOT IN
--       (SELECT json_extract(value,'$.id') FROM json_each(NEW.snapshot_json,'$.checks'))
--     AND NOT EXISTS(SELECT 1 FROM ops_head WHERE id=1 AND
--       (collected_ms>NEW.collected_ms OR (collected_ms=NEW.collected_ms AND snapshot_id>=NEW.snapshot_id)));
--   UPDATE ops_runs SET counts_json=(
--     SELECT json_object('ok',SUM(s.status='ok'),'warning',SUM(s.status='warning'),
--       'critical',SUM(s.status='critical'),'unknown',SUM(s.status='unknown'))
--     FROM json_each(NEW.snapshot_json,'$.checks') c JOIN ops_check_state s
--       ON s.collector_id=NEW.collector_id AND s.check_id=json_extract(c.value,'$.id')
--   ) WHERE snapshot_id=NEW.snapshot_id AND NOT EXISTS(SELECT 1 FROM ops_head WHERE id=1 AND
--     (collected_ms>NEW.collected_ms OR (collected_ms=NEW.collected_ms AND snapshot_id>=NEW.snapshot_id)));
--   INSERT INTO ops_watchdog(id,status,changed_ms)
--     SELECT 1,'fresh',NEW.received_ms WHERE NOT EXISTS(SELECT 1 FROM ops_head WHERE id=1 AND
--       (collected_ms>NEW.collected_ms OR (collected_ms=NEW.collected_ms AND snapshot_id>=NEW.snapshot_id)))
--     ON CONFLICT(id) DO UPDATE SET status='fresh',changed_ms=excluded.changed_ms WHERE ops_watchdog.status<>'fresh';
--   INSERT INTO ops_head VALUES(1,NEW.snapshot_id,NEW.collected_ms)
--     ON CONFLICT(id) DO UPDATE SET snapshot_id=excluded.snapshot_id,collected_ms=excluded.collected_ms
--     WHERE excluded.collected_ms>ops_head.collected_ms OR (excluded.collected_ms=ops_head.collected_ms AND excluded.snapshot_id>ops_head.snapshot_id);
-- END;
-- ============================================================================
