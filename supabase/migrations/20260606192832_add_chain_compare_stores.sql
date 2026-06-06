CREATE TABLE IF NOT EXISTS public.chain_compare_stores (
    chain_code character varying NOT NULL,
    store_code character varying NOT NULL,
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT chain_compare_stores_pkey PRIMARY KEY (chain_code),
    CONSTRAINT chain_compare_stores_chain_fkey FOREIGN KEY (chain_code)
        REFERENCES public.chains(chain_code),
    CONSTRAINT chain_compare_stores_store_fkey FOREIGN KEY (chain_code, store_code)
        REFERENCES public.stores(chain_code, store_code)
);

ALTER TABLE public.chain_compare_stores ENABLE ROW LEVEL SECURITY;

INSERT INTO public.chains (chain_code, name)
VALUES
    ('7290027600007', 'Shufersal'),
    ('7290055700007', 'Carrefour'),
    ('7290058140886', 'Rami Levi'),
    ('7290700100008', 'Hazi Hinam'),
    ('7290803800003', 'Yohananof')
ON CONFLICT (chain_code) DO NOTHING;

INSERT INTO public.stores (chain_code, store_code, store_name)
VALUES
    ('7290027600007', '413', 'Shufersal Online'),
    ('7290055700007', '5304', 'Carrefour Online'),
    ('7290058140886', '039', 'Rami Levi Online'),
    ('7290700100008', '103', 'Hazi Hinam Online'),
    ('7290803800003', '150', 'Yohananof Online')
ON CONFLICT (chain_code, store_code) DO NOTHING;

INSERT INTO public.chain_compare_stores (chain_code, store_code)
VALUES
    ('7290027600007', '413'),
    ('7290055700007', '5304'),
    ('7290058140886', '039'),
    ('7290700100008', '103'),
    ('7290803800003', '150')
ON CONFLICT (chain_code) DO UPDATE SET
    store_code = EXCLUDED.store_code,
    updated_at = now();
