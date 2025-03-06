
-- SEQUENCE: public.fipe_vehicle_manufacturer_id_seq

-- DROP SEQUENCE IF EXISTS public.fipe_vehicle_manufacturer_id_seq;

CREATE SEQUENCE IF NOT EXISTS public.fipe_vehicle_manufacturer_id_seq
    INCREMENT 1
    START 1
    MINVALUE 1
    MAXVALUE 2147483647
    CACHE 1;

-- DROP SEQUENCE IF EXISTS public.fipe_vehicle_model_id_seq;

CREATE SEQUENCE IF NOT EXISTS public.fipe_vehicle_model_id_seq
    INCREMENT 1
    START 1
    MINVALUE 1
    MAXVALUE 2147483647
    CACHE 1;

-- DROP SEQUENCE IF EXISTS public.fipe_vehicle_model_value_id_seq;

CREATE SEQUENCE IF NOT EXISTS public.fipe_vehicle_model_value_id_seq
    INCREMENT 1
    START 1
    MINVALUE 1
    MAXVALUE 2147483647
    CACHE 1;

-- Criar a tabela de fabricantes de veículos

CREATE TABLE IF NOT EXISTS public.fipe_vehicle_manufacturer
(
    id integer NOT NULL DEFAULT nextval('fipe_vehicle_manufacturer_id_seq'::regclass),
    name character varying COLLATE pg_catalog."default",
    code character varying COLLATE pg_catalog."default",
    vehicle_type integer,
    sequence integer,
    create_uid integer,
    create_date timestamp without time zone,
    write_uid integer,
    write_date timestamp without time zone,
    CONSTRAINT fipe_vehicle_manufacturer_pkey PRIMARY KEY (id),
    CONSTRAINT fipe_vehicle_manufacturer_manufacturer_name_code_vehicle_type_u UNIQUE (name, code, vehicle_type)
);

-- DROP TABLE IF EXISTS public.fipe_vehicle_model;

CREATE TABLE IF NOT EXISTS public.fipe_vehicle_model
(
    id integer NOT NULL DEFAULT nextval('fipe_vehicle_model_id_seq'::regclass),
    name character varying COLLATE pg_catalog."default" NOT NULL,
    code character varying COLLATE pg_catalog."default" NOT NULL,
    manufacturer_id integer NOT NULL,
    create_uid integer,
    create_date timestamp without time zone,
    write_uid integer,
    write_date timestamp without time zone,
    CONSTRAINT fipe_vehicle_model_pkey PRIMARY KEY (id),
    CONSTRAINT fipe_vehicle_model_model_name_manufacturer_id_code_unique UNIQUE (name, manufacturer_id, code),
    CONSTRAINT fipe_vehicle_model_manufacturer_id_fkey FOREIGN KEY (manufacturer_id)
        REFERENCES public.fipe_vehicle_manufacturer (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE RESTRICT
);

-- DROP TABLE IF EXISTS public.fipe_vehicle_model_value;

CREATE TABLE IF NOT EXISTS public.fipe_vehicle_model_value
(
    id integer NOT NULL DEFAULT nextval('fipe_vehicle_model_value_id_seq'::regclass),
    name character varying COLLATE pg_catalog."default" NOT NULL,
    model_id integer,
    code character varying COLLATE pg_catalog."default",
    fipe_code character varying COLLATE pg_catalog."default" NOT NULL,
    manufacturer_id integer,
    manufacture_year character varying COLLATE pg_catalog."default",
    reference_month character varying COLLATE pg_catalog."default",
    reference_month_code character varying COLLATE pg_catalog."default",
    fipe_value double precision,
    fuel_type character varying COLLATE pg_catalog."default",
    vehicle_type integer,
    active boolean,
    message_main_attachment_id integer,
    create_uid integer,
    create_date timestamp without time zone,
    write_uid integer,
    write_date timestamp without time zone,
    CONSTRAINT fipe_vehicle_model_value_pkey PRIMARY KEY (id),
    CONSTRAINT fipe_vehicle_model_value_model_id_fkey FOREIGN KEY (model_id)
        REFERENCES public.fipe_vehicle_model (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE SET NULL,
    CONSTRAINT fipe_vehicle_model_manufacturer_id_fkey FOREIGN KEY (manufacturer_id)
        REFERENCES public.fipe_vehicle_manufacturer (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE SET NULL
);