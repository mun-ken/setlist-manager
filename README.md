Setlist Manager
===============

Et komplet program til at holde styr på bandets sange og bygge setlister
til koncerter. Dansk brugerflade hele vejen — designet til at virke på
scenen uden at man behøver tænke over det.

📥 [**Download nyeste version til Windows**](https://github.com/mun-ken/setlist-manager/releases/latest)

---

Hvad kan den?
-------------

### 🎸 Sange og setlister
- **Flere bands** i samme fil — hvert med eget bibliotek og setlister
- **Sangbibliotek** med navn, toneart, længde og noter
- **Flere setlister pr. band** (én pr. koncert/gig)
- **Træk-og-slip** for at sortere sange i setlisten
- **Sektion-markører** — sæt "EKSTRA-NUMMER", "PAUSE", "— SLUT —" eller
  dit eget tekst-mærke ind så bandet altid kan se hvornår hovedsættet
  er færdigt
- **Sange du allerede har valgt vises gråt** i biblioteket så du
  ikke kommer til at vælge samme sang to gange
- **Auto-gem** efter hver ændring — du kan aldrig miste noget

### 📝 4 separate noter pr. sang
Hver sang kan have noter til **4 afdelinger** — så I kan skille tekniske
beskeder ad og kun vise det der er relevant for hver person:

- 🔊 **Lyd** — fx *"mere reverb"*, *"sangstemme op i omkvæd"*
- 💡 **Lys** — fx *"blå farve"*, *"strobe på solo"*
- 🎬 **Video** — fx *"zoom på guitar-solo"*, *"sort skærm i intro"*
- 🎸 **Band** — fx *"capo 3"*, *"spil softere på outro"*

Toggle-knapper over setlisten lader dig vælge hvilke kategorier vises —
så lyd-manden ikke skal se band-noter og omvendt.

### 🌐 Importér sange fra internet
Skriv et bandnavn (fx *"D-A-D"*), vælg det rigtige band fra MusicBrainz,
kryds sange af og importér. Sparer dig for at skrive 50 sange ind manuelt.

### 🔍 Søg
Søg i biblioteket eller på tværs af alle dine bands. Søger også i noterne.

### 🖨️ Print som A4
Print-dialog med **live forhåndsvisning** hvor du vælger:
- Hvilke kolonner der skal med (nummer, toneart, længde, …)
- **Hvilke noter-kategorier** der skal trykkes (default: kun band-noter)
- Tekststørrelse i 5 trin (Mini · Lille · Mellem · Stor · Maxi)
- Om bandets logo skal vises i øverste højre hjørne
- Om titel, dato, kolonneoverskrifter og markører skal med
- *"Alt til" / "Alt fra"*-knapper for hurtige valg

### 🖼️ Logo pr. band
Vælg et billede (PNG/JPG/GIF/BMP/WebP). Det vises automatisk på det
printede ark og gemmes inde i selve filen — ingen eksterne filer at
holde styr på.

### 📱 Telefon/iPad-visning på scenen
Når appen kører viser den automatisk en URL som hele bandet kan åbne på
deres telefon/iPad på samme WiFi:

- **Kun setliste** — rene sangtitler, godt overblik
- **Setliste med noter** — store kort med nuværende + næste sang,
  hver noter-kategori kan slås til/fra individuelt på hver enhed

Skifter du sang på master-PC'en opdateres alle enheder med det samme.

### 🎛️ Stream Deck / Bitfocus Companion
Naviger setlisten fra en Stream Deck under koncerten via simple
HTTP-kald:

| URL | Hvad |
|---|---|
| `http://<din-pc>:8765/api/next` | Næste sang |
| `http://<din-pc>:8765/api/prev` | Forrige sang |
| `http://<din-pc>:8765/api/goto/5` | Hop til sang #5 |
| `http://<din-pc>:8765/api/current` | Hent nuværende sang som JSON |

### 📺 Stage Mode (fullscreen)
Et stort fullscreen-vindue til at vise på en sekundær skærm bag bandet
eller på en monitor. Viser nuværende + næste sang i kæmpe skrift, med
alle 4 noter-kategorier som farvede tape-strips.

### 📡 NDI broadcast (Windows)
Hvis du har en video-mixer der understøtter NDI (OBS, vMix, ATEM osv.)
kan appen sende setliste-grafik direkte ind som en NDI source —
ingen capture-kort nødvendig.

### 🔄 Auto-update
Programmet tjekker selv (max én gang i døgnet) om der er en nyere
version. Hvis ja vises en dialog med en knap til at hente
opdateringen. Kan også tjekkes manuelt fra menuen
*Hjælp → Søg efter opdateringer…*

---

Sådan installerer du
--------------------

1. Hent [**SetlistManagerSetup.exe**](https://github.com/mun-ken/setlist-manager/releases/latest)
2. Dobbeltklik den
3. Klik *Næste* → *Installér* → *Færdig*
4. Åbn **Setlist Manager** fra Start-menuen eller skrivebordet

Det er det. Python og alle afhængigheder er pakket ind i installeren.

Første gang du åbner appen får du et lille eksempel-bibliotek så du kan
se hvordan tingene virker. Det auto-gemmes og du kan trygt slette det
når du selv lægger sange ind.

> 💡 **Windows Defender / SmartScreen advarer?** Højreklik filen →
> *Egenskaber* → sæt flueben i *Fjern blokering*. Det sker fordi
> installeren ikke er kode-signeret (det koster penge). Den er
> sikker — bygget automatisk af GitHub fra den åbne kildekode i
> dette repo.

---

Tastatur-genveje
----------------

I hovedvinduet:

| Genvej | Hvad |
|---|---|
| `Ctrl+S` | Gem som… |
| `Ctrl+O` | Åbn… |
| `Ctrl+P` | Print A4… |
| `Ctrl+F` | Søg i biblioteket |

I Stage Mode:

| Tast | Hvad |
|---|---|
| `→` · `Mellemrum` · klik | Næste sang |
| `←` · højre-klik | Forrige sang |
| `1` – `9` | Hop direkte til sang #1-9 |
| `F` | Fullscreen til/fra |
| `Esc` | Luk Stage Mode |

---

Hvor gemmes mine data?
----------------------

Auto-gem ligger i:
- **Windows**: `%APPDATA%\SetlistManager\autosave.json`
- **macOS / Linux**: `~/.setlist_manager/autosave.json`

Brug *Gem som…* hvis du vil lægge en kopi i Dropbox/OneDrive så hele
bandet kan dele setlisten.

---

For udviklere
-------------

Vil du bygge installeren selv eller bidrage til koden? Se
[`RELEASE_GUIDE.md`](RELEASE_GUIDE.md) for en komplet build-vejledning.

Kildekoden er på dansk og dækket af 157 enhedstests:

```bash
python3 test_save_load.py
```
