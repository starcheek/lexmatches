-- Every API response with status >= 400, every unhandled exception (with traceback) and every crashed
-- background job. Read through /api/admin/problems.
CREATE TABLE server_errors (
  id bigserial PRIMARY KEY,
  ts timestamptz NOT NULL DEFAULT now(),
  method text NOT NULL,              -- HTTP method, or JOB for a background job
  path text NOT NULL,                -- request path, or the job key (book:<id>, page:<id>)
  status integer,                    -- null for jobs
  duration_ms integer,
  user_id uuid,
  session_id uuid,                   -- analytics session (X-Session header), links to the page events
  ip inet,
  detail text,                       -- the error message the user got
  traceback text                     -- unhandled exceptions only
);
CREATE INDEX server_errors_ts_idx ON server_errors (ts DESC);
