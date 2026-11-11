-- Historical shipments can be reconciled without inventing an inventory pick.
CREATE TABLE fulfillment_reconciliations(
 id TEXT PRIMARY KEY,
 fulfillment_id TEXT NOT NULL REFERENCES fulfillment_events(id),
 action TEXT NOT NULL CHECK(action IN ('pre_dashboard','reopen')),
 at TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL,
 request_id TEXT NOT NULL UNIQUE, payload_hash TEXT NOT NULL
);
CREATE INDEX fulfillment_reconciliation_history ON fulfillment_reconciliations(fulfillment_id);
CREATE TRIGGER fulfillment_reconciliations_no_update BEFORE UPDATE ON fulfillment_reconciliations BEGIN SELECT RAISE(ABORT,'Shipment reconciliation history is immutable'); END;
CREATE TRIGGER fulfillment_reconciliations_no_delete BEFORE DELETE ON fulfillment_reconciliations BEGIN SELECT RAISE(ABORT,'Shipment reconciliation history is immutable'); END;
