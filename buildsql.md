# Standalone Database Build Script (Supabase Compatible)

This file contains the complete SQL query to drop all existing tables, recreate the schema, and populate the database with all necessary initial data (including Gabriel Semanisin, role assignments, clinics, competences, and daily schedules for July 2026).

Copy and run the SQL code block below in your Supabase SQL Editor.

```sql
-- 1. DROP ALL EXISTING TABLES AND SEQUENCES (CASCADE ensures constraints are resolved)
DROP TABLE IF EXISTS public.audit_logs CASCADE;
DROP TABLE IF EXISTS public.schedules CASCADE;
DROP TABLE IF EXISTS public.unavailabilities CASCADE;
DROP TABLE IF EXISTS public.user_competences CASCADE;
DROP TABLE IF EXISTS public.user_ambulances CASCADE;
DROP TABLE IF EXISTS public.user_roles CASCADE;
DROP TABLE IF EXISTS public.competences CASCADE;
DROP TABLE IF EXISTS public.ambulances CASCADE;
DROP TABLE IF EXISTS public.roles CASCADE;
DROP TABLE IF EXISTS public.users CASCADE;

DROP SEQUENCE IF EXISTS public.audit_logs_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.schedules_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.unavailabilities_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.competences_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.ambulances_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.roles_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.users_id_seq CASCADE;

-- 2. CREATE TABLES
CREATE TABLE public.users (
    id integer NOT NULL,
    email character varying NOT NULL,
    full_name character varying,
    auth_token character varying,
    auth_token_expires_at timestamp with time zone,
    login_count integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_active boolean DEFAULT true
);

CREATE TABLE public.roles (
    id integer NOT NULL,
    code character varying NOT NULL,
    name character varying NOT NULL,
    level integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_active boolean DEFAULT true
);

CREATE TABLE public.user_roles (
    user_id integer NOT NULL,
    role_id integer NOT NULL
);

CREATE TABLE public.ambulances (
    id integer NOT NULL,
    name character varying NOT NULL,
    description character varying,
    managed_by_user_id integer,
    isurgent boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_active boolean DEFAULT true
);

CREATE TABLE public.user_ambulances (
    user_id integer NOT NULL,
    ambulance_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    is_active boolean DEFAULT true
);

CREATE TABLE public.competences (
    id integer NOT NULL,
    name character varying NOT NULL,
    description character varying,
    required_count integer DEFAULT 1 NOT NULL,
    ambulance_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_active boolean DEFAULT true
);

CREATE TABLE public.user_competences (
    user_id integer NOT NULL,
    competence_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    is_active boolean DEFAULT true
);

CREATE TABLE public.schedules (
    id integer NOT NULL,
    user_id integer NOT NULL,
    ambulance_id integer NOT NULL,
    competence_id integer NOT NULL,
    work_date date NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_active boolean DEFAULT true
);

CREATE TABLE public.unavailabilities (
    id integer NOT NULL,
    user_id integer NOT NULL,
    date_absent date NOT NULL,
    start_time time without time zone,
    end_time time without time zone,
    reason character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_active boolean DEFAULT true
);

CREATE TABLE public.audit_logs (
    id integer NOT NULL,
    user_id integer,
    action character varying NOT NULL,
    entity_type character varying NOT NULL,
    entity_id character varying NOT NULL,
    changes json,
    created_at timestamp with time zone DEFAULT now()
);

-- 3. CREATE SEQUENCES
CREATE SEQUENCE public.users_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;
ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);

CREATE SEQUENCE public.roles_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.roles_id_seq OWNED BY public.roles.id;
ALTER TABLE ONLY public.roles ALTER COLUMN id SET DEFAULT nextval('public.roles_id_seq'::regclass);

CREATE SEQUENCE public.ambulances_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.ambulances_id_seq OWNED BY public.ambulances.id;
ALTER TABLE ONLY public.ambulances ALTER COLUMN id SET DEFAULT nextval('public.ambulances_id_seq'::regclass);

CREATE SEQUENCE public.competences_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.competences_id_seq OWNED BY public.competences.id;
ALTER TABLE ONLY public.competences ALTER COLUMN id SET DEFAULT nextval('public.competences_id_seq'::regclass);

CREATE SEQUENCE public.schedules_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.schedules_id_seq OWNED BY public.schedules.id;
ALTER TABLE ONLY public.schedules ALTER COLUMN id SET DEFAULT nextval('public.schedules_id_seq'::regclass);

CREATE SEQUENCE public.unavailabilities_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.unavailabilities_id_seq OWNED BY public.unavailabilities.id;
ALTER TABLE ONLY public.unavailabilities ALTER COLUMN id SET DEFAULT nextval('public.unavailabilities_id_seq'::regclass);

CREATE SEQUENCE public.audit_logs_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;
ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);

-- 4. ADD PRIMARY KEYS AND UNIQUE CONSTRAINTS
ALTER TABLE ONLY public.users ADD CONSTRAINT users_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.roles ADD CONSTRAINT roles_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.roles ADD CONSTRAINT roles_code_key UNIQUE (code);
ALTER TABLE ONLY public.user_roles ADD CONSTRAINT user_roles_pkey PRIMARY KEY (user_id, role_id);
ALTER TABLE ONLY public.ambulances ADD CONSTRAINT ambulances_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.user_ambulances ADD CONSTRAINT user_ambulances_pkey PRIMARY KEY (user_id, ambulance_id);
ALTER TABLE ONLY public.competences ADD CONSTRAINT competences_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.user_competences ADD CONSTRAINT user_competences_pkey PRIMARY KEY (user_id, competence_id);
ALTER TABLE ONLY public.schedules ADD CONSTRAINT schedules_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.unavailabilities ADD CONSTRAINT unavailabilities_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.audit_logs ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);

-- 5. CREATE INDEXES
CREATE INDEX ix_users_id ON public.users USING btree (id);
CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);
CREATE INDEX ix_roles_id ON public.roles USING btree (id);
CREATE INDEX ix_ambulances_id ON public.ambulances USING btree (id);
CREATE INDEX ix_competences_id ON public.competences USING btree (id);
CREATE INDEX ix_schedules_id ON public.schedules USING btree (id);
CREATE INDEX ix_unavailabilities_id ON public.unavailabilities USING btree (id);
CREATE INDEX ix_audit_logs_id ON public.audit_logs USING btree (id);

-- 6. ADD FOREIGN KEY CONSTRAINTS
ALTER TABLE ONLY public.ambulances ADD CONSTRAINT ambulances_managed_by_user_id_fkey FOREIGN KEY (managed_by_user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.audit_logs ADD CONSTRAINT audit_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.competences ADD CONSTRAINT competences_ambulance_id_fkey FOREIGN KEY (ambulance_id) REFERENCES public.ambulances(id);
ALTER TABLE ONLY public.schedules ADD CONSTRAINT schedules_ambulance_id_fkey FOREIGN KEY (ambulance_id) REFERENCES public.ambulances(id);
ALTER TABLE ONLY public.schedules ADD CONSTRAINT schedules_competence_id_fkey FOREIGN KEY (competence_id) REFERENCES public.competences(id);
ALTER TABLE ONLY public.schedules ADD CONSTRAINT schedules_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.unavailabilities ADD CONSTRAINT unavailabilities_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.user_ambulances ADD CONSTRAINT user_ambulances_ambulance_id_fkey FOREIGN KEY (ambulance_id) REFERENCES public.ambulances(id);
ALTER TABLE ONLY public.user_ambulances ADD CONSTRAINT user_ambulances_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.user_competences ADD CONSTRAINT user_competences_competence_id_fkey FOREIGN KEY (competence_id) REFERENCES public.competences(id);
ALTER TABLE ONLY public.user_competences ADD CONSTRAINT user_competences_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.user_roles ADD CONSTRAINT user_roles_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id);
ALTER TABLE ONLY public.user_roles ADD CONSTRAINT user_roles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);

-- 7. INSERT DATA

-- 7.1. Roles Setup
INSERT INTO public.roles (id, code, name, level, is_active, created_at, updated_at) VALUES
(1, 'EMPLOYEE', 'Zamestnanec', 1, true, now(), now()),
(2, 'LEADER', 'Veduci', 2, true, now(), now()),
(3, 'AMBULANCE_OVERSEER', 'Dohlad nad ambulanciou', 3, true, now(), now()),
(4, 'HOSPITAL_ADMIN', 'Cela nemocnica', 4, true, now(), now());

-- 7.2. Users Setup
INSERT INTO public.users (id, email, full_name, is_active, login_count, created_at, updated_at) VALUES
(1, 'a14325999@gmail.com', 'Leader A', true, 0, now(), now()),
(2, 'alexthesecond0000@gmail.com', 'Alex the Second', true, 0, now(), now()),
(3, 'noro.michel159@gmail.com', 'Noro Michel 159', true, 0, now(), now()),
(4, 'noro.michel@gmail.com', 'Noro Michel', true, 0, now(), now()),
(5, 'gsemanisin@gmail.com', 'Gabriel Semanisin', true, 0, now(), now()),
(6, 'martin.hudak@example.com', 'Martin Hudak', true, 0, now(), now()),
(7, 'jana.kovacova@example.com', 'Jana Kovacova', true, 0, now(), now()),
(8, 'peter.novak@example.com', 'Peter Novak', true, 0, now(), now()),
(9, 'lucia.horvathova@example.com', 'Lucia Horvathova', true, 0, now(), now()),
(10, 'tomas.balog@example.com', 'Tomas Balog', true, 0, now(), now()),
(11, 'eva.mistrikova@example.com', 'Eva Mistrikova', true, 0, now(), now()),
(12, 'michal.simon@example.com', 'Michal Simon', true, 0, now(), now()),
(13, 'katarina.danko@example.com', 'Katarina Danko', true, 0, now(), now()),
(14, 'andrej.svec@example.com', 'Andrej Svec', true, 0, now(), now()),
(15, 'veronika.krizova@example.com', 'Veronika Krizova', true, 0, now(), now()),
(16, 'filip.benko@example.com', 'Filip Benko', true, 0, now(), now()),
(17, 'nina.molnarova@example.com', 'Nina Molnarova', true, 0, now(), now()),
(18, 'roman.varga@example.com', 'Roman Varga', true, 0, now(), now()),
(19, 'simona.liptakova@example.com', 'Simona Liptakova', true, 0, now(), now()),
(20, 'adam.urban@example.com', 'Adam Urban', true, 0, now(), now());

-- 7.3. User Roles Assignment
INSERT INTO public.user_roles (user_id, role_id) VALUES
-- Leader A
(1, 1), (1, 2),
-- Alex the Second
(2, 1), (2, 2),
-- Noro Michel 159 (Has Role 3)
(3, 1), (3, 2), (3, 3),
-- Noro Michel (Has Role 3 and 4)
(4, 1), (4, 2), (4, 3), (4, 4),
-- Gabriel Semanisin (Has All Roles)
(5, 1), (5, 2), (5, 3), (5, 4),
-- Employees
(6, 1), (7, 1), (8, 1), (9, 1), (10, 1), (11, 1), (12, 1), (13, 1),
(14, 1), (15, 1), (16, 1), (17, 1), (18, 1), (19, 1), (20, 1);

-- 7.4. Ambulances Setup
INSERT INTO public.ambulances (id, name, description, managed_by_user_id, isurgent, is_active, created_at, updated_at) VALUES
(1, 'ambulancia1', 'Prva ambulancia', 3, false, true, now(), now()),
(2, 'ambulancia2', 'Druha ambulancia', 1, false, true, now(), now()),
(3, 'ambulancia3', 'Tretia ambulancia pod rovnakou spravou ako ambulancia1', 3, false, true, now(), now()),
(4, 'ambulancia4', 'Stvrta ambulancia', 1, false, true, now(), now()),
(5, 'urgentna_ambulancia1', 'Urgentna ambulancia pre Leader A', 1, true, true, now(), now()),
(6, 'urgentna_ambulancia2', 'Urgentna ambulancia pre Alex the Second', 2, true, true, now(), now()),
(7, 'urgentna_ambulancia3', 'Urgentna ambulancia pre Noro Michel 159', 3, true, true, now(), now()),
(8, 'urgentna_ambulancia4', 'Urgentna ambulancia pre Noro Michel', 4, true, true, now(), now());

-- 7.5. User Ambulances Assignment
INSERT INTO public.user_ambulances (user_id, ambulance_id, is_active, created_at) VALUES
-- Primary Users
(2, 1, true, now()),
(3, 1, true, now()),
(3, 3, true, now()),
(1, 2, true, now()),
(5, 1, true, now()),
(5, 2, true, now()),
(5, 3, true, now()),
(5, 4, true, now()),
-- Employees - Clinic 1
(6, 1, true, now()), (7, 1, true, now()), (8, 1, true, now()), (9, 1, true, now()),
-- Employees - Clinic 2
(10, 2, true, now()), (11, 2, true, now()), (12, 2, true, now()), (13, 2, true, now()),
-- Employees - Clinic 3
(14, 3, true, now()), (15, 3, true, now()), (16, 3, true, now()), (17, 3, true, now()),
-- Employees - Clinic 4
(18, 4, true, now()), (19, 4, true, now()), (20, 4, true, now());

-- 7.6. Competences Setup
INSERT INTO public.competences (id, name, description, required_count, ambulance_id, is_active, created_at, updated_at) VALUES
(1, 'role1', 'Prva rola pre ambulanciu 1', 1, 1, true, now(), now()),
(2, 'role2', 'Druga rola pre ambulanciu 1', 1, 1, true, now(), now()),
(3, 'role3', 'Tretia rola pre ambulanciu 1', 1, 1, true, now(), now()),
(4, 'rola1', 'Prva rola pre ambulanciu 2', 1, 2, true, now(), now()),
(5, 'rola2', 'Druga rola pre ambulanciu 2', 1, 2, true, now(), now()),
(6, 'triage', 'Triage pre ambulanciu 3', 1, 3, true, now(), now()),
(7, 'odbery', 'Odbery pre ambulanciu 3', 1, 3, true, now(), now()),
(8, 'recepcia', 'Recepcia pre ambulanciu 4', 1, 4, true, now(), now()),
(9, 'kontrola', 'Kontrola pre ambulanciu 4', 1, 4, true, now(), now());

-- 7.7. User Competences Assignment
INSERT INTO public.user_competences (user_id, competence_id, is_active, created_at) VALUES
-- Alex the Second
(2, 1, true, now()), (2, 2, true, now()), (2, 3, true, now()),
-- Noro Michel 159
(3, 1, true, now()), (3, 2, true, now()), (3, 3, true, now()), (3, 6, true, now()), (3, 7, true, now()),
-- Leader A
(1, 4, true, now()), (1, 5, true, now()), (1, 8, true, now()), (1, 9, true, now()),
-- Gabriel Semanisin
(5, 1, true, now()), (5, 2, true, now()), (5, 3, true, now()), (5, 4, true, now()), (5, 5, true, now()), (5, 6, true, now()), (5, 7, true, now()), (5, 8, true, now()), (5, 9, true, now()),
-- Employees
(6, 1, true, now()), (6, 2, true, now()),
(7, 2, true, now()), (7, 3, true, now()),
(8, 1, true, now()), (8, 3, true, now()),
(9, 2, true, now()),
(10, 4, true, now()), (10, 5, true, now()),
(11, 4, true, now()),
(12, 5, true, now()),
(13, 5, true, now()),
(14, 6, true, now()), (14, 7, true, now()),
(15, 6, true, now()),
(16, 7, true, now()),
(17, 6, true, now()), (17, 7, true, now()),
(18, 8, true, now()),
(19, 9, true, now()),
(20, 8, true, now()), (20, 9, true, now());

-- 7.8. Schedules Setup (July 2026 Shift Schedule Data)
INSERT INTO public.schedules (id, user_id, ambulance_id, competence_id, work_date, is_active, created_at, updated_at) VALUES
(1, 6, 1, 1, '2026-07-01', true, now(), now()),
(2, 7, 1, 2, '2026-07-01', true, now(), now()),
(3, 10, 2, 4, '2026-07-01', true, now(), now()),
(4, 14, 3, 6, '2026-07-01', true, now(), now()),
(5, 18, 4, 8, '2026-07-01', true, now(), now()),

(6, 8, 1, 1, '2026-07-02', true, now(), now()),
(7, 9, 1, 2, '2026-07-02', true, now(), now()),
(8, 11, 2, 4, '2026-07-02', true, now(), now()),
(9, 15, 3, 6, '2026-07-02', true, now(), now()),
(10, 19, 4, 9, '2026-07-02', true, now(), now()),

(11, 6, 1, 3, '2026-07-03', true, now(), now()),
(12, 12, 2, 5, '2026-07-03', true, now(), now()),
(13, 16, 3, 7, '2026-07-03', true, now(), now()),
(14, 20, 4, 8, '2026-07-03', true, now(), now()),

(15, 7, 1, 2, '2026-07-06', true, now(), now()),
(16, 13, 2, 5, '2026-07-06', true, now(), now()),
(17, 17, 3, 6, '2026-07-06', true, now(), now()),

(18, 2, 1, 1, '2026-07-07', true, now(), now()),
(19, 3, 1, 3, '2026-07-07', true, now(), now()),
(20, 5, 2, 4, '2026-07-07', true, now(), now()),

(21, 5, 1, 1, '2026-07-08', true, now(), now()),
(22, 6, 1, 2, '2026-07-08', true, now(), now()),
(23, 10, 2, 5, '2026-07-08', true, now(), now()),

(24, 2, 1, 2, '2026-07-09', true, now(), now()),
(25, 3, 3, 7, '2026-07-09', true, now(), now()),
(26, 5, 4, 8, '2026-07-09', true, now(), now()),

(27, 5, 3, 6, '2026-07-10', true, now(), now()),
(28, 14, 3, 7, '2026-07-10', true, now(), now()),

(29, 6, 1, 1, '2026-07-13', true, now(), now()),
(30, 7, 1, 3, '2026-07-13', true, now(), now()),
(31, 10, 2, 4, '2026-07-13', true, now(), now()),
(32, 18, 4, 9, '2026-07-13', true, now(), now()),

(33, 8, 1, 2, '2026-07-14', true, now(), now()),
(34, 11, 2, 5, '2026-07-14', true, now(), now()),
(35, 15, 3, 7, '2026-07-14', true, now(), now()),

(36, 9, 1, 3, '2026-07-15', true, now(), now()),
(37, 12, 2, 4, '2026-07-15', true, now(), now()),
(38, 16, 3, 6, '2026-07-15', true, now(), now()),

(39, 3, 1, 2, '2026-07-16', true, now(), now()),
(40, 5, 1, 3, '2026-07-16', true, now(), now()),
(41, 13, 2, 5, '2026-07-16', true, now(), now()),

(42, 2, 1, 1, '2026-07-17', true, now(), now()),
(43, 5, 2, 5, '2026-07-17', true, now(), now()),
(44, 17, 3, 7, '2026-07-17', true, now(), now());

-- 8. RESET SEQUENCES (Critical for Supabase to auto-increment from current IDs without duplicate key errors)
SELECT setval(pg_get_serial_sequence('public.users', 'id'), coalesce(max(id), 1)) FROM public.users;
SELECT setval(pg_get_serial_sequence('public.roles', 'id'), coalesce(max(id), 1)) FROM public.roles;
SELECT setval(pg_get_serial_sequence('public.ambulances', 'id'), coalesce(max(id), 1)) FROM public.ambulances;
SELECT setval(pg_get_serial_sequence('public.competences', 'id'), coalesce(max(id), 1)) FROM public.competences;
SELECT setval(pg_get_serial_sequence('public.schedules', 'id'), coalesce(max(id), 1)) FROM public.schedules;
SELECT setval(pg_get_serial_sequence('public.unavailabilities', 'id'), coalesce(max(id), 1)) FROM public.unavailabilities;
SELECT setval(pg_get_serial_sequence('public.audit_logs', 'id'), coalesce(max(id), 1)) FROM public.audit_logs;
```
