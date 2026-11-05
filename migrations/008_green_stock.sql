CREATE TABLE green_beans(
 id TEXT PRIMARY KEY,name TEXT NOT NULL,origin TEXT NOT NULL DEFAULT '',
 variety TEXT NOT NULL DEFAULT '',process TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',
 currency TEXT NOT NULL DEFAULT 'JPY',version INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE green_coffee_links(
 coffee_id TEXT PRIMARY KEY REFERENCES coffees(id),bean_id TEXT NOT NULL REFERENCES green_beans(id)
);
CREATE TABLE green_events(
 id INTEGER PRIMARY KEY AUTOINCREMENT,bean_id TEXT NOT NULL REFERENCES green_beans(id),
 kind TEXT NOT NULL CHECK(kind IN ('purchase','count','roast','reversal')),
 effective_at TEXT NOT NULL,recorded_at TEXT NOT NULL,delta_mg INTEGER NOT NULL DEFAULT 0,
 count_mg INTEGER CHECK(count_mg>=0),total_minor INTEGER CHECK(total_minor>=0),
 supplier TEXT NOT NULL DEFAULT '',reference TEXT NOT NULL DEFAULT '',lot TEXT NOT NULL DEFAULT '',
 reason TEXT NOT NULL DEFAULT '',actor TEXT NOT NULL,movement_id TEXT NOT NULL REFERENCES movements(id),
 batch_id TEXT UNIQUE REFERENCES batches(id),reversal_of INTEGER UNIQUE REFERENCES green_events(id)
);
CREATE INDEX green_events_bean ON green_events(bean_id,effective_at);
CREATE TRIGGER green_events_no_update BEFORE UPDATE ON green_events BEGIN SELECT RAISE(ABORT,'Green stock history is immutable'); END;
CREATE TRIGGER green_events_no_delete BEFORE DELETE ON green_events BEGIN SELECT RAISE(ABORT,'Green stock history is immutable'); END;
