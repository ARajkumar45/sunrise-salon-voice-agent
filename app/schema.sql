-- Database schema. Safe to run many times (IF NOT EXISTS everywhere).
-- Every table that holds business data has a business_id, and every query filters on it.

CREATE TABLE IF NOT EXISTS businesses (
    id                      SERIAL PRIMARY KEY,
    slug                    TEXT NOT NULL UNIQUE,          -- used in the call page URL
    name                    TEXT NOT NULL,
    timezone                TEXT NOT NULL,                 -- e.g. Asia/Kolkata
    address                 TEXT NOT NULL,
    slot_minutes            INT  NOT NULL DEFAULT 30,
    greeting                TEXT NOT NULL,                 -- first thing the agent says
    staff_word              TEXT NOT NULL DEFAULT 'staff member',  -- "stylist", "mechanic", ...
    free_cancellation_hours INT  NOT NULL DEFAULT 0,
    not_offered             TEXT[] NOT NULL DEFAULT '{}',
    notes                   TEXT[] NOT NULL DEFAULT '{}'   -- extra facts, one sentence each
);

CREATE TABLE IF NOT EXISTS staff (
    id          SERIAL PRIMARY KEY,
    business_id INT  NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    does        TEXT NOT NULL DEFAULT '',
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (business_id, name)
);

-- One row per working day. weekday: 0 = Monday ... 6 = Sunday.
CREATE TABLE IF NOT EXISTS staff_hours (
    staff_id   INT  NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    weekday    INT  NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    start_time TIME NOT NULL,
    end_time   TIME NOT NULL,
    PRIMARY KEY (staff_id, weekday)
);

CREATE TABLE IF NOT EXISTS services (
    id          SERIAL PRIMARY KEY,
    business_id INT  NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    staff_id    INT  NOT NULL REFERENCES staff(id),
    name        TEXT NOT NULL,
    price       TEXT NOT NULL,                             -- text, so "From Rs 2,500" works
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (business_id, name)
);

CREATE TABLE IF NOT EXISTS faqs (
    id          SERIAL PRIMARY KEY,
    business_id INT  NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    topic       TEXT NOT NULL,
    answer      TEXT NOT NULL
);

-- One row per phone call.
CREATE TABLE IF NOT EXISTS calls (
    id          SERIAL PRIMARY KEY,
    business_id INT  NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    room        TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at    TIMESTAMPTZ
);

-- Everything that happened on a call, in order: what was said, tool calls, timings.
CREATE TABLE IF NOT EXISTS call_events (
    id      BIGSERIAL PRIMARY KEY,
    call_id INT  NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind    TEXT NOT NULL,      -- said | tool | latency | interruption | silence | error
    data    JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS call_events_call ON call_events (call_id, id);
