import duckdb

con = duckdb.connect("/home/claude/da/utla_shift.duckdb")
con.sql("set threads=2")
T = 0.5
TOL = 0.005

con.sql("""
create or replace table owners2 as
with k as (
    select yr, orgnr, otype, owner_name, landkode, owner_form, n,
           case when otype = 'no_corp' or (length(owner_id) = 9 and otype = 'foreign' and owner_form in ('NUF','UTLA')) then owner_id
                when length(owner_id) = 4 then 'P|' || split_part(trim(upper(owner_name)), ' ', 1) || '|' || owner_id
                when length(owner_id) = 9 then owner_id
                when nullif(trim(owner_id), '') is not null then 'L|' || trim(owner_id)
                else 'F|' || regexp_replace(upper(owner_name), '[^A-Z0-9ÆØÅÄÖÜ]', '', 'g') end okey
    from owner_rows)
select yr, orgnr, okey, any_value(otype) otype, any_value(owner_name) owner_name,
       max(landkode) landkode, any_value(owner_form) owner_form, sum(n) n,
       bool_or(otype = 'foreign') any_foreign_row
from k group by yr, orgnr, okey
""")

con.sql("""
create or replace table owners2_pct as
select o.*, o.n / t.tot pct from owners2 o join (select yr, orgnr, sum(n) tot from owners2 group by 1, 2) t using (yr, orgnr)
""")

con.sql(f"""
create or replace table fats2_c as
with r as (select *, row_number() over (partition by yr, orgnr order by n desc, okey) rk from owners2_pct),
g as (select yr, orgnr,
             max(pct) filter (where rk = 1) top_pct,
             any_value(okey) filter (where rk = 1) top_key,
             any_value(otype) filter (where rk = 1) top_type,
             coalesce(sum(pct) filter (where otype = 'foreign'), 0) foreign_sum,
             coalesce(sum(pct) filter (where otype = 'no_person'), 0) person_sum,
             coalesce(sum(pct) filter (where otype = 'no_corp'), 0) corp_sum
      from r group by 1, 2)
select g.*,
       case when fo.legal_form = 'ASA' or v.orgnr is not null then 'listed'
            when top_pct > {T} and top_type = 'no_corp' then 'walk'
            when top_pct > {T} and top_type = 'foreign' then 'foreign'
            when top_pct > {T} and top_type = 'no_person' then 'synthetic_person'
            when foreign_sum > {T} then 'foreign'
            when person_sum > {T} then 'synthetic_person'
            when corp_sum > {T} then 'jv_corporates'
            else 'dispersed' end node
from g left join forms fo using (orgnr) left join vps v using (orgnr)
""")

con.sql("""
create or replace table fats2_u as
with recursive walk(yr, orgnr, cur, depth, path) as (
    select yr, orgnr, orgnr, 0, [orgnr] from fats2_c
    union all
    select w.yr, w.orgnr, c.top_key, w.depth + 1, list_append(w.path, c.top_key)
    from walk w join fats2_c c on c.yr = w.yr and c.orgnr = w.cur
    where c.node = 'walk' and w.depth < 10 and not list_contains(w.path, c.top_key)
),
ch as (select * from walk qualify row_number() over (partition by yr, orgnr order by depth desc) = 1)
select ch.yr, ch.orgnr, ch.depth, ch.cur group_top, d.top_key direct_top_key, t.top_key top_top_key,
       coalesce(t.node, case when fo.legal_form = 'ASA' then 'listed' else 'external_not_in_register' end) top_kind
from ch join fats2_c d on d.yr = ch.yr and d.orgnr = ch.orgnr
left join fats2_c t on t.yr = ch.yr and t.orgnr = ch.cur
left join forms fo on fo.orgnr = ch.cur
""")

