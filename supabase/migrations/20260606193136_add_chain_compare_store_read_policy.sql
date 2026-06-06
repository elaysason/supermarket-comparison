DROP POLICY IF EXISTS chain_compare_stores_read_all
    ON public.chain_compare_stores;

CREATE POLICY chain_compare_stores_read_all
    ON public.chain_compare_stores
    FOR SELECT
    USING (true);
