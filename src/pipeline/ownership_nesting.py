import duckdb
from google.oauth2 import service_account
import google.auth.transport.requests as tr

cred = service_account.Credentials.from_service_account_file(
    "/mnt/project/sondreskarsten-d7d14-8486be2d085b.json",
    scopes=["https://www.googleapis.com/auth/devstorage.read_only"])
cred.refresh(tr.Request())

con = duckdb.connect("/home/claude/da/utla_shift.duckdb")
con.sql("set threads=2")
con.sql("install httpfs; load httpfs")
con.sql(f"create or replace secret g (type gcs, bearer_token '{cred.token}')")
con.sql("attach '/home/claude/da/foreign_shift.duckdb' as f (read_only)")

CTRL = 0.5

con.sql("""
create or replace table vps as
select distinct cast(orgnr as varchar) orgnr from read_parquet('gs://sondre_brreg_data/aksjeeierbok/v2/vps_orgnrs_ever.parquet')
""")

con.sql("""
create or replace table utla_names as
select org_nr utla_orgnr, name utla_name, foreign_law_country_code utla_country,
       regexp_replace(upper(name), '[^A-Z0-9ÆØÅÄÖÜ]', '', 'g') name_key
from f.pre_enh where legal_form = 'UTLA'
""")

con.sql("""
create or replace table owner_rows as
select a.yr, a.orgnr, a.owner_id, a.owner_name, a.landkode, a.n, a.owner_form,
       case when a.f_nufutla or a.f_land then 'foreign'
            when length(a.owner_id) = 9 then 'no_corp'
            when length(a.owner_id) = 4 then 'no_person'
            else 'no_other' end otype,
       case when length(a.owner_id) = 9 then a.owner_id
            when length(a.owner_id) = 4 then 'P|' || a.owner_name || '|' || a.owner_id
            else 'F|' || coalesce(nullif(a.owner_id,''), '') || '|' || regexp_replace(upper(a.owner_name), '[^A-Z0-9ÆØÅÄÖÜ]', '', 'g') end okey
from aksje_c a
""")

con.sql("""
create or replace table owners as
select yr, orgnr, okey, any_value(otype) otype, any_value(owner_name) owner_name, any_value(landkode) landkode,
       any_value(owner_form) owner_form, sum(n) n
from owner_rows group by yr, orgnr, okey
""")

con.sql("""
create or replace table comp as
with t as (select yr, orgnr, sum(n) tot from owners group by 1, 2),
r as (select o.*, o.n / t.tot pct, row_number() over (partition by o.yr, o.orgnr order by o.n desc, o.okey) rk from owners o join t using (yr, orgnr))
select r.yr, r.orgnr,
       max(pct) filter (where rk = 1) top_pct,
       any_value(okey) filter (where rk = 1) top_key,
       any_value(otype) filter (where rk = 1) top_type,
       any_value(owner_name) filter (where rk = 1) top_name,
       any_value(landkode) filter (where rk = 1) top_land,
       coalesce(sum(pct) filter (where otype = 'foreign'), 0) foreign_sum,
       coalesce(sum(pct) filter (where otype = 'no_person'), 0) person_sum
from r group by 1, 2
""")

con.sql(f"""
create or replace table comp_c as
select c.*, fo.legal_form,
       case when fo.legal_form = 'ASA' or v.orgnr is not null then 'excluded_asa_vps'
            when c.top_type = 'foreign' and c.top_pct > {CTRL} then 'foreign_single'
            when c.foreign_sum > {CTRL} then 'foreign_sum'
            when c.top_type = 'no_corp' and c.top_pct > {CTRL} then 'no_corp_parent'
            when c.top_type = 'no_person' and c.top_pct > {CTRL} then 'no_person_top'
            when c.top_pct > {CTRL} then 'no_other_top'
            else 'dispersed' end direct_status,
       case when c.top_pct > 0.9 then 'gt_90' when c.top_pct >= 2/3 then 'ge_2_3' when c.top_pct > 0.5 then 'gt_50'
            when c.top_pct > 1/3 then 'gt_1_3' else 'le_1_3' end top_tier
from comp c
left join forms fo on fo.orgnr = c.orgnr
left join vps v on v.orgnr = c.orgnr
""")

con.sql("""
create or replace table chain as
with recursive walk(yr, orgnr, cur, depth, path) as (
    select yr, orgnr, orgnr, 0, [orgnr] from comp_c where direct_status <> 'excluded_asa_vps'
    union all
    select w.yr, w.orgnr, c.top_key, w.depth + 1, list_append(w.path, c.top_key)
    from walk w join comp_c c on c.yr = w.yr and c.orgnr = w.cur
    where c.direct_status = 'no_corp_parent' and w.depth < 10 and not list_contains(w.path, c.top_key)
)
select * from walk qualify row_number() over (partition by yr, orgnr order by depth desc) = 1
""")

