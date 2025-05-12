-- db/init.sql
BEGIN;

-- 1) Tenants: tracks your authenticated users
CREATE TABLE IF NOT EXISTS tenants (
  id          SERIAL       PRIMARY KEY,
  user_id     TEXT         UNIQUE   NOT NULL,
  created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS page_tokens (
  tenant_id    INTEGER  REFERENCES tenants(id),
  page_id      TEXT     PRIMARY KEY,
  access_token TEXT     NOT NULL,
  installed_at TIMESTAMPTZ DEFAULT now()
);


-- 2) Posts: page status updates and other items
CREATE TABLE IF NOT EXISTS posts (
  id          TEXT         PRIMARY KEY,
  page_id     TEXT         NOT NULL,    -- the Page generating this post
  message     TEXT,
  from_id     TEXT,                    -- actor (could be same as page_id)
  from_name   TEXT,
  verb        TEXT,                    -- like "add", "edited"
  published   BOOLEAN,                 -- published flag
  created_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at);

-- 3) Comments: threaded replies to posts or to other comments
CREATE TABLE IF NOT EXISTS comments (
  id          TEXT         PRIMARY KEY,
  page_id     TEXT         NOT NULL,
  post_id     TEXT         NOT NULL,    -- which post this comment belongs to
  text        TEXT         NOT NULL,
  platform    TEXT         NOT NULL,    -- 'facebook' or 'instagram'
  parent_id   TEXT,                    -- reply to another comment
  user_id     TEXT,                    -- commenter’s ID
  user_name   TEXT,                    -- commenter’s name
  verb        TEXT,                    -- like 'add', 'edited'
  created_at  TIMESTAMPTZ NOT NULL,
  CONSTRAINT fk_comments_post   FOREIGN KEY (post_id)   REFERENCES posts(id),
  CONSTRAINT fk_comments_parent FOREIGN KEY (parent_id) REFERENCES comments(id),
  replied   BOOLEAN NOT NULL DEFAULT FALSE,
  reply_id  TEXT
);
CREATE INDEX IF NOT EXISTS idx_comments_created_at ON comments(created_at);


-- 4) Mentions: when your Page is mentioned in a post or comment
CREATE TABLE IF NOT EXISTS mentions (
  id           TEXT         PRIMARY KEY,  -- e.g. mention-<post_id>-<sender_id>-<ts>
  post_id      TEXT         NOT NULL,
  sender_id    TEXT         NOT NULL,
  sender_name  TEXT,
  verb         TEXT         NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL,
  CONSTRAINT fk_mentions_post FOREIGN KEY (post_id) REFERENCES posts(id)
);
CREATE INDEX IF NOT EXISTS idx_mentions_created_at ON mentions(created_at);

-- 5) Messages: direct messages and Messenger events
CREATE TABLE IF NOT EXISTS messages (
  id             TEXT         PRIMARY KEY,
  thread_id      TEXT         NOT NULL,
  sender_id      TEXT         NOT NULL,
  recipient_id   TEXT         NOT NULL,
  message        TEXT         NOT NULL,
  platform       TEXT         NOT NULL,    -- 'facebook' or 'instagram'
  verb           TEXT,                   -- e.g. 'sent', 'delivered', 'read'
  created_at     TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);

-- 6) Per-Page settings (one row per Page ID)
CREATE TABLE IF NOT EXISTS page_settings (
  page_id            TEXT    PRIMARY KEY,       -- e.g. “373583083509912”
  auto_reply_enabled BOOLEAN NOT NULL DEFAULT TRUE
);

-- No seed rows here; we’ll INSERT on first webhook
CREATE TABLE IF NOT EXISTS replies (
    id          SERIAL       PRIMARY KEY,
    post_id     TEXT         NOT NULL,
    reply_text  TEXT         NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    sent        BOOLEAN      NOT NULL DEFAULT FALSE
);


COMMIT;
