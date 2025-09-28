#!/usr/bin/env node
// Fetch enriched competition metadata from RapidAPI's sportapi7 endpoints.
// Usage example:
//   node rapidapi/fetchCompetitions.mjs --input data/competitions.json --out data/competitions_enriched.json \
//     --sports football basketball --concurrency 6 --delay 0.25

import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const BASE_URL = 'https://sportapi7.p.rapidapi.com/api/v1';
const DEFAULT_INPUT = 'data/competitions.json';
const DEFAULT_OUTPUT = 'data/competitions_enriched.json';
const DEFAULT_CONCURRENCY = 6;
const DEFAULT_DELAY = 0.25; // seconds
const DEFAULT_JITTER = 0.15; // seconds
const RAPIDAPI_HOST = 'sportapi7.p.rapidapi.com';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function parseArgs(argv) {
  const args = {
    input: DEFAULT_INPUT,
    out: DEFAULT_OUTPUT,
    sports: [],
    concurrency: DEFAULT_CONCURRENCY,
    delay: DEFAULT_DELAY,
    jitter: DEFAULT_JITTER,
    key: process.env.RAPIDAPI_KEY || '',
  };

  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--input' && argv[i + 1]) {
      args.input = argv[++i];
    } else if (arg === '--out' && argv[i + 1]) {
      args.out = argv[++i];
    } else if (arg === '--sports') {
      args.sports = [];
      while (argv[i + 1] && !argv[i + 1].startsWith('--')) {
        args.sports.push(argv[++i]);
      }
    } else if ((arg === '--concurrency' || arg === '-c') && argv[i + 1]) {
      args.concurrency = Number(argv[++i]);
    } else if (arg === '--delay' && argv[i + 1]) {
      args.delay = Number(argv[++i]);
    } else if (arg === '--jitter' && argv[i + 1]) {
      args.jitter = Number(argv[++i]);
    } else if (arg === '--key' && argv[i + 1]) {
      args.key = argv[++i];
    } else if (arg === '--help' || arg === '-h') {
      printHelp();
      process.exit(0);
    } else {
      console.warn(`Ignoring unknown argument: ${arg}`);
    }
  }

  if (!args.key) {
    throw new Error('RapidAPI key is required (set RAPIDAPI_KEY env var or pass --key).');
  }

  return args;
}

function printHelp() {
  console.log(`Usage: node rapidapi/fetchCompetitions.mjs [options]\n\n` +
    `Options:\n` +
    `  --input <path>        Source competitions JSON (default: ${DEFAULT_INPUT})\n` +
    `  --out <path>          Destination file for enriched competitions (default: ${DEFAULT_OUTPUT})\n` +
    `  --sports <list>       Optional sport slug filter (space-separated)\n` +
    `  --concurrency <int>   Parallel requests (default: ${DEFAULT_CONCURRENCY})\n` +
    `  --delay <seconds>     Base delay between requests per worker (default: ${DEFAULT_DELAY})\n` +
    `  --jitter <seconds>    Additional random delay (default: ${DEFAULT_JITTER})\n` +
    `  --key <value>         RapidAPI key (overrides RAPIDAPI_KEY env)\n` +
    `  -h, --help            Show this message\n`);
}

async function loadCompetitions(filePath, sportsFilter) {
  const data = await fs.readFile(filePath, 'utf-8');
  const competitions = JSON.parse(data);
  if (!Array.isArray(competitions)) {
    throw new Error(`Expected array in ${filePath}`);
  }
  if (!sportsFilter || sportsFilter.length === 0) {
    return competitions;
  }
  const set = new Set(sportsFilter);
  return competitions.filter((item) => set.has(item.sportSlug));
}

async function fetchJson(endpoint, key) {
  const response = await fetch(`${BASE_URL}${endpoint}`, {
    headers: {
      'X-RapidAPI-Key': key,
      'X-RapidAPI-Host': RAPIDAPI_HOST,
    },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`HTTP ${response.status} for ${endpoint}: ${body.slice(0, 200)}`);
  }
  return response.json();
}

