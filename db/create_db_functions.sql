-- this fnc loops over all SJs and returns related fotos
CREATE OR REPLACE FUNCTION public.fnc_get_all_sjs_and_related_foto()
 RETURNS TABLE(sj_id integer, foto_id character varying, foto_typ character varying, foto_datum date)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            sj.id_sj,
            tf.id_foto,
            tf.foto_typ,
            tf.datum AS foto_datum
        FROM
            public.tab_sj sj
        INNER JOIN
            public.tabaid_foto_sj tafs ON sj.id_sj = tafs.ref_sj
        INNER JOIN
            public.tab_foto tf ON tafs.ref_foto = tf.id_foto
    );
END;
$function$
;


-- 
-- this fnc loops over all SJs and returns related fotograms
CREATE OR REPLACE FUNCTION public.fnc_get_all_sjs_and_related_fotogram()
 RETURNS TABLE(sj_id integer, id_fotogram character varying, fotogram_typ character varying)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            sj.id_sj,
            tf.id_fotogram,
            tf.fotogram_typ
        FROM
            public.tab_sj sj
        INNER JOIN
            public.tabaid_fotogram_sj tafs ON sj.id_sj = tafs.ref_sj
        INNER JOIN
            public.tab_fotogram tf ON tafs.ref_fotogram = tf.id_fotogram
    );
END;
$function$
;

--
-- this fnc loops over all SJs and returns related sketches
CREATE OR REPLACE FUNCTION public.fnc_get_all_sjs_and_related_sketch()
 RETURNS TABLE(sj_id integer, id_sketch character varying, sketch_typ character varying, datum date)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            sj.id_sj,
            ts.id_sketch,
            ts.sketch_typ,
            ts.datum AS sketch_datum
        FROM
            public.tab_sj sj
        INNER JOIN
            public.tabaid_sj_sketch tass ON sj.id_sj = tass.ref_sj
        INNER JOIN
            public.tab_sketch ts ON tass.ref_sketch = ts.id_sketch
    );
END;
$function$
;

