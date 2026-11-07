-- Persistent first scheduled observation; NULL covers pre-migration/ingest-first rows.
ALTER TABLE ops_watchdog ADD COLUMN first_seen_ms INTEGER;
