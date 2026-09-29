import duckdb
con=duckdb.connect('/home/claude/da/scratch.duckdb')
z={
'II':{'50':"Inderøy,Indre Fosen,Meråker",'15':"Fjord,Rauma,Sande,Stranda,Sunndal,Sykkylven,Tingvoll,Vestnes",
      '46':"Askvoll,Aurland,Bremanger,Eidfjord,Fedje,Fjaler,Gloppen,Gulen,Hyllestad,Høyanger,Kvinnherad,Luster,Lærdal,Masfjorden,Modalen,Solund,Stad,Stryn,Tysnes,Ullensvang,Ulvik,Vik,Årdal",
      '11':"Hjelmeland,Sauda,Suldal",'42':"Bygland,Bykle,Evje og Hornnes,Gjerstad,Risør,Valle,Åmli,Åseral",
      '40':"Drangedal,Fyresdal,Hjartdal,Kviteseid,Nissedal,Nome,Seljord,Tinn,Tokke,Vinje",
      '34':"Eidskog,Grue,Kongsvinger,Nord-Fron,Nord-Odal,Nordre Land,Ringebu,Søndre Land,Sør-Fron,Sør-Odal,Trysil,Våler,Åmot,Åsnes",
      '33':"Flå,Gol,Hemsedal,Hol,Nesbyen,Nore og Uvdal,Rollag,Ål"},
'III':{'50':"Frøya,Heim,Hitra,Holtålen,Oppdal,Rennebu,Rindal,Røros,Tydal",'15':"Aure,Surnadal,Vanylven",
       '34':"Alvdal,Dovre,Engerdal,Etnedal,Folldal,Lesja,Lom,Nord-Aurdal,Os,Rendalen,Sel,Skjåk,Stor-Elvdal,Sør-Aurdal,Tolga,Tynset,Vang,Vestre Slidre,Vågå,Øystre Slidre"},
'IV':{'55':"Balsfjord,Bardu,Dyrøy,Gratangen,Harstad,Ibestad,Kvæfjord,Lavangen,Målselv,Salangen,Senja,Sørreisa,Tjeldsund",
      '18':"Alstahaug,Andøy,Beiarn,Bindal,Brønnøy,Bø,Dønna,Evenes,Fauske,Flakstad,Gildeskål,Grane,Hadsel,Hamarøy,Hattfjelldal,Hemnes,Herøy,Leirfjord,Lurøy,Lødingen,Meløy,Moskenes,Narvik,Nesna,Rana,Rødøy,Røst,Saltdal,Sortland,Steigen,Sømna,Sørfold,Træna,Vefsn,Vega,Vestvågøy,Vevelstad,Værøy,Vågan,Øksnes",
      '50':"Flatanger,Grong,Høylandet,Leka,Lierne,Namsos,Namsskogan,Nærøysund,Osen,Overhalla,Røyrvik,Snåsa,Åfjord",'15':"Smøla"},
'IVa':{'55':"Tromsø",'18':"Bodø"},
'V':{'55':"Karlsøy,Kvænangen,Kåfjord,Lyngen,Nordreisa,Skjervøy,Storfjord",
     '56':"Alta,Berlevåg,Båtsfjord,Tana,Gamvik,Kautokeino,Hammerfest,Hasvik,Karasjok,Lebesby,Loppa,Måsøy,Nordkapp,Porsanger,Sør-Varanger,Nesseby,Vadsø,Vardø"},
'partial':{'50':"Orkland,Steinkjer,Ørland",'15':"Molde,Volda,Ålesund,Haram",'46':"Kinn,Sogndal,Sunnfjord,Voss"},
}
rows=[(zone,c,n.strip().upper()) for zone,d in z.items() for c,v in d.items() for n in v.split(',')]
con.execute("create or replace table zmap(zone varchar, fylke varchar, name varchar)")
con.executemany("insert into zmap values (?,?,?)",rows)
con.execute("create or replace table kzone as select k.knr, k.kname, coalesce(z.zone,'I') as zone from knr k left join zmap z on substr(k.knr,1,2)=z.fylke and upper(k.kname)=z.name where k.knr<>'2100'")
print(con.execute("select zone, count(*) from kzone where knr in (select knr from knr where n>50) group by 1 order by 1").fetchall())
print(con.execute("select * from zmap z where not exists (select 1 from kzone k where substr(k.knr,1,2)=z.fylke and upper(k.kname)=z.name)").fetchall())
