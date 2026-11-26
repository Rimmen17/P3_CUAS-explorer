# P3_CUAS Code Explorer

Interaktiv side over gruppe 341's kode i [twoods25/P3_CUAS](https://github.com/twoods25/P3_CUAS):
filtræ, systemkort, og for hver klasse og funktion hvad den gør, hvad den modtager og sender, og hvad den hænger sammen med.

**Siden:** https://rimmen17.github.io/P3_CUAS-explorer/

## Hvordan den holdes opdateret
En GitHub Action (`.github/workflows/build.yml`) bygger siden igen:
- hver nat (henter den nyeste kode fra P3_CUAS),
- ved hvert push til dette repo (fx når en beskrivelse er rettet),
- når du trykker **Actions → Byg Code Explorer → Run workflow**.

Nye klasser, funktioner, routes og config-værdier kommer automatisk med, inklusive parametre, return-værdier og hvem der kalder hvem.

## Skriv en forklaring
1. Find nøglen: den står på siden under en funktion uden beskrivelse (rød prik), fx `ptz/code/targetClass.py::TargetCalculator.calculate_command`.
2. Tilføj eller ret den i `descriptions.json`:
   ```json
   "ptz/code/fooClass.py::Foo.bar": {
     "summary": "Hvad funktionen gør.",
     "params": {"x": "Hvad x er."},
     "returns": "Hvad den giver tilbage.",
     "notes": "Valgfri bemærkning.",
     "todo": ["Valgfri liste over mangler"]
   }
   ```
3. Commit. Siden bygges igen af sig selv.

En ny klasse kommer med på systemkortet, når du tilføjer `"sti::Klasse": [kolonne, række]` under `diagram`.

## Byg lokalt
    python build_explorer.py              # henter P3_CUAS og skriver P3_CUAS_explorer.html
    python build_explorer.py --repo STI   # bruger en lokal checkout
    python build_explorer.py --check      # exit 1 hvis noget mangler beskrivelse

Lokalt skriver scriptet tomme skabeloner for ny kode ind i `descriptions.json`. Udfyld dem og commit.
Kræver kun Python 3.9+ (ingen pakker).

Værdierne for IP, bruger og password fra `credentials.py` bliver erstattet med ••• på siden.

Filer: `build_explorer.py` (parser), `template.html` (udseende), `descriptions.json` (forklaringer).
