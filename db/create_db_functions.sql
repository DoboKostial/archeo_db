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

-- this function requires the ID of cut and lists all SJs cut by this cut
CREATE OR REPLACE FUNCTION public.fnc_get_cut_and_related_sjs(choose_cut integer)
 RETURNS TABLE(id_cut integer, id_sj integer, docu_plan boolean, docu_vertical boolean)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            tc.id_cut,
            tsj.id_sj,
            tsj.docu_plan,
	    tsj.docu_vertical
        FROM
            public.tab_cut tc
        INNER JOIN
            public.tabaid_sj_cut tasc ON tc.id_cut = tasc.ref_cut
        INNER JOIN
            public.tab_sj tsj ON tasc.ref_sj = tsj.id_sj
	WHERE tc.id_cut = choose_cut
    );
END;
$function$
;

-- this function takes ID of SJ and list all cuts cutting this SJ 
CREATE OR REPLACE FUNCTION public.fnc_get_sj_and_related_cuts(choose_sj integer)
 RETURNS TABLE(sj_id integer, id_cut integer, description character varying)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN QUERY (
        SELECT
            sj.id_sj,
            tc.id_cut,
            tc.description
        FROM
            public.tab_sj sj
        INNER JOIN
            public.tabaid_sj_cut tasc ON sj.id_sj = tasc.ref_sj
        INNER JOIN
            public.tab_cut tc ON tasc.ref_cut = tc.id_cut
	WHERE sj.id_sj = choose_sj
    );
END;
$function$
;

-- this function takes SJ id and returns list of all related fotos
CREATE OR REPLACE FUNCTION public.fnc_get_sj_and_related_foto(choose_sj integer)
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
	WHERE sj.id_sj = choose_sj
    );
END;
$function$
;

-- this function requires SJ id and returns list of referenced fotograms
CREATE OR REPLACE FUNCTION public.fnc_get_sj_and_related_fotogram(strat_j integer)
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
	WHERE sj.id_sj = strat_j
    );
END;
$function$
;
