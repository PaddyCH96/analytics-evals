-- Query-history extraction templates.
-- Pick the block for your warehouse. Adjust the service-account and application
-- filters to match your stack before running -- the defaults are a starting point,
-- not a complete list.


-- ============================================================================
-- SNOWFLAKE
-- ----------------------------------------------------------------------------
-- Needs a role with IMPORTED PRIVILEGES on the SNOWFLAKE database.
-- ACCOUNT_USAGE has up to 45 minutes of latency and 365 days of retention.
-- ============================================================================

SELECT
    q.query_id,
    q.query_text,
    q.database_name,
    q.schema_name,
    q.user_name,
    q.role_name,
    q.start_time,
    q.total_elapsed_time / 1000.0            AS elapsed_seconds,
    q.bytes_scanned,
    q.rows_produced
FROM snowflake.account_usage.query_history AS q
WHERE q.start_time >= DATEADD(day, -90, CURRENT_TIMESTAMP())
  AND q.execution_status = 'SUCCESS'
  AND q.query_type = 'SELECT'
  AND q.rows_produced > 0
  -- keep it cheap enough to re-run many times during evaluation
  AND q.total_elapsed_time < 60000            -- < 60s
  AND q.bytes_scanned < 5 * POW(1024, 3)      -- < 5 GB
  -- drop machine traffic
  AND q.user_name NOT ILIKE ANY ('%DBT%', '%FIVETRAN%', '%AIRBYTE%',
                                 '%AIRFLOW%', '%DAGSTER%', '%SERVICE%',
                                 '%LOOKER%', '%TABLEAU%', '%METABASE%')
  AND q.query_text NOT ILIKE '%information_schema%'
  AND q.query_text NOT ILIKE '%account_usage%'
  AND LENGTH(q.query_text) BETWEEN 80 AND 8000
ORDER BY q.start_time DESC
LIMIT 10000;


-- ============================================================================
-- BIGQUERY
-- ----------------------------------------------------------------------------
-- INFORMATION_SCHEMA.JOBS must be region-qualified. 180 days of retention.
-- Swap JOBS_BY_PROJECT for JOBS_BY_ORGANIZATION to cover every project.
-- ============================================================================

SELECT
    job_id,
    query,
    user_email,
    creation_time,
    TIMESTAMP_DIFF(end_time, start_time, MILLISECOND) / 1000.0 AS elapsed_seconds,
    total_bytes_processed
FROM `region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
  AND job_type    = 'QUERY'
  AND state       = 'DONE'
  AND error_result IS NULL
  AND statement_type = 'SELECT'
  AND cache_hit IS NOT TRUE
  AND total_bytes_processed < 5 * POW(1024, 3)
  AND NOT REGEXP_CONTAINS(
        user_email,
        r'(?i)(gserviceaccount|dbt|fivetran|airbyte|airflow|dagster|looker)')
  AND NOT REGEXP_CONTAINS(LOWER(query), r'information_schema')
  AND LENGTH(query) BETWEEN 80 AND 8000
ORDER BY creation_time DESC
LIMIT 10000;


-- ============================================================================
-- POSTGRES  (pg_stat_statements)
-- ----------------------------------------------------------------------------
-- WARNING: query text here is NORMALISED. Literals are replaced with $1, $2, ...
-- so what you get is a query *shape*, not runnable SQL. You must substitute
-- plausible literals (from the schema, or from a sample of the real data)
-- before the reference SQL will execute. Validate every case afterwards.
--
-- Requires: CREATE EXTENSION pg_stat_statements; and the library preloaded.
-- ============================================================================

SELECT
    s.queryid,
    s.query,
    r.rolname                      AS user_name,
    s.calls,
    s.rows,
    s.total_exec_time / s.calls    AS mean_exec_ms
FROM pg_stat_statements AS s
JOIN pg_roles AS r ON r.oid = s.userid
WHERE s.query ILIKE 'select%'
  AND s.rows > 0
  AND s.total_exec_time / s.calls < 60000
  AND r.rolname NOT ILIKE ANY (ARRAY['%dbt%', '%fivetran%', '%airbyte%',
                                     '%airflow%', '%service%', '%replicat%'])
  AND s.query NOT ILIKE '%pg_catalog%'
  AND s.query NOT ILIKE '%information_schema%'
  AND LENGTH(s.query) BETWEEN 80 AND 8000
ORDER BY s.calls DESC
LIMIT 10000;


-- ============================================================================
-- DATABRICKS  (system.query.history)
-- ----------------------------------------------------------------------------
-- Requires the `system` schema to be enabled for the metastore.
-- ============================================================================

SELECT
    statement_id,
    statement_text,
    executed_by,
    start_time,
    total_duration_ms / 1000.0 AS elapsed_seconds,
    read_bytes
FROM system.query.history
WHERE start_time >= current_timestamp() - INTERVAL 90 DAYS
  AND execution_status  = 'FINISHED'
  AND statement_type    = 'SELECT'
  AND total_duration_ms < 60000
  AND read_bytes < 5 * 1024 * 1024 * 1024
  AND executed_by NOT RLIKE '(?i)(dbt|fivetran|airbyte|airflow|service)'
  AND length(statement_text) BETWEEN 80 AND 8000
ORDER BY start_time DESC
LIMIT 10000;


-- ============================================================================
-- NO QUERY HISTORY AVAILABLE (DuckDB, MotherDuck, SQLite, locked-down warehouse)
-- ----------------------------------------------------------------------------
-- Fall back to dbt. Read target/manifest.json and build cases from:
--   * nodes.*  with resource_type = 'model'   -> "show me <description>"
--   * metrics.*                                -> "<metric> by <dimension> for <period>"
--   * nodes.*  with resource_type = 'test'     -> negative / edge cases
-- Or mine saved questions from Metabase (/api/card), Looker (Looks), or an
-- existing nao project's tests/*.yml.
-- ============================================================================
