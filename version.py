"""Single source of truth for app version + opdaterings-URL.

Når du udgiver en ny version:
  1. Bump APP_VERSION her (følg semantic versioning: MAJOR.MINOR.PATCH)
  2. Commit + push
  3. Lav et git tag der matcher: ``git tag v1.2.0 && git push --tags``
  4. GitHub Actions bygger automatisk installeren og opretter en Release
  5. Brugere får besked om opdateringen næste gang de starter programmet

Hvis du forker projektet, så ret GITHUB_OWNER til dit GitHub-brugernavn
(og evt. GITHUB_REPO hvis du omdøber repoet).
"""

APP_VERSION = "1.4.5"

# GitHub repo som opdaterings-tjekket henter Releases fra.
# Skift til dit eget brugernavn/repo hvis du forker.
GITHUB_OWNER = "mun-ken"
GITHUB_REPO = "setlist-manager"
