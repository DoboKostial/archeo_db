DO $$
BEGIN
    IF to_regclass('public.tab_finds') IS NOT NULL THEN
        ALTER TABLE public.tab_finds
            ALTER COLUMN box DROP NOT NULL;

        ALTER TABLE public.tab_finds
            DROP CONSTRAINT IF EXISTS tab_finds_box_check;

        ALTER TABLE public.tab_finds
            ADD CONSTRAINT tab_finds_box_check
            CHECK (box IS NULL OR box > 0);
    END IF;
END
$$;
