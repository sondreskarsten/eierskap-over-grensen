import subprocess
import duckdb

src_url = "https://stotte.brreg.no/nb/oppslag/stoettetildeling/totalbestand/csv"
raw = "/home/claude/da/totalbestand.csv"
utf8 = "/home/claude/da/totalbestand_utf8.csv"
out = "/home/claude/da/da_tildelinger.parquet"

schemes = {
    "1000000033": "Regionalt differensiert arbeidsgiveravgift 2014-2020",
    "1000000098": "Differensiert arbeidsgiveravgift for transport- og energisektoren",
    "1000000422": "Regionalt differensiert arbeidsgiveravgift 2021",
    "1000000420": "Regionalt differensiert arbeidsgiveravgift 2022-2027",
    "1000029830": "Regionalt DA 2026-",
    "1000031862": "Regionalt DA bagatellmessig 2026",
}


def build(download=False):
    if download:
        subprocess.run(["curl", "-sS", "-L", "--max-time", "600", "-o", raw, src_url], check=True)
    subprocess.run(f"iconv -f UTF-16 -t UTF-8 {raw} > {utf8}", shell=True, check=True)
    con = duckdb.connect()
    con.execute(f"create table tb as select * from read_csv('{utf8}', delim=';', header=true, quote='\"', all_varchar=true)")
    con.execute("create table s(scheme_id varchar, scheme_name varchar)")
    con.executemany("insert into s values (?, ?)", list(schemes.items()))
    con.execute(f"""
        copy (
          select tb.*,
                 s.scheme_id,
                 s.scheme_name,
                 strptime(tb."Tildelingsdato", '%d.%m.%Y')::date as tildelingsdato_d,
                 strptime(tb."Mottatt dato", '%d.%m.%Y')::date as mottatt_dato_d,
                 replace(tb."Tildelt beløp", ',', '.')::double as tildelt_belop_num
          from tb join s on tb."Tilknyttet støtteordning" = s.scheme_id
        ) to '{out}' (format parquet)
    """)
    return con.execute(f"select scheme_id, count(*) from '{out}' group by 1 order by 1").fetchall()


print(build())