const GENDER_MAP = {
  M: 'men',
  F: 'women',
  X: 'mixed',
};

function normalizeGender(raw) {
  if (!raw) return 'men';
  const upper = String(raw).toUpperCase();
  return GENDER_MAP[upper] || 'men';
}

function buildLogoUrl(tournamentId, variant = '') {
  if (!tournamentId) return null;
  const suffix = variant ? `/${variant}` : '';
  return `https://api.sofascore.com/api/v1/unique-tournament/${tournamentId}/image${suffix}`;
}

function mapTournamentPayload(base, payload) {
  const ut = payload?.uniqueTournament ?? {};
  const category = ut.category ?? {};
  const country = ut.country ?? category.country ?? null;

  return {
    ...base,
    genderRaw: ut.gender ?? null,
    gender: normalizeGender(ut.gender),
    tier: ut.tier ?? null,
    hasGroups: ut.hasGroups ?? null,
    hasPlayoffSeries: ut.hasPlayoffSeries ?? null,
    hasRounds: ut.hasRounds ?? null,
    startDateTimestamp: ut.startDateTimestamp ?? null,
    endDateTimestamp: ut.endDateTimestamp ?? null,
    displayInverseHomeAwayTeams: ut.displayInverseHomeAwayTeams ?? null,
    primaryColorHex: ut.primaryColorHex ?? null,
    secondaryColorHex: ut.secondaryColorHex ?? null,
    logo: ut.logo ?? null,
    logoUrl: ut.logo ? buildLogoUrl(ut.id || base.tournamentId) : null,
    darkLogo: ut.darkLogo ?? null,
    darkLogoUrl: ut.darkLogo ? buildLogoUrl(ut.id || base.tournamentId, 'dark') : null,
    country: country
      ? {
          alpha2: country.alpha2 ?? null,
          alpha3: country.alpha3 ?? null,
          name: country.name ?? null,
        }
      : null,
  };
}

async function delay(seconds) {
  if (!seconds || seconds <= 0) return;
  await new Promise((resolve) => setTimeout(resolve, seconds * 1000));
}

async function runWorker(queue, nextIndex, workerId, options, key, results, errors) {
  while (true) {
    const idx = nextIndex.value;
    if (idx >= queue.length) {
      return;
    }
    nextIndex.value += 1;

    const { competition, endpoint } = queue[idx];
    try {
      const jitter = Math.random() * options.jitter;
      await delay(options.delay + jitter);
      const payload = await fetchJson(endpoint, key);
      const enriched = mapTournamentPayload(competition, payload);
      results[idx] = enriched;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      errors.push({ competition, endpoint, message });
      results[idx] = { ...competition, fetchError: message };
      console.error(`Worker ${workerId} failed for ${competition.tournamentId}: ${message}`);
    }
  }
}

async function main() {
  const args = parseArgs(process.argv);
  const inputPath = path.resolve(__dirname, '..', args.input);
  const outputPath = path.resolve(__dirname, '..', args.out);

  const competitions = await loadCompetitions(inputPath, args.sports);
  console.log(`Loaded ${competitions.length} competitions from ${args.input}`);

  const queue = competitions.map((competition) => ({
    competition,
    endpoint: `/unique-tournament/${competition.tournamentId}`,
  }));

  const results = new Array(queue.length);
  const errors = [];
  const nextIndex = { value: 0 };

  const workers = Array.from({ length: Math.max(1, args.concurrency) }, (_, idx) =>
    runWorker(queue, nextIndex, idx + 1, args, args.key, results, errors)
  );

  await Promise.all(workers);

  console.log(`Fetched ${results.length} tournaments, ${errors.length} failures.`);

  const successful = results.filter((entry) => entry && !entry.fetchError);
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, JSON.stringify(successful, null, 2));
  console.log(`Saved enriched competitions to ${args.out}`);

  if (errors.length > 0) {
    const errorPath = `${outputPath}.errors.json`;
    await fs.writeFile(errorPath, JSON.stringify(errors, null, 2));
    console.warn(`Captured ${errors.length} errors in ${errorPath}`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
