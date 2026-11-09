-- Preserve foreign-key identities, price links and historical reporting.
CREATE TABLE coffee_archives(
 coffee_id TEXT PRIMARY KEY REFERENCES coffees(id),
 archived_at TEXT NOT NULL, actor TEXT NOT NULL
);