con.sql("""
create or replace table ultimate as
select ch.yr, ch.orgnr, ch.depth, ch.cur top_orgnr,
       coalesce(t.direct_status, case when fo.legal_form in ('ASA') then 'parent_asa' else 'parent_not_in_aksjebok' end) top_status_raw,
       t.top_name top_owner_name, t.top_land top_owner_land, t.top_pct top_owner_pct, t.foreign_sum top_foreign_sum,
       d.direct_status, d.top_tier, d.top_pct direct_top_pct
from chain ch
join comp_c d on d.yr = ch.yr and d.orgnr = ch.orgnr
left join comp_c t on t.yr = ch.yr and t.orgnr = ch.cur
left join forms fo on fo.orgnr = ch.cur
""")

con.sql("""
create or replace table ultimate_c as
select u.*,
       case when top_status_raw in ('foreign_single','foreign_sum') then 'foreign'
            when top_status_raw = 'dispersed' and depth = 0 then 'dispersed_skip'
            when top_status_raw = 'dispersed' then 'domestic_dispersed_top'
            when top_status_raw in ('excluded_asa_vps','parent_asa') then 'domestic_listed_top'
            when top_status_raw = 'no_corp_parent' then 'chain_cut'
            else 'domestic' end ultimate
from ultimate u
""")

con.sql("""
create or replace table top_foreign_owner as
select c.yr, c.orgnr, o.owner_name foreign_owner_name, o.landkode foreign_owner_land, o.n / t.tot foreign_owner_pct,
       coalesce(uo.utla_orgnr, un.utla_orgnr) utla_orgnr, coalesce(uo.utla_country, un.utla_country) utla_country
from comp_c c
join owners o on o.yr = c.yr and o.orgnr = c.orgnr and o.otype = 'foreign'
join (select yr, orgnr, sum(n) tot from owners group by 1, 2) t on t.yr = c.yr and t.orgnr = c.orgnr
left join utla_names uo on uo.utla_orgnr = o.okey
left join utla_names un on un.name_key = regexp_replace(upper(o.owner_name), '[^A-Z0-9ÆØÅÄÖÜ]', '', 'g')
where c.direct_status in ('foreign_single','foreign_sum')
qualify row_number() over (partition by c.yr, c.orgnr order by o.n desc) = 1
""")

con.sql("""
create or replace table result as
select u.*, tfo.foreign_owner_name, tfo.foreign_owner_land, tfo.foreign_owner_pct, tfo.utla_orgnr, tfo.utla_country,
       e.has_emp, e.n_units_emp, e.ans_known
from ultimate_c u
left join top_foreign_owner tfo on tfo.yr = u.yr and tfo.orgnr = u.top_orgnr
left join emp24 e on e.orgnr = u.orgnr
""")

con.sql("""
create or replace table transitions as
select c.yr, c.orgnr, p.ultimate prev_ultimate, c.ultimate curr_ultimate, p.top_orgnr prev_top, c.top_orgnr curr_top,
       c.depth, c.foreign_owner_name, c.foreign_owner_land, c.utla_orgnr, c.has_emp, c.n_units_emp, c.ans_known
from result c join result p on p.orgnr = c.orgnr and p.yr = c.yr - 1
where c.yr in (2024, 2025) and p.ultimate <> c.ultimate
""")

q = lambda s: print(con.sql(s).df().to_string(index=False), "\n")

q("select yr, direct_status, count(*) n from comp_c group by all order by 1, 3 desc")
q("""select yr, ultimate, count(*) companies, count(*) filter (where has_emp) with_emp, sum(ans_known) ans_5plus,
       count(*) filter (where depth > 0) via_chain, max(depth) max_depth
from result group by all order by 1, 3 desc""")
q("""select yr, prev_ultimate, curr_ultimate, count(*) companies, count(*) filter (where has_emp) with_emp,
       sum(ans_known) ans_5plus, count(*) filter (where depth > 0) via_chain
from transitions where 'foreign' in (prev_ultimate, curr_ultimate) group by all order by 1, 4 desc""")
q("""select yr, count(*) foreign_tops, count(utla_orgnr) resolved_to_utla, count(*) filter (where foreign_owner_land is not null) with_land
from (select distinct yr, top_orgnr, utla_orgnr, foreign_owner_land from result where ultimate = 'foreign') group by 1 order by 1""")
q("""select t.yr, t.orgnr, t.depth, t.curr_top, t.foreign_owner_name, t.foreign_owner_land, t.utla_orgnr, t.n_units_emp, t.ans_known
from transitions t where prev_ultimate <> 'foreign' and curr_ultimate = 'foreign' and has_emp order by ans_known desc nulls last limit 20""")

for t in ["result", "transitions"]:
    con.sql(f"copy {t} to '/home/claude/da/ownership_{t}.parquet' (format parquet)")
