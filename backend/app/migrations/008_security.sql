-- Daily cost counters (app/quota.py): pages started for translation and newly synthesized speech characters.
CREATE TABLE IF NOT EXISTS usage_daily (
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  day date NOT NULL DEFAULT CURRENT_DATE,
  pages integer NOT NULL DEFAULT 0,
  tts_chars integer NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, day)
);
CREATE INDEX IF NOT EXISTS usage_daily_day_idx ON usage_daily (day);

-- Bumped on password reset: tokens carrying an older version stop working (app/auth.py).
ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version integer NOT NULL DEFAULT 0;

-- The Stripe customer created for this account at checkout (never looked up by e-mail).
ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id text;
