DO $$
BEGIN
    IF to_regclass('public.tab_finds') IS NOT NULL THEN
        ALTER TABLE public.tab_finds
            ALTER COLUMN count DROP NOT NULL;

        ALTER TABLE public.tab_finds
            DROP CONSTRAINT IF EXISTS tab_finds_count_check;

        ALTER TABLE public.tab_finds
            ADD CONSTRAINT tab_finds_count_check
            CHECK (count IS NULL OR count > 0);
    END IF;
END
$$;
