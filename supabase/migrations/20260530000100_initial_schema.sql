-- Baseline schema captured from the existing Supabase database.
-- Run this against fresh/staging databases. For the existing production DB,
-- baseline migration history instead of running duplicate CREATE TABLE statements.

CREATE TABLE public.chains (
    chain_code character varying NOT NULL,
    name character varying NOT NULL,
    is_active boolean DEFAULT true,
    CONSTRAINT chains_pkey PRIMARY KEY (chain_code)
);

CREATE TABLE public.products (
    barcode character varying NOT NULL,
    product_name character varying,
    image_url text,
    unit_name character varying,
    total_quantity numeric CHECK (total_quantity IS NULL OR total_quantity >= 0),
    manufacturer_name character varying,
    CONSTRAINT products_pkey PRIMARY KEY (barcode)
);

CREATE TABLE public.stores (
    chain_code character varying NOT NULL,
    store_code character varying NOT NULL DEFAULT 'ONLINE'::character varying,
    store_name character varying,
    CONSTRAINT stores_pkey PRIMARY KEY (chain_code, store_code),
    CONSTRAINT stores_chain_code_fkey FOREIGN KEY (chain_code)
        REFERENCES public.chains(chain_code)
);

CREATE TABLE public.prices (
    barcode character varying NOT NULL,
    price numeric NOT NULL CHECK (price >= 0),
    price_per_unit numeric CHECK (price_per_unit IS NULL OR price_per_unit >= 0),
    update_date timestamp with time zone NOT NULL,
    chain_code character varying NOT NULL,
    store_code character varying NOT NULL,
    CONSTRAINT prices_pkey PRIMARY KEY (chain_code, store_code, barcode),
    CONSTRAINT prices_store_fkey FOREIGN KEY (chain_code, store_code)
        REFERENCES public.stores(chain_code, store_code),
    CONSTRAINT prices_barcode_fkey FOREIGN KEY (barcode)
        REFERENCES public.products(barcode)
);

CREATE TABLE public.shipping_costs (
    chain_code text NOT NULL,
    option_type text NOT NULL CHECK (option_type = ANY (ARRAY['delivery'::text, 'pickup'::text])),
    fee numeric NOT NULL CHECK (fee >= 0),
    free_above numeric CHECK (free_above IS NULL OR free_above >= 0),
    min_order numeric CHECK (min_order IS NULL OR min_order >= 0),
    notes text,
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT shipping_costs_pkey PRIMARY KEY (chain_code, option_type),
    CONSTRAINT shipping_costs_chain_code_fkey FOREIGN KEY (chain_code)
        REFERENCES public.chains(chain_code)
);

ALTER TABLE public.chains ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stores ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.prices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shipping_costs ENABLE ROW LEVEL SECURITY;

CREATE INDEX prices_barcode_chain_price_idx
    ON public.prices (barcode, chain_code, price);

CREATE INDEX prices_chain_barcode_price_idx
    ON public.prices (chain_code, barcode, price);
