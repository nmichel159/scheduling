-- Run once on existing PostgreSQL databases before deploying the cookie-session
-- authentication update. Fresh databases already receive this column via
-- schema.sql / SQLAlchemy metadata.
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS auth_token_expires_at timestamp with time zone;

CREATE INDEX IF NOT EXISTS ix_users_auth_token ON public.users (auth_token);
