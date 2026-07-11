INSERT INTO public.stores (chain_code, store_code, store_name)
VALUES ('7290055700007', '471', 'קרפור אונליין   כפר סבא @ קרפור (5304)')
ON CONFLICT (chain_code, store_code) DO UPDATE SET
    store_name = EXCLUDED.store_name;

INSERT INTO public.chain_compare_stores (chain_code, store_code)
VALUES ('7290055700007', '471')
ON CONFLICT (chain_code) DO UPDATE SET
    store_code = EXCLUDED.store_code,
    updated_at = now();
