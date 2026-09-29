import duckdb
from google.oauth2 import service_account
import google.auth.transport.requests as tr

cred = service_account.Credentials.from_service_account_file(
    "/mnt/project/sondreskarsten-d7d14-8486be2d085b.json",
    scopes=["https://www.googleapis.com/auth/devstorage.read_only"])
cred.refresh(tr.Request())

con = duckdb.connect("/home/claude/da/foreign_shift.duckdb")
con.sql("install httpfs; load httpfs")
con.sql(f"create or replace secret gcs_tok (type gcs, bearer_token '{cred.token}')")

con.sql("""
create or replace table pre_enh as
select org_nr, name, legal_form, employees, employees_reported, country_code, postal_country_code, location_country_code,
       foreign_law_country_code, foreign_legal_form, foreign_register_name, foreign_registration_number,
       foreign_reg_country, foreign_reg_city, foreign_reg_address, municipality_code, nace_1, deletion_date
from read_parquet('gs://sondre_brreg_data/enheter/parsed/v1/state/2025-12-31.parquet')
""")

con.sql("""
create or replace table pre_und as
select organisasjonsnummer, overordnet_enhet, navn, antall_ansatte, har_registrert_antall_ansatte,
       beliggenhetsadresse_kommunenummer, beliggenhetsadresse_landkode, naeringskode1_kode, nedleggelsesdato, slettedato, dato_eierskifte
from read_parquet('gs://sondre_brreg_data/underenheter/parsed/v2/state/2025-12-31.parquet')
""")

print(con.sql("select count(*) from pre_enh").fetchone(), con.sql("select count(*) from pre_und").fetchone())
print(con.sql("""select legal_form, count(*) n, count(foreign_registration_number) f_regnr, count(foreign_law_country_code) f_land
                 from pre_enh where foreign_registration_number is not null or foreign_law_country_code is not null group by 1 order by 2 desc limit 8""").df())
print(con.sql("""select org_nr, name, legal_form, foreign_law_country_code, foreign_registration_number, country_code
                 from pre_enh where foreign_law_country_code is not null and legal_form='NUF' limit 5""").df().to_string(index=False))
