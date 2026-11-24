# graeSynth-Website

Stand 18.11.2026 · statische Vorschau-Website (Deutsch + Englisch), erzeugt mit `build_site.py`

## Aufbau

| Pfad | Inhalt |
|---|---|
| `content/modules.json` | Texte je Modul (Name, Kurzzeile, Beschreibung, Merkmale; de/en). Von Hand gepflegt. |
| `content/site.json` | Seitentexte (Startseite, Familien, Stand, Platzhalter Impressum/Datenschutz; de/en). |
| `assets/site.css`, `assets/site.js` | Gestaltung, Filter im Modulraster, 3D-Viewer. |
| `build_site.py` | Generator. Schreibt alles nach `dist/`. |
| `dist/` | Fertige Website. Dieser Ordner wird hochgeladen. Nicht von Hand ändern. |

## Erzeugen

```
"C:\Program Files\KiCad\10.0\bin\python.exe" 010_Module\_kicad_tools\render3d.py
"C:\Program Files\KiCad\10.0\bin\python.exe" 050_Marketing\Website\build_site.py
```

- Zuerst `render3d.py`: Es baut die zusammengebauten Modelle (`_komplett`), aus denen die Website ihre Bilder und 3D-Modelle nimmt.
- `build_site.py` rendert je Modul eine Frontansicht und ein Schrägbild und kopiert das GLB-Modell. Bilder entstehen nur neu, wenn das Modell neuer ist.
- `--no-images` schreibt nur HTML und Daten. `--only=A6,D1` rendert nur diese Module. `--force` rendert alles neu.

## Was woher kommt

- **Breite (TE/HP), Buchsen, Regler, Schalter, Ausführung:** aus den KiCad-Dateien (Panel und Platinen).
- **LEDs:** Lage aus den Footprints `LED_*` der Vorderplatine, auf die nächste Panelbohrung gesetzt. Im Bild pulsieren Leuchtpunkte (CSS), im 3D-Modell die Materialien `LED:<Referenz>` (`glb_pack.py`, `site.js`).
- **3D-Modelle verkleinern (seit 20.11.2026):** zwei Stufen in `glb_pack.py`. Stufe 1 (`pack`) fasst die Teile zusammen, Stufe 2 (`squeeze`) komprimiert mit `_tools/gltfpack/gltfpack.exe` (gltfpack 1.3 aus den GitHub-Releases von zeux/meshoptimizer, MIT; Aufruf `-cc -km -vp 16`). Alle 34 Modelle zusammen: 87 → 22 MB. Fehlt die exe, bleibt es bei Stufe 1. Der Viewer braucht dafür den meshopt-Decoder; `site.js` lädt ihn von jsdelivr (`meshoptimizer@0.22.0`) und setzt `src` erst danach.
- **Fertigmodul / Bausatz (seit 21.11.2026):** Gibt es zu einem Modul beide Platinensätze (`PCB_SMD` und `PCB_THT`), baut `build_site.py` zusätzlich `img/<id>-kit-3d.webp` und `models/<id>-kit.glb` aus `<Kit-Vorderplatine>_komplett`. Die Modulseite bekommt dann einen Umschalter, der Schrägbild und 3D-Modell tauscht (`.variants` in `site.js`). Die Frontansicht bleibt gleich, weil beide dasselbe Panel haben. Weitere Ausführungen aus `PCB_SMD_V<n>_<Kennung>` (D2: `rgb`) kommen als dritte Option dazu (`<id>-rgb-3d.webp`, `<id>-rgb.glb`); die Frontansicht oben zeigt weiter das Standard-Panel. Beschriftungen: `variant_<kennung>` und `alt3d_<kennung>` in `content/site.json`.
- **Standard-Ausführung (seit 22.11.2026):** `"default_variant": "RGB"` in `content/modules.json` (D2) macht diese Ausführung zum Fertigmodul der Seite: Frontbild, Systemübersicht, Schrägbild und 3D-Modell. Die Grundausführung bleibt als Option `mono` („Einfarbige LEDs“). Die RGB-LEDs sind im Rendering farbig (render3d, `_led5_lit`), die Leuchtpunkte im Frontbild haben dieselbe Farbe (`.fp i.rgb`).
- **Schaltpläne (seit 22.11.2026):** `build_site.py` liest `010_Module/Schaltplaene_Website.md`, kopiert die dort genannten PDFs nach `dist/schematics/` und zeigt sie auf der Modulseite im Abschnitt „Schaltplan“ (Fertigmodul, Bausatz, bei mehreren Platinen je Teilplan). Ist ein PDF älter als sein `.kicad_sch`, meldet der Lauf das.
- **Datenblätter (seit 24.11.2026):** `build_site.py` liest `010_Module/Datenblaetter.md` (Spalten ID, Modul, Deutsch, Englisch), kopiert die PDFs nach `dist/datasheets/` und verlinkt unter der Spezifikationstabelle das Datenblatt in der Sprache der Seite. Erzeugt werden die PDFs mit `_kicad_tools/datenblatt.py` (nutzt die Bilder aus `dist/img`), nicht hier. Ist ein PDF älter als seine `datenblatt.json`, meldet der Lauf das.
- **Cache:** `site.css`, `site.js`, Bilder und Modelle bekommen `?v=<Dateistand>`, damit Browser nach einem Neubau nicht die alte Datei zeigen.
- **Texte:** aus `content/`. Sie stützen sich auf die `Benutzerhinweise.md` der Module.
- **Preise und Stromaufnahme:** bewusst nicht auf der Seite (Vorschau ohne Preise; Stromwerte sind noch nicht gemessen).

## Ansehen

Lokaler Server (in Claude: Vorschau `website`, Port 8780):

```
"C:\Program Files\KiCad\10.0\bin\python.exe" -m http.server 8780 --directory 050_Marketing\Website\dist
```

Dann `http://localhost:8780` öffnen.

## Veröffentlichen (seit 22.11.2026)

- Repo: `github.com/MarcGraedtke/graeSynth` (nur dieser Ordner; `dist/` wird mit eingecheckt, weil der Bau KiCad braucht).
- Railway baut aus dem `Dockerfile` einen Caddy-Server (`Caddyfile`), der `dist/` ausliefert. Jeder Push auf `main` veröffentlicht neu.
- Ablauf nach Änderungen: `build_site.py` → `git add -A` → `git commit` → `git push`.
- Vorschau-Sperre: `NOINDEX = True` in `build_site.py` (robots.txt) und `X-Robots-Tag` in der `Caddyfile`. Zum Freischalten beides entfernen.
- Impressum und Datenschutz: `content/legal/*.html`. Der Abschnitt `<!--cdn-->` erscheint nur, solange `site.js` den Viewer von jsdelivr lädt.

## Vor der Veröffentlichung offen

- Datenschutzerklärung ist ein Entwurf: vor dem Freischalten prüfen lassen (Railway-Region, Auftragsverarbeitung).
- Der 3D-Viewer (`model-viewer`) wird nach einem Klick von `cdn.jsdelivr.net` geladen. Für eine Seite ganz ohne fremde Server die Datei nach `assets/` legen und den Pfad in `site.js` ändern.
- Der Webserver sollte `.glb` zusätzlich komprimiert ausliefern (gzip/Brotli).
- Die Knöpfe in den Bildern sind Platzhalter, bis der Knopftyp feststeht.

## Späterer Umstieg auf Next.js

`dist/data/modules.json` enthält alle Module mit Texten, Fakten und Bildpfaden in einer Datei. Eine Next.js-Seite kann diese Datei und die Ordner `img/` und `models/` unverändert übernehmen.
