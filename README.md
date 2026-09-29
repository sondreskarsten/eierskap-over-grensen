# Eierskap over grensen

Proof of concept: norske selskaper som gikk over til utenlandsk kontroll i inntektsårene 2024 og 2025.

Side: https://sondreskarsten.github.io/eierskap-over-grensen/

Kilder: Aksjonærregisteret (Skatteetaten), Enhetsregisteret og Støtteregisteret (Brønnøysundregistrene), bearbeidet i `gs://sondre_brreg_data`.

## Oppdatere

`index.html` er selvstendig (data innebygd). Bygg på nytt i denne rekkefølgen:

| Steg | Skript | Lager |
|---|---|---|
| 1 | `src/pipeline/zones.py` | `scratch.duckdb`: `kzone` (kommune → AGA-sone) |
| 2 | `src/pipeline/foreign_shift_pre.py` | `foreign_shift.duckdb`: `pre_enh`, `pre_und` (enheter/underenheter per 2025-12-31 fra GCS) |
| 3 | `src/pipeline/utla_shift.py` | `utla_shift.duckdb`: `forms`, `aksje`, `own`, `shift` |
| 4 | `src/pipeline/ownership_nesting.py` | `utla_shift.duckdb`: `vps`, kjeder og norsk konserntopp |
| 5 | `src/pipeline/ubo_sale_vs_move.py` | `utla_shift.duckdb`: `owners2`, `fats2_tr` (salg vs. flytting) |
| 6 | `src/pipeline/da_tildelinger.py` | `da_tildelinger.parquet` (AGA-støtte fra Støtteregisteret totalbestand) |
| 7 | `src/viz/build_data2.py` | `src/viz/data2.json` (rader, populasjoner, kommuner) |
| 8 | `src/viz/build_emp_years.py` | legger ansatte 2024/2025/2026 (snitt juni/september) inn i `data2.json` |
| 9 | `src/viz/assemble.py` | `index.html` fra `head3.html` + `script3.html` + `data2.json` + geodata |

Kun frontend-endringer: rediger `src/viz/head3.html` / `script3.html` og kjør steg 9.

## Lokale input som ikke ligger i repoet

Skriptene har hardkodede stier fra arbeidsmiljøet (`/home/claude/da/`, `/tmp/claude-0/`) og må pekes om:

- Aksjonærregisteret CSV per år: `aksje_2023.csv`, `aksje_2024.csv`, `a2025.csv` (steg 3)
- Underenheter-bulk 2024-07-01: `und_2024-07-01.csv.gz` (steg 3)
- Støtteregisteret totalbestand: `totalbestand.csv` (steg 6)
- Enheter- og underenheter-bulk fra Brønnøysund-API (dagens): `enheter.json.gz`, `underenheter.json.gz` (steg 7–8)
- GCP service-account for lesing av `gs://sondre_brreg_data` og `gs://cb-signaler-sim-rig` (steg 2, 8). Nøkkel ligger ikke i repoet.