con.sql(f"""
create or replace table fats2_tr as
with cur as (select u.*, e.has_emp, e.ans_known from fats2_u u left join emp24 e using (orgnr)),
tr as (
    select c.yr, c.orgnr, p.top_kind prev_kind, c.top_kind curr_kind, c.depth, c.group_top, p.group_top prev_group_top,
           c.has_emp, c.ans_known,
           case when p.direct_top_key is distinct from c.direct_top_key then 'sold_here'
                when p.group_top is distinct from c.group_top then 'inherited_from_above'
                when p.top_top_key is distinct from c.top_top_key then 'sold_at_top'
                else 'threshold_drift' end locus
    from cur c join cur p on p.orgnr = c.orgnr and p.yr = c.yr - 1
    where c.yr in (2024, 2025) and p.top_kind <> c.top_kind),
topf as (
    select yr, orgnr, okey, otype, owner_name, landkode, pct
    from owners2_pct where otype = 'foreign'
    qualify row_number() over (partition by yr, orgnr order by n desc, okey) = 1),
node_eval as (
    select tr.*, tf.okey f_key, tf.owner_name f_name, tf.landkode f_land, tf.pct f_pct,
           left(tf.okey, 2) = 'P|' f_is_person,
           mv.prev_pct, mv.prev_land, mv.prev_key,
           po.pct same_key_prev_pct, po.otype same_key_prev_otype
    from tr
    left join topf tf on tf.yr = tr.yr and tf.orgnr = tr.group_top
    left join owners2_pct po on po.yr = tr.yr - 1 and po.orgnr = tr.group_top and po.okey = tf.okey
    left join lateral (
        select p.pct prev_pct, p.landkode prev_land, p.okey prev_key
        from owners2_pct p
        where p.yr = tr.yr - 1 and p.orgnr = tr.group_top and p.otype = 'no_person'
          and split_part(trim(upper(p.owner_name)), ' ', 1) = split_part(trim(upper(tf.owner_name)), ' ', 1)
          and abs(p.pct - tf.pct) <= {TOL}
          and (left(tf.okey, 2) <> 'P|' or split_part(p.okey, '|', 3) = split_part(tf.okey, '|', 3))
        order by abs(p.pct - tf.pct) limit 1) mv on true)
select *,
       case when curr_kind <> 'foreign' then null
            when f_key is null then 'unresolved'
            when prev_key is not null then 'move'
            when same_key_prev_pct is not null and same_key_prev_otype = 'foreign' then 'already_foreign_owner'
            when same_key_prev_pct is not null then 'stake_change'
            else 'sale' end sale_or_move
from node_eval
""")

q = lambda s: print(con.sql(s).df().to_string(index=False), "\n")

q("""select 'old_key' k, yr, count(*) into_foreign, count(*) filter (where locus='threshold_drift') drift from fats_tr where curr_kind='foreign' group by 1,2
union all select 'first_name_dob', yr, count(*), count(*) filter (where locus='threshold_drift') from fats2_tr where curr_kind='foreign' group by 1,2 order by 2,1""")

q("""select yr, sale_or_move, case when f_is_person then 'person' else 'corporate' end owner_kind,
       count(*) companies, count(*) filter (where has_emp) with_emp, sum(ans_known) ans5, count(distinct group_top) tops
from fats2_tr where curr_kind = 'foreign' group by all order by 1, 4 desc""")

q("""select yr, sale_or_move, locus, count(*) n from fats2_tr where curr_kind = 'foreign' group by all order by 1, 2, 4 desc""")

q("""select yr, orgnr, group_top, f_name, prev_land, f_land, round(prev_pct,3) prev_pct, round(f_pct,3) pct, n_emp.ans_known
from fats2_tr n_emp where sale_or_move = 'move' and has_emp order by ans_known desc nulls last limit 12""")

q("""select yr, f_land, count(*) companies, count(distinct group_top) tops, count(*) filter (where has_emp) with_emp
from fats2_tr where sale_or_move = 'move' group by all order by 1, 3 desc limit 12""")

con.sql("copy fats2_tr to '/home/claude/da/ubo_sale_vs_move.parquet' (format parquet)")
