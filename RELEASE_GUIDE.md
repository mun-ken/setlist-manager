Sådan udgiver du en ny version
===============================

Programmet tjekker automatisk **GitHub Releases** for nye versioner.
Det betyder at når DU udgiver en ny version på GitHub, så får ALLE dine
brugere automatisk besked næste gang de starter programmet.

Hele flowet — fra ændring til at brugerne får besked
----------------------------------------------------

### 1. Lav dine ændringer i koden
Ret det du vil rette i `main.py`, `setlist_model.py` osv.

### 2. Bump versionen i `version.py`
Åbn `version.py` og ret `APP_VERSION` — fx fra `"1.1.0"` til `"1.2.0"`.

Følg [Semantic Versioning](https://semver.org/lang/da/):
- **PATCH** (`1.1.0` → `1.1.1`): kun bugfixes
- **MINOR** (`1.1.0` → `1.2.0`): nye funktioner, bagudkompatibelt
- **MAJOR** (`1.1.0` → `2.0.0`): ændringer der bryder eksisterende filer

### 3. Commit, tag og push
```bash
git add version.py
git commit -m "Bump til 1.2.0"
git tag v1.2.0
git push
git push --tags
```

Det er **tagget** der trigger udgivelsen. Tagget skal hedde `v` + samme
version (fx `v1.2.0`) — workflowet tjekker det og fejler hvis de ikke
matcher.

### 4. Vent ~5 minutter
GitHub Actions:
1. Bygger `SetlistManager.exe` med PyInstaller
2. Pakker den i `SetlistManagerSetup.exe` med Inno Setup
3. **Opretter automatisk en GitHub Release** på
   `https://github.com/<owner>/<repo>/releases/tag/v1.2.0`
4. Hænger installeren ved som download-link

Følg fremskridtet under fanen **Actions** i dit GitHub-repo.

### 5. Brugerne får besked
Næste gang en bruger åbner Setlist Manager (max 24 timer), tjekker
programmet i baggrunden og viser en dialog:

> 🎉 Der er en ny version!
> Din version: 1.1.0
> Nyeste version: v1.2.0
> [Spring denne over] [Senere] [⬇ Download nu]

Tryk på "Download nu" → browseren åbner med direkte link til
`SetlistManagerSetup.exe`. Brugeren dobbeltklikker den → installerer
oven på den gamle version → kører den nye.


Første gang du sætter det op
----------------------------

### A. Konfigurer hvor opdateringer hentes fra
Ret `version.py`:
```python
GITHUB_OWNER = "dit-brugernavn"
GITHUB_REPO  = "navn-på-dit-repo"
```

Dette er den GitHub-konto + repo programmet kontakter ved hvert
opdaterings-tjek.

### B. Push dit repo til GitHub (hvis du ikke allerede har gjort det)
```bash
git init
git add .
git commit -m "Første version"
git remote add origin https://github.com/dit-brugernavn/dit-repo.git
git push -u origin main
```

Repoet skal være **public** for at GitHub Actions er gratis OG for at
brugerne kan hente Releases uden at logge ind.

### C. Tjek at workflowet kører
Gå til **Actions**-fanen → "Build Windows Installer" → første gang
skal du måske trykke "I understand my workflows, go ahead and run them".

### D. Lav din første Release
Følg trin 1-4 ovenfor med `APP_VERSION = "1.0.0"` og tag `v1.0.0`.


Hvad teknisk sker bag scenen
-----------------------------

| Komponent              | Rolle |
|------------------------|-------|
| `version.py`           | Single source of truth for versionsnummer + GitHub-repo |
| `updater.py`           | Henter `/releases/latest` fra GitHub API, sammenligner versioner |
| `main.py`              | Auto-tjek 3 sek. efter start (kun hvis sidste tjek >24t siden); menupunkt "🔄 Søg efter opdateringer…" |
| `installer.iss`        | Læser version fra `APP_VERSION` env-variabel |
| `build_windows.bat`    | Sætter `APP_VERSION` fra `version.py` før Inno Setup kører |
| `.github/workflows/build-windows.yml` | Trigges på tag-push, opretter GitHub Release, uploader installer |

**Ingen ekstra Python-afhængigheder** — vi bruger kun `urllib` fra
stdlib. Cache gemmes i `%APPDATA%\SetlistManager\last_update_check.json`.

**Privatliv:** Programmet sender kun én simpel GET-request til
`api.github.com` — ingen brugerdata, ingen telemetri.


Test før du udgiver
--------------------

```bash
# Tjek versionen
python3 -c "from version import APP_VERSION; print(APP_VERSION)"

# Tjek at updater virker (kontakter rigtigt GitHub)
python3 -c "from updater import check_for_update; print(check_for_update())"

# Kør alle tests
python3 test_save_load.py
```


Fejlfinding
-----------

**"Ingen forbindelse" når jeg trykker Søg efter opdateringer**
→ Tjek at `GITHUB_OWNER`/`GITHUB_REPO` i `version.py` er korrekte,
   og at repoet er public.

**Workflow fejler med "Tag matcher ikke APP_VERSION"**
→ Du har lavet `git tag v1.2.0` uden at bumpe `version.py` til `"1.2.0"`.
   Slet tagget (`git tag -d v1.2.0 && git push --delete origin v1.2.0`),
   bump versionen, commit, og tag igen.

**Release oprettes ikke**
→ Tjek at workflow har `permissions: contents: write` (det har den).
   Tjek under repo-settings → Actions → General → "Workflow permissions"
   at "Read and write permissions" er aktiveret.

**Brugerne får ikke besked om opdateringen**
→ Programmet auto-tjekker kun én gang pr. 24 timer. Brugeren kan
   manuelt tvinge et tjek via menuen: **Hjælp → 🔄 Søg efter opdateringer…**
