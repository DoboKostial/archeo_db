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

-- this function use SJ is as an argument and prints all sketches associated with
CREATE OR REPLACE FUNCTION public.fnc_get_sj_and_related_sketch(strat_j integer)
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
	WHERE sj.id_sj = strat_j
    );
END;
$function$
;


-- similar as 1st function but this uses loop
CREATE OR REPLACE FUNCTION public.fnc_print_all_sjs_and_associated_photos()
 RETURNS void
 LANGUAGE plpgsql
AS $function$
DECLARE
    sj_record record;
    photo_info text;
BEGIN
    FOR sj_record IN (
        SELECT id_sj
        FROM tab_sj
    ) LOOP
        FOR photo_info IN (
            SELECT tf.id_foto || ' (' || tf.foto_typ || ')' AS photo_description
            FROM tabaid_foto_sj tafs
            JOIN tab_foto tf ON tafs.ref_foto = tf.id_foto
            WHERE tafs.ref_sj = sj_record.id_sj
        ) LOOP
            RAISE NOTICE 'For SJ %, Associated Photo: %', sj_record.id_sj, photo_info;
        END LOOP;
    END LOOP;
END;
$function$
;

-- this function lists all objects/features and prints associated sjs
CREATE OR REPLACE FUNCTION public.fnc_show_all_objects_sjs()
 RETURNS TABLE(objekt integer, typ_objektu character varying, strat_j integer, interpretace character varying)
 LANGUAGE plpgsql
AS $function$
BEGIN
        RETURN QUERY SELECT
        id_object, object_typ, id_sj, interpretation
        FROM tab_object INNER JOIN tab_sj ON id_object = ref_object
        ORDER BY id_object ASC;
END;
$function$
;

-- this function takes foto ID and prints all fotograms associated
CREATE OR REPLACE FUNCTION public.fnc_show_fotograms_by_photo(fotopattern character varying)
 RETURNS TABLE(id_fotogram character varying, fotogram_typ character varying, ref_sketch character varying)
 LANGUAGE plpgsql
AS $function$
	BEGIN
		RETURN QUERY
		SELECT fg.id_fotogram, fg.fotogram_typ, fg.ref_sketch
		FROM tab_fotogram fg
		INNER JOIN tabaid_fotogram_foto tff ON fg.id_fotogram = tff.ref_fotogram
		INNER JOIN tab_foto fo ON tff.ref_foto = fo.id_foto
		WHERE fo.id_foto ILIKE fotopattern;

	END;
   $function$
;

-- this func takes fotogram ID and lists all fotos associated
CREATE OR REPLACE FUNCTION public.fnc_show_fotos_by_fotogram(fotogramm character varying)
 RETURNS TABLE(id_foto character varying, foto_typ character varying, notes character varying)
 LANGUAGE plpgsql
AS $function$
	BEGIN
		RETURN QUERY
		SELECT fo.id_foto, fo.typ, fo.notes
		FROM tab_foto fo
		INNER JOIN tabaid_fotogram_foto tff ON fo.id_foto = tff.ref_foto
		INNER JOIN tab_fotogram tf ON tff.ref_fotogram = tf.id_fotogram
		WHERE tf.id_fotogram ILIKE fotogramm;

	END;
   $function$
;

-- this function takes object/feature as argument and prints all SJs it consists of
CREATE OR REPLACE FUNCTION public.fnc_show_sj_by_object(objekt integer)
 RETURNS TABLE(strat_j_id integer, interpretace character varying)
 LANGUAGE plpgsql
AS $function$
BEGIN
        RETURN QUERY SELECT
                id_sj,
                interpretation
        FROM tab_object
        INNER JOIN tab_sj on id_object = ref_object
        WHERE id_object = objekt;
END;
$function$
;

