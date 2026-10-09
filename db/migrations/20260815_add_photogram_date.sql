BEGIN;

ALTER TABLE public.tab_photograms
    ADD COLUMN IF NOT EXISTS datum date;

-- Existing photograms have no recoverable capture date. Use the migration
-- date so the new required field can be enforced consistently.
UPDATE public.tab_photograms
SET datum = CURRENT_DATE
WHERE datum IS NULL;

ALTER TABLE public.tab_photograms
    ALTER COLUMN datum SET NOT NULL;

CREATE INDEX IF NOT EXISTS tab_photograms_datum_idx
    ON public.tab_photograms (datum);

COMMIT;
