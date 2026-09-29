import duckdb, json
import pandas as pd

con = duckdb.connect("/home/claude/da/utla_shift.duckdb", read_only=True)
con.sql("attach '/home/claude/da/scratch.duckdb' as s (read_only)")
con.sql("attach '/home/claude/da/foreign_shift.duckdb' as f (read_only)")

FYLKE = {"03": "Oslo", "11": "Rogaland", "15": "Møre og Romsdal", "18": "Nordland", "31": "Østfold", "32": "Akershus",
         "33": "Buskerud", "34": "Innlandet", "39": "Vestfold", "40": "Telemark", "42": "Agder", "46": "Vestland",
         "50": "Trøndelag", "55": "Troms", "56": "Finnmark"}
TYPE = {"move": "Eier flyttet utenlands", "sale": "Solgt til utenlandsk eier",
        "already_foreign_owner": "Kjøpt inn i utenlandsk konsern"}
ZONE = {"I": "I/Ia", "II": "II", "III": "III", "IV": "IV", "IVa": "IVa", "V": "V", "partial": "delt"}

con.sql("""
create temp table enh_now as
select organisasjonsnummer orgnr, navn, organisasjonsform.kode form, harRegistrertAntallAnsatte har_ans, antallAnsatte ansatte,
       forretningsadresse.kommunenummer knr, forretningsadresse.kommune kommune
from read_json('/tmp/claude-0/enheter.json.gz', format='array', maximum_object_size=100000000,
     columns={organisasjonsnummer:'VARCHAR', navn:'VARCHAR', organisasjonsform:'STRUCT(kode VARCHAR)', harRegistrertAntallAnsatte:'BOOLEAN',
              antallAnsatte:'BIGINT', forretningsadresse:'STRUCT(kommunenummer VARCHAR, kommune VARCHAR)'})
""")
con.sql("""
create temp table und_now as
select overordnetEnhet parent, harRegistrertAntallAnsatte har_ans, antallAnsatte ansatte, beliggenhetsadresse.kommunenummer knr
from read_json('/home/claude/da/underenheter.json.gz', format='array', maximum_object_size=100000000,
     columns={overordnetEnhet:'VARCHAR', harRegistrertAntallAnsatte:'BOOLEAN', antallAnsatte:'BIGINT', beliggenhetsadresse:'STRUCT(kommunenummer VARCHAR)'})
""")
con.sql("""
create temp table da26 as
select "Organisasjonsnummer støttemottaker" orgnr, sum(tildelt_belop_num) da_nok
from read_parquet('/home/claude/da/da_tildelinger.parquet') where scheme_id in ('1000029830','1000031862') group by 1
""")

rows = con.sql("""
select t.yr, t.orgnr, t.sale_or_move, t.depth, t.group_top,
       coalesce(e.navn, pe.name) navn, coalesce(e.knr, pe.municipality_code) knr, e.kommune,
       coalesce(e.har_ans, t.has_emp, false) har_ans, e.ansatte ansatte_now,
       d.da_nok, t.f_name, t.f_land, t.f_key, t.f_is_person, t.f_pct,
       coalesce(g.navn, gpe.name) top_navn
from fats2_tr t
left join enh_now e on e.orgnr = t.orgnr
left join f.pre_enh pe on pe.org_nr = t.orgnr
left join da26 d on d.orgnr = t.orgnr
left join enh_now g on g.orgnr = t.group_top
left join f.pre_enh gpe on gpe.org_nr = t.group_top
where t.curr_kind = 'foreign' and t.sale_or_move in ('move','sale','already_foreign_owner')
""").df()

moved = tuple(sorted(set(rows.orgnr)))
con.sql("create temp table moved as select unnest(?::varchar[]) orgnr", params=[list(moved)])
units = con.sql("""
select u.parent orgnr, u.knr, sum(coalesce(u.ansatte, 0)) ans, count(*) filter (where u.har_ans) n_emp_units
from und_now u join moved m on m.orgnr = u.parent where u.har_ans group by 1, 2
""").df()

def ubo(r):
    if not pd.isna(r.f_is_person) and r.f_is_person:
        parts = [p for p in str(r.f_name).replace("-", " ").split() if p]
        ini = ".".join(p[0] for p in parts) + "." if parts else "?"
        by = str(r.f_key).split("|")[-1] if str(r.f_key).startswith("P|") else ""
        return f"{ini} f. {by}".strip()
    return str(r.f_name).title() if not pd.isna(r.f_name) else "Ukjent"

