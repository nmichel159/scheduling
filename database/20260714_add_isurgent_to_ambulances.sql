ALTER TABLE public.ambulances
ADD COLUMN IF NOT EXISTS isurgent boolean DEFAULT false;

UPDATE public.ambulances
SET isurgent = false
WHERE isurgent IS NULL;
