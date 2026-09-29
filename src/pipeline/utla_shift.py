import duckdb
from google.oauth2 import service_account
import google.auth.transport.requests as tr

cred = service_account.Credentials.from_service_account_file(
    "/mnt/project/sondreskarsten-d7d14-8486be2d085b.json",
    scopes=["https://www.googleapis.com/auth/devstorage.read_only"])
cred.refresh(tr.Request())

con = duckdb.connect("/home/claude/da/utla_shift.duckdb")
con.sql("install httpfs; load httpfs")
con.sql(f"create or replace secret g (type gcs, bearer_token '{cred.token}')")
con.sql("attach '/home/claude/da/scratch.duckdb' as s (read_only)")
con.sql("attach '/home/claude/da/foreign_shift.duckdb' as f (read_only)")

con.sql("""
create or replace table forms as
select org_nr orgnr, legal_form from f.pre_enh
union by name
select orgnr, orgform legal_form from s.enh2 where orgnr not in (select org_nr from f.pre_enh)
""")

files = {2023: "/home/claude/da/aksje_2023.csv", 2024: "/home/claude/da/aksje_2024.csv", 2025: "/tmp/claude-0/a2025.csv"}
con.sql("create or replace table aksje (yr int, orgnr varchar, owner_id varchar, owner_name varchar, landkode varchar, n double)")
for y, p in files.items():
    con.sql(f"""
    insert into aksje
    select {y}, Orgnr, trim("Fødselsår/orgnr"), "Navn aksjonær", upper(trim(Landkode)), try_cast("Antall aksjer" as double)
    from read_csv('{p}', delim=';', header=true, all_varchar=true)
    """)

con.sql("""
create or replace table aksje_c as
select a.*, fo.legal_form owner_form,
       coalesce(a.landkode,'') not in ('NO','NOR','') f_land,
       coalesce(fo.legal_form in ('NUF','UTLA'), false) f_nufutla
from aksje a left join forms fo on fo.orgnr = a.owner_id
""")

con.sql("""
create or replace table own as
select yr, orgnr, sum(n) sh,
       coalesce(sum(n) filter (where f_land or f_nufutla), 0) / sum(n) fshare,
       coalesce(sum(n) filter (where f_land), 0) / sum(n) fshare_land,
       coalesce(sum(n) filter (where f_nufutla and not f_land), 0) / sum(n) fshare_nufutla,
       coalesce(sum(n) filter (where f_nufutla and owner_form='UTLA'), 0) / sum(n) fshare_utla
from aksje_c group by all having sum(n) > 0
""")

con.sql("""
create or replace table shift as
select c.orgnr, c.yr,
       p.fshare prev_fshare, c.fshare curr_fshare,
       c.fshare_land, c.fshare_nufutla, c.fshare_utla,
       p.fshare < 0.5 and c.fshare >= 0.5 became_majority,
       p.fshare = 0 and c.fshare > 0 became_any,
       case when c.fshare_utla >= 0.5 then 'UTLA_owner'
            when c.fshare_nufutla >= 0.5 then 'NUF_or_UTLA_owner'
            when c.fshare_land >= 0.5 then 'foreign_landkode'
            else 'mixed' end channel
from own c join own p on p.orgnr = c.orgnr and p.yr = c.yr - 1
where c.yr in (2024, 2025)
""")

con.sql("""
create or replace table und24 as
select organisasjonsnummer und, overordnetEnhet parent, harRegistrertAntallAnsatte = 'true' har, try_cast(antallAnsatte as int) ans
from read_csv('/home/claude/da/und_2024-07-01.csv.gz', all_varchar=true, header=true)
""")
con.sql("""
create or replace table emp24 as
select parent orgnr, count(*) filter (where har) n_units_emp, sum(ans) ans_known, bool_or(har) has_emp
from und24 group by 1
""")

con.sql("""
create or replace table reparent as
select u.und, u.parent pre_parent, p.overordnet_enhet post_parent, fp.legal_form post_form, fo.legal_form pre_form, u.har, u.ans
from und24 u
join f.pre_und p on p.organisasjonsnummer = u.und
left join forms fp on fp.orgnr = p.overordnet_enhet
left join forms fo on fo.orgnr = u.parent
where u.parent <> p.overordnet_enhet
""")

q = lambda s: print(con.sql(s).df().to_string(index=False), "\n")

q("select yr, count(*) companies, round(avg((fshare>0)::int)*100,2) pct_any_foreign, round(avg((fshare>=0.5)::int)*100,2) pct_majority_foreign, round(avg((fshare_utla>0)::int)*100,3) pct_any_utla from own group by 1 order by 1")

q("""select s.yr, s.channel,
       count(*) filter (where became_majority) became_majority,
       count(*) filter (where became_majority and e.has_emp) became_majority_with_emp,
       sum(e.ans_known) filter (where became_majority) ans_known_5plus,
       count(*) filter (where became_any) became_any_foreign
from shift s left join emp24 e using (orgnr) group by all order by 1, 2""")

q("""select s.yr, count(*) filter (where became_majority) maj, count(*) filter (where became_majority and e.has_emp) maj_emp,
       sum(e.n_units_emp) filter (where became_majority) units_emp, sum(e.ans_known) filter (where became_majority) ans_5plus
from shift s left join emp24 e using (orgnr) group by 1 order by 1""")

q("""select count(*) reparented_units, count(*) filter (where har) with_emp,
       count(*) filter (where post_form in ('NUF','UTLA') and coalesce(pre_form,'') not in ('NUF','UTLA')) to_nuf_utla,
       count(*) filter (where post_form in ('NUF','UTLA') and coalesce(pre_form,'') not in ('NUF','UTLA') and har) to_nuf_utla_emp,
       sum(ans) filter (where post_form in ('NUF','UTLA') and coalesce(pre_form,'') not in ('NUF','UTLA')) to_nuf_utla_ans_5plus
from reparent""")

q("""select und, pre_parent, pre_form, post_parent, post_form, har, ans from reparent
where post_form in ('NUF','UTLA') and coalesce(pre_form,'') not in ('NUF','UTLA') order by ans desc nulls last limit 20""")

for yr in (2024, 2025):
    q(f"""with v as (select orgnr, share_foreign from read_parquet('gs://sondre_brreg_data/aksjeeierbok/v2/panel/{yr}.parquet'))
    select {yr} yr, count(*) joined,
           round(corr(v.share_foreign, o.fshare_land),4) corr_vs_landkode, round(corr(v.share_foreign, o.fshare),4) corr_vs_incl_nufutla,
           count(*) filter (where abs(v.share_foreign - o.fshare_land) < 1e-4) eq_landkode,
           count(*) filter (where abs(v.share_foreign - o.fshare) < 1e-4) eq_incl_nufutla,
           count(*) filter (where o.fshare >= 0.5 and v.share_foreign < 0.5) majority_missed_by_v2
    from v join own o on o.orgnr = v.orgnr and o.yr = {yr}""")

q("""select t.income_year, t.threshold_label, t.crossing_direction, count(*) n
from read_parquet(['gs://sondre_brreg_data/aksjeeierbok/v2/thresholds/2024.parquet','gs://sondre_brreg_data/aksjeeierbok/v2/thresholds/2025.parquet']) t
join (select distinct yr, orgnr, owner_id from aksje_c where f_nufutla and not f_land) a
  on a.orgnr = t.orgnr and a.owner_id = t.fid and a.yr = t.income_year
where t.threshold_label = 't_0500' group by all order by all""")

for t in ["shift", "reparent", "emp24"]:
    con.sql(f"copy {t} to '/home/claude/da/utla_{t}.parquet' (format parquet)")
