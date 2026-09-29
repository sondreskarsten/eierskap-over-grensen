from pathlib import Path

def assemble(src=Path(__file__).parent, out=Path(__file__).parents[2] / "index.html"):
    page = (src / "head3.html").read_text() + (src / "script3.html").read_text()
    page = (page.replace("__DATA__", (src / "data2.json").read_text().replace("</", "<\\/"))
                .replace("__GEOF__", (src / "fylker_small.json").read_text())
                .replace("__GEOK__", (src / "kommuner_small.json").read_text()))
    page = '<!doctype html>\n<html lang="nb">\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n<meta name="robots" content="noindex, nofollow">\n' + page
    out.write_text(page)
    return out

assemble()
