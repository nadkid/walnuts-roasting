CREATE TABLE cafe_orders(
 order_id TEXT PRIMARY KEY REFERENCES orders(id),
 requested_by TEXT NOT NULL,
 version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE cafe_order_lines(
 line_id TEXT PRIMARY KEY REFERENCES lines(id),
 form TEXT NOT NULL CHECK(form IN ('bulk','bags')),
 requested_mg INTEGER NOT NULL CHECK(requested_mg>0),
 delivered_mg INTEGER NOT NULL DEFAULT 0 CHECK(delivered_mg>=0 AND delivered_mg<=requested_mg)
);
CREATE TABLE cafe_deliveries(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 order_id TEXT NOT NULL REFERENCES cafe_orders(order_id),
 line_id TEXT NOT NULL REFERENCES cafe_order_lines(line_id),
 movement_id TEXT NOT NULL REFERENCES movements(id),
 source_stock_id TEXT NOT NULL REFERENCES stocks(id),
 destination_stock_id TEXT NOT NULL REFERENCES stocks(id),
 quantity_mg INTEGER NOT NULL CHECK(quantity_mg>0),
 overfill_mg INTEGER NOT NULL DEFAULT 0 CHECK(overfill_mg>=0)
);
CREATE TRIGGER cafe_deliveries_no_update BEFORE UPDATE ON cafe_deliveries BEGIN SELECT RAISE(ABORT,'Cafe delivery history is immutable'); END;
CREATE TRIGGER cafe_deliveries_no_delete BEFORE DELETE ON cafe_deliveries BEGIN SELECT RAISE(ABORT,'Cafe delivery history is immutable'); END;
