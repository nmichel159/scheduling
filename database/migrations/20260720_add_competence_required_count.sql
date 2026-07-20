ALTER TABLE public.competences
    ADD COLUMN IF NOT EXISTS required_count integer NOT NULL DEFAULT 1;

ALTER TABLE public.competences
    ADD CONSTRAINT competences_required_count_positive CHECK (required_count > 0);
