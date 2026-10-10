-- 0005: composition arrangement mode (M4.6). Existing rows keep the M4/M4.5 planner ("legacy").
ALTER TABLE composition ADD COLUMN mode TEXT NOT NULL DEFAULT 'legacy';
