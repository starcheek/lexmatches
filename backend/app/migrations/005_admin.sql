-- Owner-controlled switches, changed from the /admin page (no restart). Missing key = default.
CREATE TABLE app_settings (
  key text PRIMARY KEY,
  value jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
