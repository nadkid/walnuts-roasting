CREATE TABLE webhook_deliveries(id TEXT PRIMARY KEY,event_id TEXT NOT NULL,topic TEXT NOT NULL,payload_hash TEXT NOT NULL,received_at TEXT NOT NULL,processed_at TEXT);
CREATE INDEX webhook_pending ON webhook_deliveries(processed_at,received_at);
