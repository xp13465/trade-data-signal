-- D1 free-tier daily read quota exhaustion (2026-11-12 UTC account rows_read 5,352,802 >
-- 5,000,000; burn-out ~UTC 23:15-23:30 daily): the 0003 observation triggers re-unpacked
-- ops_runs.snapshot_json once per ops_check_state upsert (186x per ingest round, ~95
-- json_each rows each, measured rows_read=2..187 per lookup on the live D1). This
-- forward-only migration keeps the exact 0001/0003/0005 semantics but writes
-- observation_json inline from the single json_each pass that ops_run_insert already
-- performs, then drops the two redundant observation triggers.
-- Severe anchor / recovery invocation semantics from 0005 are preserved verbatim
-- (only the two observation_json additions differ from the 0005 trigger body below);
-- ops_recovery_policy stays at version 2 and is not touched.

DROP TRIGGER ops_check_observation_insert;
DROP TRIGGER ops_check_observation_update;

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
    WHERE excluded.observed_ms>ops_check_state.observed_ms OR
      (excluded.observed_ms=ops_check_state.observed_ms AND excluded.collected_ms>ops_check_state.collected_ms);
  UPDATE ops_check_state SET status='unknown',summary='Missing from latest snapshot; coverage unknown; not a recovery',
    collected_ms=NEW.collected_ms,updated_ms=NEW.received_ms
    WHERE collector_id=NEW.collector_id AND check_id NOT IN
      (SELECT json_extract(value,'$.id') FROM json_each(NEW.snapshot_json,'$.checks'))
    AND NOT EXISTS(SELECT 1 FROM ops_head WHERE id=1 AND
      (collected_ms>NEW.collected_ms OR (collected_ms=NEW.collected_ms AND snapshot_id>=NEW.snapshot_id)));
  -- ACK/history counts describe the atomically elected states, not an unverified
  -- producer claim of recovery. Duplicates retain these first-ingest counts.
  UPDATE ops_runs SET counts_json=(
    SELECT json_object('ok',SUM(s.status='ok'),'warning',SUM(s.status='warning'),
      'critical',SUM(s.status='critical'),'unknown',SUM(s.status='unknown'))
    FROM json_each(NEW.snapshot_json,'$.checks') c JOIN ops_check_state s
      ON s.collector_id=NEW.collector_id AND s.check_id=json_extract(c.value,'$.id')
  ) WHERE snapshot_id=NEW.snapshot_id AND NOT EXISTS(SELECT 1 FROM ops_head WHERE id=1 AND
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
-- every statement in this file when the migration runs. To roll back 0006 after
-- stopping the collector timer (see DEPLOY.md §7), execute the SQL below manually via
-- `wrangler d1 execute OPS_DB --remote --config <config> --file <this-extracted-sql>`.
-- It restores the exact pre-0006 trigger set verbatim (0003 observation triggers +
-- the 0005 ops_run_insert without observation_json). No table data is touched:
-- observation_json values written inline are byte-identical to what the 0003
-- triggers would have written for the same snapshots, so no backfill/cleanup is
-- needed in either direction.
--
-- DROP TRIGGER ops_run_insert;
-- CREATE TRIGGER ops_run_insert AFTER INSERT ON ops_runs BEGIN
--   INSERT INTO ops_check_state(collector_id,check_id,name,status,observed_ms,collected_ms,snapshot_id,updated_ms,problem_open,summary)
--     SELECT NEW.collector_id,json_extract(c.value,'$.id'),json_extract(c.value,'$.name'),c.effective_status,
--       json_extract(c.value,'$._observed_ms'),NEW.collected_ms,NEW.snapshot_id,NEW.received_ms,
--       CASE WHEN c.effective_status IN ('warning','critical') THEN 1 ELSE 0 END,
--       CASE WHEN c.effective_status<>json_extract(c.value,'$.status') THEN
--         CASE WHEN c.prior_problem_open=1 THEN 'Recovery invocation not verified; original problem remains open'
--           ELSE 'Natural invocation not verified; execution health remains unknown' END
--         ELSE json_extract(c.value,'$.summary') END
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
--       problem_open=CASE WHEN excluded.status='ok' THEN 0 WHEN excluded.status IN ('warning','critical') THEN 1 ELSE ops_check_state.problem_open END
--     WHERE excluded.observed_ms>ops_check_state.observed_ms OR
--       (excluded.observed_ms=ops_check_state.observed_ms AND excluded.collected_ms>ops_check_state.collected_ms);
--   UPDATE ops_check_state SET status='unknown',summary='Missing from latest snapshot; coverage unknown; not a recovery',
--     collected_ms=NEW.collected_ms,updated_ms=NEW.received_ms
--     WHERE collector_id=NEW.collector_id AND check_id NOT IN
--     (SELECT json_extract(value,'$.id') FROM json_each(NEW.snapshot_json,'$.checks'))
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
-- CREATE TRIGGER ops_check_observation_insert AFTER INSERT ON ops_check_state BEGIN
--   UPDATE ops_check_state SET observation_json=(
--     SELECT c.value FROM ops_runs r, json_each(r.snapshot_json,'$.checks') c
--     WHERE r.snapshot_id=NEW.snapshot_id AND json_extract(c.value,'$.id')=NEW.check_id LIMIT 1
--   ) WHERE collector_id=NEW.collector_id AND check_id=NEW.check_id;
-- END;
-- CREATE TRIGGER ops_check_observation_update AFTER UPDATE ON ops_check_state
-- WHEN NEW.snapshot_id<>OLD.snapshot_id BEGIN
--   UPDATE ops_check_state SET observation_json=(
--     SELECT c.value FROM ops_runs r, json_each(r.snapshot_json,'$.checks') c
--     WHERE r.snapshot_id=NEW.snapshot_id AND json_extract(c.value,'$.id')=NEW.check_id LIMIT 1
--   ) WHERE collector_id=NEW.collector_id AND check_id=NEW.check_id;
-- END;
-- ============================================================================
