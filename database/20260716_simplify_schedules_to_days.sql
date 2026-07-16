-- Schedule entries represent a working day and competence only.
-- Run once against existing databases before deploying the updated backend.
ALTER TABLE schedules
    DROP COLUMN IF EXISTS shift_start,
    DROP COLUMN IF EXISTS shift_end;
