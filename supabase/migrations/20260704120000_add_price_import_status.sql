CREATE TABLE IF NOT EXISTS public.price_import_status (
    chain_code character varying NOT NULL,
    store_code character varying NOT NULL,
    price_file_type text NOT NULL,
    source_file_name text NOT NULL,
    source_file_date timestamp with time zone NOT NULL,
    last_success_at timestamp with time zone NOT NULL DEFAULT now(),
    items_imported integer NOT NULL DEFAULT 0 CHECK (items_imported >= 0),
    CONSTRAINT price_import_status_pkey PRIMARY KEY (chain_code, store_code),
    CONSTRAINT price_import_status_store_fkey FOREIGN KEY (chain_code, store_code)
        REFERENCES public.stores(chain_code, store_code)
);

ALTER TABLE public.price_import_status ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS price_import_status_read_all
    ON public.price_import_status;

CREATE POLICY price_import_status_read_all
    ON public.price_import_status
    FOR SELECT
    USING (true);
