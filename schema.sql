
-- Create enum type for supported network protocols (safe if already exists)
DO $$ BEGIN
  CREATE TYPE protocol_type AS ENUM ('HTTP', 'HTTPS', 'FTP', 'SSH');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Create enum type for server health status values (safe if already exists)
DO $$ BEGIN
  CREATE TYPE health_status_type AS ENUM ('UNKNOWN', 'HEALTHY', 'UNHEALTHY');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Main table storing monitored servers and their current health state
CREATE TABLE IF NOT EXISTS servers (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  protocol protocol_type NOT NULL,
  health_status health_status_type NOT NULL DEFAULT 'UNKNOWN',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Stores historical health check results for each server
CREATE TABLE IF NOT EXISTS requests (
  id BIGSERIAL PRIMARY KEY,
  server_id BIGINT NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
  checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  is_success BOOLEAN NOT NULL,
  latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
  http_status INTEGER NULL,
  error TEXT NULL
);

-- Index for fast lookup of recent checks per server
CREATE INDEX IF NOT EXISTS idx_requests_server_checked
  ON requests(server_id, checked_at DESC);
