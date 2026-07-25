UPDATE public.shipping_costs
SET fee = 35.90,
    notes = 'משלוח עד הבית ₪35.90',
    updated_at = now()
WHERE chain_code = '7290027600007'
  AND option_type = 'delivery';
