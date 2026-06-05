Setlist Manager
===============

Et komplet program til at holde styr på bandets sange og bygge setlister
til koncerter. Tænkt så **slutbrugeren kun behøver at dobbeltklikke én
installer-fil** — så er programmet klar i Start-menuen og på skrivebordet.

Funktioner
----------
- � **Flere bands** i samme fil — hver med eget bibliotek og setlister
- �🎵 **Sangbibliotek** med navn, toneart, længde og noter
- 🌐 **Importér sange fra internet** — skriv et bandnavn (fx "D-A-D"),
  vælg det rigtige band fra MusicBrainz, kryds sange af og importér
- 🔍 **Søg** i biblioteket eller på tværs af alle dine bands
- 📚 **Flere setlister** pr. band (én pr. koncert/gig)
- 🖱️ **Træk-og-slip** for at sortere sange i setlisten
- 🇩🇰 **Dansk brugerflade** hele vejen igennem
- 💾 **Auto-gem** efter hver ændring — du kan aldrig miste noget
- 🖨️ **Print som A4** med dialog hvor du vælger:
  - hvilke kolonner der skal med (nummer, toneart, længde, noter, samlet spilletid)
  - tekststørrelse i 5 trin (Mini / Lille / Mellem / Stor / Maxi)
  - om bandets logo skal vises i øverste højre hjørne
  - om titel, meta-linje, dato, kolonneoverskrifter og markører skal med
  - **"Alt til" / "Alt fra"-knapper** så du hurtigt får ren minimal version
  - **Live forhåndsvisning** i dialogen — du ser med det samme hvordan
    arket kommer til at se ud når du ændrer noget
  - 🌐 Knap til **fuld forhåndsvisning i browser** hvis du vil se A4-versionen
- 🎬 **Sektion-markører i setlisten** — sæt "EKSTRA-NUMMER", "PAUSE",
  "— SLUT —" eller dit eget tekst-mærke ind så bandet altid kan se
  hvornår hovedsættet er færdigt. Markører vises både i appen
  (gul baggrund, fed kursiv) og på det printede ark
- 🚫 **Sange du allerede har valgt vises gråt** i biblioteket — så du
  altid kun kan vælge hver sang én gang til samme setliste
- 🖼️ **Logo pr. band** — vælg et billede (PNG/JPG/GIF/BMP/WebP); det vises
  automatisk i øverste højre hjørne af A4-arket og gemmes inde i filen
  (ingen eksterne filer at holde styr på)
- ⌨️ Genveje: `Ctrl+S` gem som, `Ctrl+O` åbn, `Ctrl+P` print, `Ctrl+F` søg
- 🎨 Eget program-ikon
- 🔄 **Auto-update** — programmet tjekker selv (max én gang i døgnet)
  om der er en nyere version på GitHub. Hvis ja vises en dialog med
  release-noter og en knap til at hente installeren. Kan også tjekkes
  manuelt fra menuen *Hjælp → Søg efter opdateringer…*

Filerne i projektet
-------------------
| Fil                                   | Formål                                            |
| ------------------------------------- | ------------------------------------------------- |
| `main.py`                             | Tkinter GUI (dansk)                               |
| `setlist_model.py`                    | Datamodel (testbar uden GUI)                      |
| `music_search.py`                     | Opslag i MusicBrainz (internet-import)            |
| `version.py`                          | **Single source of truth** for version + repo-info|
| `updater.py`                          | Online opdaterings-tjek mod GitHub Releases       |
| `test_save_load.py`                   | 70 enhedstests (kører uden Tkinter og internet)   |
| `make_icon.py`                        | Genererer `assets/app.ico` med Pillow             |
| `requirements.txt`                    | Build-dependencies (PyInstaller, Pillow)          |
| `setlist.spec`                        | PyInstaller-opskrift → `SetlistManager.exe`       |
| `build_windows.bat`                   | Ét-klik build på Windows                          |
| `installer.iss`                       | Inno Setup-opskrift → `SetlistManagerSetup.exe`   |
| `.github/workflows/build-windows.yml` | Automatisk cloud-build + GitHub Release ved tags  |
| `RELEASE_GUIDE.md`                    | Komplet vejledning til at udgive en ny version    |

---

For SLUTBRUGEREN (din bandkammerat)
-----------------------------------
1. Download `SetlistManagerSetup.exe`.
2. Dobbeltklik den.
3. Klik "Næste" → "Installér" → "Færdig".
4. Åbn *Setlist Manager* fra Start-menuen eller skrivebordet.

Ingenting andet skal installeres. Python, Tkinter, Pillow og alle
afhængigheder er pakket ind i installeren.

Det første som åbnes er et lille eksempel-bibliotek så man kan se hvordan
det virker. Det bliver auto-gemt til `%APPDATA%\SetlistManager\autosave.json`.

