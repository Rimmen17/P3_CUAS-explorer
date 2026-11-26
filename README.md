# P3_CUAS Code Explorer

Interaktiv side over gruppe 341's kode i `twoods25/P3_CUAS`:
filtræ, systemkort, og for hver klasse og funktion hvad den gør, hvad den modtager og sender, og hvad den hænger sammen med.

**Siden:** https://rimmen17.github.io/P3_CUAS-explorer/

## Opdatér siden
Når der er kommet ny kode i P3_CUAS:

    python build_explorer.py --push

Scriptet henter den nyeste kode (med dit eget GitHub-login, fordi P3_CUAS er privat), bygger `site/index.html`
og pusher den. GitHub Pages viser den nye version efter ca. et minut.

Nye klasser, funktioner, routes og config-værdier kommer automatisk med, inklusive parametre, return-værdier og hvem der kalder hvem.

## Skriv en forklaring
Ny kode får en tom skabelon i `descriptions.json` og en rød prik på siden. Udfyld den og kør `python build_explorer.py --push` igen:

```json
"ptz/code/fooClass.py::Foo.bar": {
  "summary": "Hvad funktionen gør.",
  "params": {"x": "Hvad x er."},
  "returns": "Hvad den giver tilbage.",
  "notes": "Valgfri bemærkning.",
  "todo": ["Valgfri liste over mangler"]
}
```

En ny klasse kommer med på systemkortet, når du tilføjer `"sti::Klasse": [kolonne, række]` under `diagram`.

## Automatisk opdatering hver nat (valgfrit)
GitHub Actions kan ikke læse det private P3_CUAS uden en token. Sådan slår du det til:
1. Lav et fine-grained token på GitHub (Settings → Developer settings → Fine-grained tokens) med **Contents: Read-only** på `twoods25/P3_CUAS`. Er repoet ejet af en anden, skal ejeren måske godkende tokenet.
2. Gem det i dette repo under Settings → Secrets and variables → Actions med navnet `P3_CUAS_TOKEN`.

Så bygges siden hver nat kl. 03 UTC og ved hvert push.

## Andre muligheder
    python build_explorer.py --repo STI   # brug en lokal checkout
    python build_explorer.py --check      # exit 1 hvis noget mangler beskrivelse

Kræver kun Python 3.9+ (ingen pakker). Værdierne for IP, bruger og password fra `credentials.py` vises som •••.
Siden er offentlig, selvom P3_CUAS er privat, så den viser kildekoden for alle med linket.

Filer: `build_explorer.py` (parser), `template.html` (udseende), `descriptions.json` (forklaringer), `site/index.html` (den byggede side).
