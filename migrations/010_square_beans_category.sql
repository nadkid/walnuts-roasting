ALTER TABLE sale_catalog ADD COLUMN category_ids TEXT NOT NULL DEFAULT '[]';
ALTER TABLE sale_catalog ADD COLUMN in_scope INTEGER NOT NULL DEFAULT 1;
INSERT INTO settings VALUES ('square_category_id','null');