out = []
for r in rows.itertuples():
    knr = "" if pd.isna(r.knr) else r.knr
    out.append({
        "y": int(r.yr), "o": r.orgnr, "n": "" if pd.isna(r.navn) else r.navn.title(), "t": TYPE[r.sale_or_move],
        "kn": knr, "f": knr[:2] if knr[:2] in FYLKE else "",
        "e": bool(r.har_ans) if not pd.isna(r.har_ans) else False,
        "a": None if pd.isna(r.ansatte_now) else int(r.ansatte_now),
        "da": None if pd.isna(r.da_nok) else round(float(r.da_nok)),
        "u": ubo(r), "p": bool(r.f_is_person) if not pd.isna(r.f_is_person) else False,
        "c": "" if pd.isna(r.f_land) else r.f_land,
        "pct": None if pd.isna(r.f_pct) else round(float(r.f_pct) * 100, 1),
        "g": r.group_top, "gn": "" if pd.isna(r.top_navn) else r.top_navn.title(), "d": int(r.depth),
    })

emp_units = {}
for r in units.itertuples():
    if pd.isna(r.knr): continue
    emp_units.setdefault(r.orgnr, []).append([r.knr, int(r.ans)])

kz = {r.knr: ZONE.get(r.zone, "I/Ia") for r in con.sql("select knr, zone from s.kzone").df().itertuples()}
kname = {r.knr: r.kommune.title() for r in con.sql("select knr, any_value(kommune) kommune from enh_now where knr is not null and kommune is not null group by 1").df().itertuples()}

den = {}
for r in con.sql("select knr, sum(coalesce(ansatte,0)) ans from und_now where har_ans and knr is not null group by 1").df().itertuples():
    den.setdefault(r.knr, {})["ans"] = int(r.ans)
for r in con.sql("select e.knr, sum(d.da_nok) da from da26 d join enh_now e using (orgnr) where e.knr is not null group by 1").df().itertuples():
    den.setdefault(r.knr, {})["da"] = round(float(r.da))

con.sql("""
create temp table univ as
select o.yr, o.orgnr, o.okey, coalesce(e.knr, pe.municipality_code) knr, coalesce(e.har_ans, false) har_ans
from owners2 o
left join enh_now e on e.orgnr = o.orgnr
left join f.pre_enh pe on pe.org_nr = o.orgnr
left join forms fo on fo.orgnr = o.orgnr
left join vps v on v.orgnr = o.orgnr
where o.yr in (2024, 2025) and coalesce(fo.legal_form,'') <> 'ASA' and v.orgnr is null
""")
con.sql("create temp table kzm as select knr, zone from s.kzone")
pop = con.sql("""
with u as (select univ.*, left(knr, 2) fy, coalesce(kzm.zone, 'I') as zn from univ left join kzm using (knr) where knr is not null)
select yr, knr, fy, zn,
       count(distinct orgnr) cos, count(distinct orgnr) filter (where har_ans) cos_e,
       count(distinct okey) own, count(distinct okey) filter (where har_ans) own_e,
       grouping(knr) gk, grouping(zn) gz
from u group by grouping sets ((yr, knr, fy, zn), (yr, fy), (yr, fy, zn))
""").df()
popmap = {}
for r in pop.itertuples():
    if r.fy not in FYLKE: continue
    if r.gk == 0: key = "k:" + r.knr
    elif r.gz == 1: key = "f:" + r.fy
    else: key = "z:" + r.fy + ":" + ZONE.get(r.zn, "I/Ia")
    d = popmap.setdefault(key, {})
    for m in ["cos", "cos_e", "own", "own_e"]:
        d[f"{m}_{int(r.yr)}"] = d.get(f"{m}_{int(r.yr)}", 0) + int(getattr(r, m))

kommuner = {k: {"n": kname.get(k, k), "z": kz.get(k, "I/Ia"), **v} for k, v in den.items() if k[:2] in FYLKE}

json.dump({"rows": out, "units": emp_units, "fylker": FYLKE, "kommuner": kommuner, "pop": popmap},
          open("/home/claude/da/viz/data2.json", "w"), ensure_ascii=False, separators=(",", ":"))
print(len(out), "rows;", len(emp_units), "companies with located units;", len(kommuner), "kommuner")
tot = {k: sum(v.get(k, 0) for v in kommuner.values()) for k in ["ans", "da"]}
print("national denominators:", tot, "; fylke pops:", sum(v.get("cos_2025",0) for k,v in popmap.items() if k.startswith("f:")))
print("numerators: emp in located units", sum(a for v in emp_units.values() for _, a in v), "; da", sum(x["da"] or 0 for x in out))
