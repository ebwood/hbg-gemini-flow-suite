# Contributing

Thanks for helping keep HBG Gemini Flow Suite useful as Gemini Web and Flow evolve.

## Development workflow

1. Fork the repository and create a focused branch.
2. Keep real Google authorization outside the repository.
3. Run the local checks:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q suite_cli.py media_cleanup.py sync_auth.py sitecustomize.py
sh -n suite start-desktop.sh
python3 scripts/check_secrets.py
NOVNC_PASSWORD=local-test docker compose --env-file .env.example config --quiet
```

4. If a change touches browser automation, describe the tested Flow UI mode, locale and date.
5. If a change touches generated media, report dimensions, duration, codecs and visual QA.

## Pull request rules

- Never commit `.env`, cookies, Chrome profiles, Docker volume exports or generated account data.
- Avoid selectors that depend only on translated visible text; prefer stable attributes or Material Symbols identifiers.
- Preserve older selectors when adding support for a new Flow UI cohort.
- Do not weaken localhost-only port bindings.
- Add or update tests for deterministic Python or shell behavior.
- Explain third-party license changes when adding a dependency.
