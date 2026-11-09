-- Reporting projections do not change inventory or the immutable stock ledger.
CREATE TABLE order_financials(
 order_id TEXT PRIMARY KEY REFERENCES orders(id), currency TEXT NOT NULL,
 sold_at TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE square_return_orders(
 id TEXT PRIMARY KEY, version INTEGER NOT NULL, updated_at TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE fulfillment_picks(
 id INTEGER PRIMARY KEY AUTOINCREMENT, fulfillment_id TEXT NOT NULL REFERENCES fulfillment_events(id),
 line_id TEXT NOT NULL REFERENCES lines(id), stock_id TEXT NOT NULL REFERENCES stocks(id),
 movement_id TEXT NOT NULL REFERENCES movements(id), quantity_mg INTEGER NOT NULL CHECK(quantity_mg>0),
 overfill_mg INTEGER NOT NULL DEFAULT 0 CHECK(overfill_mg>=0)
);
CREATE INDEX fulfillment_picks_line ON fulfillment_picks(line_id);
CREATE TRIGGER fulfillment_picks_no_update BEFORE UPDATE ON fulfillment_picks BEGIN SELECT RAISE(ABORT,'Fulfillment picks are immutable'); END;
CREATE TRIGGER fulfillment_picks_no_delete BEFORE DELETE ON fulfillment_picks BEGIN SELECT RAISE(ABORT,'Fulfillment picks are immutable'); END;
CREATE TABLE order_shipping(
 order_id TEXT PRIMARY KEY REFERENCES orders(id), currency TEXT NOT NULL,
 mode TEXT NOT NULL CHECK(mode IN ('shipping','pickup')), parcels TEXT NOT NULL,
 version INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL, actor TEXT NOT NULL
);
