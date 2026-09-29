import duckdb, json
from google.oauth2 import service_account
from google.cloud import storage
import google.auth.transport.requests as tr

cred = service_account.Credentials.from_service_account_file(
    "/mnt/project/sondreskarsten-d7d14-8486be2d085b.json",
    scopes=["https://www.googleapis.com/auth/devstorage.read_only"])
cred.refresh(tr.Request())
storage.Client(credentials=cred, project="sondreskarsten-d7d14").bucket("cb-signaler-sim-rig") \
    .blob("underenheter/raw/underenheter_alle_2026-06-30.json.gz").download_to_filename("/home/claude/da/und_2026-06-30.json.gz")

con = duckdb.connect()
con.sql("install httpfs; load httpfs")
con.sql(f"create secret g (type gcs, bearer_token '{cred.token}')")

YEARS = {
    "2024": [("pq", "2024-07-02"), ("pq", "2024-09-29")],
    "2025": [("pq", "2025-06-30"), ("pq", "2025-09-30")],
    "2026": [("js", "/home/claude/da/und_2026-06-30.json.gz"), ("js", "/home/claude/da/underenheter.json.gz")],
}

def snap_sql(kind, ref):
    if kind == "pq":
        return f"""select overordnet_enhet parent, beliggenhetsadresse_kommunenummer knr,
                   lower(har_registrert_antall_ansatte) = 'true' har, try_cast(antall_ansatte as bigint) ans
                   from read_parquet('gs://sondre_brreg_data/underenheter/parsed/v2/state/{ref}.parquet')"""
    return f"""select overordnetEnhet parent, beliggenhetsadresse.kommunenummer knr, harRegistrertAntallAnsatte har, antallAnsatte ans
               from read_json('{ref}', format='array', maximum_object_size=100000000,
                    columns={{overordnetEnhet:'VARCHAR', beliggenhetsadresse:'STRUCT(kommunenummer VARCHAR)', harRegistrertAntallAnsatte:'BOOLEAN', antallAnsatte:'BIGINT'}})"""

d = json.load(open("/home/claude/da/viz/data2.json"))
moved = sorted({r["o"] for r in d["rows"]})
con.sql("create table moved as select unnest(?::varchar[]) orgnr", params=[moved])

emp, base = {}, {}
for y, snaps in YEARS.items():
    parts = []
    for i, (kind, ref) in enumerate(snaps):
        con.sql(f"create or replace table s{i} as {snap_sql(kind, ref)}")
        parts.append(f"s{i}")
    for parent, knr, ans in con.sql(f"""
        with a as (select parent, knr, sum(coalesce(ans,0)) ans from s0 join moved m on m.orgnr = parent where har group by 1, 2),
             b as (select parent, knr, sum(coalesce(ans,0)) ans from s1 join moved m on m.orgnr = parent where har group by 1, 2)
        select coalesce(a.parent, b.parent), coalesce(a.knr, b.knr), (coalesce(a.ans,0) + coalesce(b.ans,0)) / 2.0
        from a full join b on a.parent = b.parent and a.knr is not distinct from b.knr""").fetchall():
        emp.setdefault(parent, {}).setdefault(y, []).append([knr, round(float(ans), 1)])
    for knr, ans in con.sql("""
        with a as (select knr, sum(coalesce(ans,0)) ans from s0 where har and knr is not null group by 1),
             b as (select knr, sum(coalesce(ans,0)) ans from s1 where har and knr is not null group by 1)
        select coalesce(a.knr, b.knr), (coalesce(a.ans,0) + coalesce(b.ans,0)) / 2.0 from a full join b using (knr)""").fetchall():
        base.setdefault(knr, {})[y] = round(float(ans), 1)

d["emp_hist"] = emp
d["base_hist"] = base
d["emp_years"] = ["2024", "2025", "2026"]
d["emp_snaps"] = {y: [s[1].split("/")[-1].replace("und_", "").replace(".json.gz", "").replace("underenheter", "2026-09-28") for s in v] for y, v in YEARS.items()}
d.pop("snaps", None)
json.dump(d, open("/home/claude/da/viz/data2.json", "w"), ensure_ascii=False, separators=(",", ":"))

for y in YEARS:
    ids = {r["o"] for r in d["rows"]}
    print(y, "moved companies", round(sum(x[1] for o in ids for x in emp.get(o, {}).get(y, []))),
          "| national", round(sum(v.get(y, 0) for v in base.values())))
print(d["emp_snaps"])
