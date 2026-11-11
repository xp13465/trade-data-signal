-- Forward-only upgrade: preserve the last severe invocation through unknown
-- observations. Restrict policy to the two original severe services.
ALTER TABLE ops_check_state ADD COLUMN recovery_failure_invocation TEXT;
ALTER TABLE ops_check_state ADD COLUMN recovery_failure_ms INTEGER;

UPDATE ops_check_state SET
  recovery_failure_invocation=json_extract(observation_json,'$.evidence.invocation_id'),
  recovery_failure_ms=observed_ms
WHERE problem_open=1 AND check_id IN ('cloud-service:trade-public-fund-daily.service','cloud-service:trade-overfit-monitor.service');

CREATE TRIGGER ops_severe_anchor_insert AFTER INSERT ON ops_check_state
WHEN NEW.status='critical' AND NEW.check_id IN ('cloud-service:trade-public-fund-daily.service','cloud-service:trade-overfit-monitor.service') BEGIN
  UPDATE ops_check_state SET recovery_failure_ms=NEW.observed_ms,
    recovery_failure_invocation=(SELECT json_extract(c.value,'$.evidence.invocation_id')
      FROM ops_runs r,json_each(r.snapshot_json,'$.checks') c
      WHERE r.snapshot_id=NEW.snapshot_id AND json_extract(c.value,'$.id')=NEW.check_id)
  WHERE collector_id=NEW.collector_id AND check_id=NEW.check_id;
END;

CREATE TRIGGER ops_severe_anchor_update AFTER UPDATE ON ops_check_state
WHEN NEW.status='critical' AND NEW.snapshot_id<>OLD.snapshot_id
  AND NEW.check_id IN ('cloud-service:trade-public-fund-daily.service','cloud-service:trade-overfit-monitor.service') BEGIN
  UPDATE ops_check_state SET recovery_failure_ms=NEW.observed_ms,
    recovery_failure_invocation=(SELECT json_extract(c.value,'$.evidence.invocation_id')
      FROM ops_runs r,json_each(r.snapshot_json,'$.checks') c
      WHERE r.snapshot_id=NEW.snapshot_id AND json_extract(c.value,'$.id')=NEW.check_id)
  WHERE collector_id=NEW.collector_id AND check_id=NEW.check_id;
END;

-- Replace the insert trigger in this forward migration, never the deployed 0001.
-- Every row is normalized against current state inside this one transaction;
-- blocked recoveries become unknown while retaining problem_open. Other rows
-- and the watchdog/head still advance. No SELECT-before-batch race or IGNORE.
DROP TRIGGER ops_run_insert;
CREATE TRIGGER ops_run_insert AFTER INSERT ON ops_runs BEGIN
  INSERT INTO ops_check_state(collector_id,check_id,name,status,observed_ms,collected_ms,snapshot_id,updated_ms,problem_open,summary)
    SELECT NEW.collector_id,json_extract(c.value,'$.id'),json_extract(c.value,'$.name'),c.effective_status,
      json_extract(c.value,'$._observed_ms'),NEW.collected_ms,NEW.snapshot_id,NEW.received_ms,
      CASE WHEN c.effective_status IN ('warning','critical') THEN 1 ELSE 0 END,
      CASE WHEN c.effective_status<>json_extract(c.value,'$.status') THEN 'Recovery invocation not verified; original problem remains open' ELSE json_extract(c.value,'$.summary') END
    FROM (
      SELECT c.value, CASE WHEN previous.problem_open=1 AND json_extract(c.value,'$.status')='ok'
        AND json_extract(c.value,'$.id') IN ('cloud-service:trade-public-fund-daily.service','cloud-service:trade-overfit-monitor.service')
        THEN CASE WHEN json_extract(c.value,'$.evidence.execution_state')='completed'
          AND json_extract(c.value,'$.evidence.exit_code')=0
          AND json_extract(c.value,'$.evidence.unit_result')='success'
          AND length(json_extract(c.value,'$.evidence.invocation_id'))=32
          AND json_extract(c.value,'$.evidence.invocation_id') NOT GLOB '*[^0-9a-f]*'
          AND json_extract(c.value,'$.evidence.invocation_id')<>COALESCE(previous.recovery_failure_invocation,'')
          AND julianday(json_extract(c.value,'$.evidence.last_start_utc')) IS NOT NULL
          AND julianday(json_extract(c.value,'$.evidence.last_exit_utc')) IS NOT NULL
          AND ROUND((julianday(json_extract(c.value,'$.evidence.last_start_utc'))-2440587.5)*86400000)>COALESCE(previous.recovery_failure_ms,previous.observed_ms)
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

-- Last statement marks the complete policy; new Worker refuses ingest without it.
CREATE TABLE ops_recovery_policy(id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL);
INSERT INTO ops_recovery_policy VALUES(1,1);
