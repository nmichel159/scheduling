--
-- PostgreSQL database dump
--

\restrict enAma9JLYXZEJgQEMXzWndbVgPGHiFyqb6P5dVblLap1nFe0nbeg4EhdnxQO3IX

-- Dumped from database version 15.17
-- Dumped by pg_dump version 15.17

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: ambulances; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ambulances (
    id integer NOT NULL,
    name character varying NOT NULL,
    description character varying,
    managed_by_user_id integer,
    isurgent boolean,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_active boolean
);


--
-- Name: ambulances_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ambulances_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ambulances_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ambulances_id_seq OWNED BY public.ambulances.id;


--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    id integer NOT NULL,
    user_id integer,
    action character varying NOT NULL,
    entity_type character varying NOT NULL,
    entity_id character varying NOT NULL,
    changes json,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;


--
-- Name: competences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.competences (
    id integer NOT NULL,
    name character varying NOT NULL,
    description character varying,
    ambulance_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_active boolean
);


--
-- Name: competences_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.competences_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: competences_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.competences_id_seq OWNED BY public.competences.id;


--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    id integer NOT NULL,
    code character varying NOT NULL,
    name character varying NOT NULL,
    level integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_active boolean
);


--
-- Name: roles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.roles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.roles_id_seq OWNED BY public.roles.id;


--
-- Name: schedules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schedules (
    id integer NOT NULL,
    user_id integer NOT NULL,
    ambulance_id integer NOT NULL,
    competence_id integer NOT NULL,
    work_date date NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_active boolean
);


--
-- Name: schedules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.schedules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: schedules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.schedules_id_seq OWNED BY public.schedules.id;


--
-- Name: unavailabilities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.unavailabilities (
    id integer NOT NULL,
    user_id integer NOT NULL,
    date_absent date NOT NULL,
    start_time time without time zone,
    end_time time without time zone,
    reason character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_active boolean
);


--
-- Name: unavailabilities_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.unavailabilities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: unavailabilities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.unavailabilities_id_seq OWNED BY public.unavailabilities.id;


--
-- Name: user_ambulances; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_ambulances (
    user_id integer NOT NULL,
    ambulance_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    is_active boolean
);


--
-- Name: user_competences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_competences (
    user_id integer NOT NULL,
    competence_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    is_active boolean
);


--
-- Name: user_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_roles (
    user_id integer NOT NULL,
    role_id integer NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id integer NOT NULL,
    email character varying NOT NULL,
    full_name character varying,
    auth_token character varying,
    login_count integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_active boolean
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: ambulances id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ambulances ALTER COLUMN id SET DEFAULT nextval('public.ambulances_id_seq'::regclass);


--
-- Name: audit_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);


--
-- Name: competences id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competences ALTER COLUMN id SET DEFAULT nextval('public.competences_id_seq'::regclass);


--
-- Name: roles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles ALTER COLUMN id SET DEFAULT nextval('public.roles_id_seq'::regclass);


--
-- Name: schedules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schedules ALTER COLUMN id SET DEFAULT nextval('public.schedules_id_seq'::regclass);


--
-- Name: unavailabilities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unavailabilities ALTER COLUMN id SET DEFAULT nextval('public.unavailabilities_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: ambulances ambulances_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ambulances
    ADD CONSTRAINT ambulances_pkey PRIMARY KEY (id);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: competences competences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competences
    ADD CONSTRAINT competences_pkey PRIMARY KEY (id);


--
-- Name: roles roles_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_code_key UNIQUE (code);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: schedules schedules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schedules
    ADD CONSTRAINT schedules_pkey PRIMARY KEY (id);


--
-- Name: unavailabilities unavailabilities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unavailabilities
    ADD CONSTRAINT unavailabilities_pkey PRIMARY KEY (id);


--
-- Name: user_ambulances user_ambulances_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_ambulances
    ADD CONSTRAINT user_ambulances_pkey PRIMARY KEY (user_id, ambulance_id);


--
-- Name: user_competences user_competences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_competences
    ADD CONSTRAINT user_competences_pkey PRIMARY KEY (user_id, competence_id);


--
-- Name: user_roles user_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_pkey PRIMARY KEY (user_id, role_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: ix_ambulances_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ambulances_id ON public.ambulances USING btree (id);


--
-- Name: ix_audit_logs_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_id ON public.audit_logs USING btree (id);


--
-- Name: ix_competences_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_competences_id ON public.competences USING btree (id);


--
-- Name: ix_roles_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_roles_id ON public.roles USING btree (id);


--
-- Name: ix_schedules_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_schedules_id ON public.schedules USING btree (id);


--
-- Name: ix_unavailabilities_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_unavailabilities_id ON public.unavailabilities USING btree (id);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_id ON public.users USING btree (id);


--
-- Name: ambulances ambulances_managed_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ambulances
    ADD CONSTRAINT ambulances_managed_by_user_id_fkey FOREIGN KEY (managed_by_user_id) REFERENCES public.users(id);


--
-- Name: audit_logs audit_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: competences competences_ambulance_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competences
    ADD CONSTRAINT competences_ambulance_id_fkey FOREIGN KEY (ambulance_id) REFERENCES public.ambulances(id);


--
-- Name: schedules schedules_ambulance_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schedules
    ADD CONSTRAINT schedules_ambulance_id_fkey FOREIGN KEY (ambulance_id) REFERENCES public.ambulances(id);


--
-- Name: schedules schedules_competence_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schedules
    ADD CONSTRAINT schedules_competence_id_fkey FOREIGN KEY (competence_id) REFERENCES public.competences(id);


--
-- Name: schedules schedules_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schedules
    ADD CONSTRAINT schedules_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: unavailabilities unavailabilities_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unavailabilities
    ADD CONSTRAINT unavailabilities_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: user_ambulances user_ambulances_ambulance_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_ambulances
    ADD CONSTRAINT user_ambulances_ambulance_id_fkey FOREIGN KEY (ambulance_id) REFERENCES public.ambulances(id);


--
-- Name: user_ambulances user_ambulances_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_ambulances
    ADD CONSTRAINT user_ambulances_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: user_competences user_competences_competence_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_competences
    ADD CONSTRAINT user_competences_competence_id_fkey FOREIGN KEY (competence_id) REFERENCES public.competences(id);


--
-- Name: user_competences user_competences_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_competences
    ADD CONSTRAINT user_competences_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: user_roles user_roles_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id);


--
-- Name: user_roles user_roles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- PostgreSQL database dump complete
--

\unrestrict enAma9JLYXZEJgQEMXzWndbVgPGHiFyqb6P5dVblLap1nFe0nbeg4EhdnxQO3IX

