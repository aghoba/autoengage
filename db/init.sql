-- db/init.sql
CREATE TABLE IF NOT EXISTS tenants (
  id          SERIAL      PRIMARY KEY,
  user_id     TEXT        UNIQUE   NOT NULL,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);
