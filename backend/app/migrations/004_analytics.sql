-- Usage analytics: one row per browser tab session, one row per event (page view, click, shortcut key,
-- sampled mouse path, page leave, script error). Additive; no existing table changes.

CREATE TABLE analytics_sessions (
  id uuid PRIMARY KEY,                 -- generated in the browser, kept in sessionStorage (one per tab session)
  visitor_id uuid,                     -- kept in localStorage: links sessions of one browser, signed in or not
  user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  ip inet,
  user_agent text,
  language text,
  timezone text,
  referrer text,
  screen_w integer,
  screen_h integer,
  started_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX analytics_sessions_user_idx ON analytics_sessions (user_id, started_at DESC);
CREATE INDEX analytics_sessions_started_idx ON analytics_sessions (started_at DESC);

CREATE TABLE analytics_events (
  id bigserial PRIMARY KEY,
  session_id uuid NOT NULL REFERENCES analytics_sessions(id) ON DELETE CASCADE,
  user_id uuid,                        -- the signed-in user at the time of the event (null = signed out)
  ts timestamptz NOT NULL,             -- browser clock
  type text NOT NULL,                  -- pageview | click | key | mouse | leave | error
  path text NOT NULL,                  -- route, e.g. /read/<book id>
  name text,                           -- click: control label; key: key name
  data jsonb
);
CREATE INDEX analytics_events_session_idx ON analytics_events (session_id, ts);
CREATE INDEX analytics_events_type_idx ON analytics_events (type, ts DESC);
