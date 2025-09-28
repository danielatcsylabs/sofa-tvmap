# RapidAPI Tooling

Utility scripts for working with the sportapi7 endpoints on RapidAPI. These
scripts supplement the direct SofaScore scrapers by using the paid API for
endpoints that frequently return `403` under heavy load.

## Prerequisites

- Node.js 18+ (this repository currently uses Node 24)
- RapidAPI key with access to [sportapi7](https://rapidapi.com/rapidsportapi/api/sportapi7)
- `RAPIDAPI_KEY` environment variable set, or pass `--key` when invoking scripts

## `fetchCompetitions.mjs`

Enriches the existing competition catalog with additional metadata such as
`gender`, brand colors, and tournament flags sourced from the
`/unique-tournament/{id}` endpoint.

Example:

```bash
node rapidapi/fetchCompetitions.mjs \
  --input data/competitions.json \
  --out data/competitions_enriched.json \
  --sports football basketball tennis \
  --concurrency 6 --delay 0.3 --jitter 0.2
```

Flags:

- `--sports` filters the workload to the supplied sport slugs. Omit to process all entries.
- `--concurrency`, `--delay`, and `--jitter` control client-side throttling so you can stay well under RapidAPI’s 50 req/s cap.
- Errors are written to `<output>.errors.json` for follow-up retries.

The enriched output conforms to `schema/competitions.schema.json`.
