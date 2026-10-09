DO $$
BEGIN
    IF to_regclass('public.tab_sj') IS NULL
       OR to_regclass('public.tab_sj_negativ') IS NULL THEN
        RETURN;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'tab_sj'
          AND column_name = 'excav_extent'
    ) THEN
        ALTER TABLE public.tab_sj
            ADD COLUMN excav_extent NUMERIC(3,0) NULL;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'tab_sj_negativ'
          AND column_name = 'excav_extent'
    ) THEN
        UPDATE public.tab_sj AS sj
        SET excav_extent = CASE lower(trim(neg.excav_extent::text))
            WHEN 'whole' THEN 100
            WHEN 'more_than_50' THEN 75
            WHEN 'around_50' THEN 50
            WHEN 'less_than_50' THEN 25
            WHEN 'unknown' THEN NULL
            WHEN '' THEN NULL
            ELSE CASE
                WHEN trim(neg.excav_extent::text) ~ '^(100|[0-9]{1,2})$'
                    THEN trim(neg.excav_extent::text)::NUMERIC(3,0)
                ELSE NULL
            END
        END
        FROM public.tab_sj_negativ AS neg
        WHERE neg.id_negativ = sj.id_sj
          AND sj.excav_extent IS NULL;

        ALTER TABLE public.tab_sj_negativ
            DROP COLUMN excav_extent;
    END IF;

    ALTER TABLE public.tab_sj
        DROP CONSTRAINT IF EXISTS tab_sj_excav_extent_chk;

    ALTER TABLE public.tab_sj
        ADD CONSTRAINT tab_sj_excav_extent_chk
        CHECK (excav_extent IS NULL OR (excav_extent >= 0 AND excav_extent <= 100));
END
$$;