---

For DIG (sådan laver du installeren)
------------------------------------
Tre veje. Vælg den der passer.

### 🟢 Vej A — Lad GitHub bygge den (anbefales, ingen Windows-PC nødvendig)
1. Opret en gratis GitHub-konto og upload denne mappe som et nyt repo.
2. Åbn fanen **Actions** → *Build Windows Installer* → **Run workflow**.
3. Vent ~3 minutter. Hent zip-filen under *Artifacts*.
4. Inde i den ligger:
   - `SetlistManager.exe` (standalone — kør direkte)
   - `SetlistManagerSetup.exe` (den rigtige installer at give videre)

### 🔵 Vej B — Byg på en Windows-PC (ét klik)
1. Installer Python 3.10+ fra <https://python.org> (sæt flueben i *Add to PATH*).
2. Kopiér hele mappen over på Windows-PC'en.
3. Dobbeltklik **`build_windows.bat`** — den klarer resten.
4. Resultat: `dist\SetlistManager.exe`.
5. (Valgfrit, for rigtig installer) Installer
   [Inno Setup 6](https://jrsoftware.org/isinfo.php), højreklik
   `installer.iss` → *Compile* → `Output\SetlistManagerSetup.exe`.

> 💡 **Har du ikke Python installeret?** Det er helt OK — `build_windows.bat`
> opdager det og tilbyder at installere Python automatisk for dig. Sig bare
> "J" når den spørger. Eller dobbeltklik `install_python.bat` først.


### 🟡 Vej C — Manuel build
```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python make_icon.py
pyinstaller setlist.spec --noconfirm
```

---

Kør fra kildekode (udvikling)
-----------------------------
```bash
# macOS / Linux
python3 main.py

# Windows
python main.py
```

Kør tests
---------
```bash
python3 test_save_load.py
```

Hvor gemmes data?
-----------------
Auto-gem ligger i:
- **Windows**: `%APPDATA%\SetlistManager\autosave.json`
- **macOS / Linux**: `~/.setlist_manager/autosave.json`

Brug `Gem som…` for at gemme en kopi et andet sted (fx i Dropbox/OneDrive
hvis I vil dele setlisten med flere bandmedlemmer).

Cachen for opdaterings-tjek ligger samme sted i `last_update_check.json`
— den sørger for at vi højst spørger GitHub én gang i døgnet.

Udgiv en ny version (auto-update)
---------------------------------
1. Ret `APP_VERSION` i **`version.py`** (fx fra `"1.1.0"` til `"1.2.0"`).
2. Commit + push.
3. Lav et git-tag der **matcher** versionen og push det:
   ```bash
   git tag v1.2.0
   git push origin v1.2.0
   ```
4. GitHub Actions bygger automatisk installeren og opretter en
   **Release** med `SetlistManagerSetup-1.2.0.exe` vedhæftet.
5. Alle eksisterende brugere ser et opdaterings-vindue næste gang de
   starter programmet (eller via *Hjælp → Søg efter opdateringer…*).

Se **`RELEASE_GUIDE.md`** for trinvis vejledning og fejlfinding.

Noter
-----
- Den færdige `.exe` er ~15 MB og kan tage et par sekunder om at starte
  første gang — helt normalt for PyInstaller `--onefile` apps.
- Cross-compile af Windows `.exe` fra macOS/Linux understøttes ikke af
  PyInstaller. Brug Vej A (GitHub Actions) hvis du ikke har en Windows-PC.
- JSON-filer fra version 1 indlæses og opgraderes automatisk til v2.

Fejlfinding
-----------
**"Python is not installed or not on PATH"**
> Du har en ældre version af `build_windows.bat`. Hent den nye version —
> den installerer Python automatisk for dig. Eller dobbeltklik
> `install_python.bat` først.

**"Python blev installeret men kan ikke ses i dette vindue endnu"**
> Helt normalt. Luk `cmd`-vinduet og dobbeltklik `build_windows.bat` igen
> så finder den den nyligt installerede Python.

**Build'et stopper med "Failed building wheel for Pillow"**
> Du mangler Microsoft Visual C++ Build Tools. Den nemmeste løsning:
> kør `build_windows.bat` igen — pip prøver først at hente en præ-bygget
> version, og det virker næsten altid på Windows.

**Windows Defender / SmartScreen blokerer `.exe`'en**
> Højreklik filen → *Egenskaber* → sæt flueben i *Fjern blokering*.
> Det sker fordi den ikke er kode-signeret (kode-signering koster penge).
> Hvis du distribuerer den til andre er det nemmeste at sende dem
> `SetlistManagerSetup.exe` (Inno Setup-installeren) i stedet, da den
> sjældent får samme advarsel.

