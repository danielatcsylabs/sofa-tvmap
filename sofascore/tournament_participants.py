import argparse
import asyncio
import json
import random
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

if __package__ is None or __package__ == "":
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from sofascore.competitions import fetch_competitions_for_sports
else:  # pragma: no cover - executed when run as module
    from .competitions import fetch_competitions_for_sports

from sofascore_wrapper.api import SofascoreAPI

DEFAULT_SPORTS = [
    "football",
]
DEFAULT_COMPETITIONS_FILE = Path("data/competitions.json")
DEFAULT_OUTPUT_FILE = Path("data/tournaments_participants.json")
DEFAULT_REQUEST_DELAY = 0.25
DEFAULT_REQUEST_JITTER = 0.0
DEFAULT_RETRY_DELAY = 3.0
DEFAULT_MAX_RETRIES = 4
DEFAULT_RETRY_STATUSES = (403, 429, 430, 500, 502, 503)
DEFAULT_TOURNAMENT_JITTER = 0.0

def _extract_status_code(exc: Exception) -> Optional[int]:
    message = str(exc)
    if ":" not in message:
        return None
    tail = message.rsplit(":", 1)[-1].strip()
    return int(tail) if tail.isdigit() else None


async def _sleep_with_jitter(base_delay: float, jitter: float) -> None:
    if base_delay <= 0 and jitter <= 0:
        return
    extra = random.random() * jitter if jitter > 0 else 0.0
    delay = base_delay + extra
    if delay > 0:
        await asyncio.sleep(delay)


async def fetch_with_retry(
    api: SofascoreAPI,
    endpoint: str,
    *,
    request_delay: float,
    request_jitter: float,
    max_retries: int,
    retry_delay: float,
    retry_statuses: Iterable[int],
) -> Dict[str, Any]:
    attempt = 0
    retry_codes = set(int(code) for code in retry_statuses)

    while True:
        await _sleep_with_jitter(request_delay, request_jitter)

        try:
            return await api._get(endpoint)
        except Exception as exc:  # noqa: BLE001
            status = _extract_status_code(exc)
            attempt += 1

            can_retry = (
                status is not None
                and status in retry_codes
                and attempt <= max_retries
            )

            if can_retry:
                wait_time = retry_delay * (2 ** (attempt - 1))
                print(
                    f"↻ {endpoint} failed with {status}. "
                    f"Retry {attempt}/{max_retries} in {wait_time:.1f}s"
                )
                await asyncio.sleep(wait_time)
                continue

            raise


def simplify_team(team: Dict[str, Any]) -> Dict[str, Any]:
    country = team.get("country") or {}
    return {
        "id": team.get("id"),
        "name": team.get("name"),
        "slug": team.get("slug"),
        "shortName": team.get("shortName"),
        "gender": team.get("gender"),
        "type": team.get("type"),
        "country": {
            "alpha2": country.get("alpha2"),
            "alpha3": country.get("alpha3"),
            "name": country.get("name"),
        }
        if country
        else None,
    }


async def load_competitions(
    path: Optional[Path], sports: Iterable[str]
) -> List[Dict[str, Any]]:
    sports_list = list(sports)
    if path and path.exists():
        competitions = json.loads(path.read_text(encoding="utf-8"))
        if sports_list:
            sports_set = set(sports_list)
            competitions = [
                comp
                for comp in competitions
                if comp.get("sportSlug", "football") in sports_set
            ]
        return competitions

    return await fetch_competitions_for_sports(sports_list)


def _has_valid_team_data(snapshot: Dict[str, Any]) -> bool:
    team_sets = snapshot.get("teamSets", [])
    for team_set in team_sets:
        teams = team_set.get("teams")
        if isinstance(teams, list):
            return True
    return False


def _load_existing_index(path: Optional[Path]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    if not path or not path.exists():
        return {}

    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}

    index: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for sport, snapshots in existing.items():
        bucket: Dict[str, Dict[str, Any]] = {}
        if not isinstance(snapshots, list):
            continue
        for snapshot in snapshots:
            metadata = snapshot.get("metadata", {})
            tournament_id = metadata.get("tournamentId")
            if tournament_id is None:
                continue
            bucket[str(tournament_id)] = snapshot
        if bucket:
            index[sport] = bucket
    return index


def _materialize_dataset(
    index: Dict[str, Dict[str, Dict[str, Any]]],
    competitions: List[Dict[str, Any]]
) -> Dict[str, List[Dict[str, Any]]]:
    ordered: Dict[str, List[Dict[str, Any]]] = {}
    seen: set[Tuple[str, str]] = set()

    for competition in competitions:
        sport = competition.get("sportSlug", "unknown")
        tournament_id = competition.get("tournamentId")
        if tournament_id is None:
            continue
        key = str(tournament_id)
        snapshot = index.get(sport, {}).get(key)
        if snapshot is None:
            continue
        ordered.setdefault(sport, []).append(snapshot)
        seen.add((sport, key))

    for sport, snapshots in index.items():
        for key, snapshot in snapshots.items():
            if (sport, key) not in seen:
                ordered.setdefault(sport, []).append(snapshot)

    return ordered


async def collect_participants(
    api: SofascoreAPI,
    competition: Dict[str, Any],
    *,
    all_seasons: bool,
    season_limit: Optional[int],
    request_delay: float,
    request_jitter: float,
    max_retries: int,
    retry_delay: float,
    retry_statuses: Iterable[int],
) -> Dict[str, Any]:
    tournament_id = competition.get("tournamentId")

    result: Dict[str, Any] = {
        "metadata": competition,
        "seasons": [],
        "teamSets": [],
    }

    try:
        seasons_payload = await fetch_with_retry(
            api,
            f"/unique-tournament/{tournament_id}/seasons",
            request_delay=request_delay,
            request_jitter=request_jitter,
            max_retries=max_retries,
            retry_delay=retry_delay,
            retry_statuses=retry_statuses,
        )
    except Exception as exc:  # noqa: BLE001
        result["error"] = {"error": str(exc)}
        return result

    seasons: List[Dict[str, Any]] = seasons_payload or []
    result["seasons"] = seasons

    if not seasons:
        return result

    selected_seasons = seasons if all_seasons else seasons[:1]
    if season_limit is not None:
        selected_seasons = selected_seasons[:season_limit]

    for season in selected_seasons:
        season_id = season.get("id")
        if season_id is None:
            continue

        try:
            teams_payload = await fetch_with_retry(
                api,
                f"/unique-tournament/{tournament_id}/season/{season_id}/teams",
                request_delay=request_delay,
                request_jitter=request_jitter,
                max_retries=max_retries,
                retry_delay=retry_delay,
                retry_statuses=retry_statuses,
            )
        except Exception as exc:  # noqa: BLE001
            result["teamSets"].append(
                {
                    "seasonId": season_id,
                    "season": season,
                    "error": {"error": str(exc)},
                }
            )
            continue

        teams = [simplify_team(team) for team in teams_payload.get("teams", [])]
        result["teamSets"].append(
            {
                "seasonId": season_id,
                "season": season,
                "teams": teams,
            }
        )

    return result


async def build_dataset(
    competitions: Iterable[Dict[str, Any]],
    *,
    all_seasons: bool,
    season_limit: Optional[int],
    request_delay: float,
    request_jitter: float,
    tournament_delay: float,
    tournament_jitter: float,
    max_retries: int,
    retry_delay: float,
    retry_statuses: Iterable[int],
    existing_index: Dict[str, Dict[str, Dict[str, Any]]],
    force: bool,
) -> Dict[str, List[Dict[str, Any]]]:
    api = SofascoreAPI()
    results_index: Dict[str, Dict[str, Dict[str, Any]]] = {
        sport: dict(snapshots) for sport, snapshots in existing_index.items()
    }

    try:
        competitions_list = list(competitions)
        total = len(competitions_list)

        for index, competition in enumerate(competitions_list, start=1):
            sport = competition.get("sportSlug", "unknown")
            tournament_id = competition.get("tournamentId")
            name = competition.get("tournamentName", str(tournament_id))
            category = competition.get("categoryName", "?")
            tournament_key = str(tournament_id)
            existing_snapshot = (
                results_index.get(sport, {}).get(tournament_key)
            )

            if (
                not force
                and existing_snapshot
                and _has_valid_team_data(existing_snapshot)
            ):
                print(
                    f"[cached] {sport} | {category} – {name} ({tournament_id})"
                )
                continue

            print(
                f"[{index}/{total}] {sport} | {category} – {name} ({tournament_id})"
            )

            await _sleep_with_jitter(tournament_delay, tournament_jitter)

            snapshot = await collect_participants(
                api,
                competition,
                all_seasons=all_seasons,
                season_limit=season_limit,
                request_delay=request_delay,
                request_jitter=request_jitter,
                max_retries=max_retries,
                retry_delay=retry_delay,
                retry_statuses=retry_statuses,
            )

            results_index.setdefault(sport, {})[tournament_key] = snapshot
    finally:
        await api.close()

    return _materialize_dataset(results_index, competitions_list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch SofaScore tournament participants without heavy extras."
    )
    parser.add_argument(
        "--sport",
        dest="sports",
        action="append",
        help="SofaScore sport slug to harvest. Repeat flag for multiple (default: football).",
    )
    parser.add_argument(
        "--competitions",
        type=Path,
        default=DEFAULT_COMPETITIONS_FILE,
        help=(
            "Path to existing competitions JSON. If missing, competitions are fetched "
            "using the provided sports."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT_FILE,
        help="Where to store the aggregated tournament+team dataset.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Pretty-print indent for the output JSON (default: 2).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of tournaments processed (useful for testing).",
    )
    parser.add_argument(
        "--all-seasons",
        action="store_true",
        help="Collect team lists for every available season (default: only the first season).",
    )
    parser.add_argument(
        "--season-limit",
        type=int,
        default=None,
        help="Clamp the number of seasons harvested per tournament (applied after --all-seasons).",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=DEFAULT_REQUEST_DELAY,
        help=(
            "Seconds to wait before each SofaScore request (default: "
            f"{DEFAULT_REQUEST_DELAY})."
        ),
    )
    parser.add_argument(
        "--tournament-delay",
        type=float,
        default=0.0,
        help="Optional pause in seconds between tournaments (default: 0).",
    )
    parser.add_argument(
        "--request-jitter",
        type=float,
        default=DEFAULT_REQUEST_JITTER,
        help="Random jitter added to each request delay (seconds, default: 0).",
    )
    parser.add_argument(
        "--tournament-jitter",
        type=float,
        default=DEFAULT_TOURNAMENT_JITTER,
        help="Random jitter added to each tournament delay (seconds, default: 0).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help="Maximum retries when SofaScore returns retryable status codes.",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=DEFAULT_RETRY_DELAY,
        help=(
            "Base delay (seconds) for retry backoff. Doubles with each attempt "
            f"(default: {DEFAULT_RETRY_DELAY})."
        ),
    )
    parser.add_argument(
        "--retry-status",
        dest="retry_status",
        action="append",
        type=int,
        help=(
            "HTTP status codes that trigger a retry. Repeat flag to add more. "
            f"Defaults: {', '.join(map(str, DEFAULT_RETRY_STATUSES))}."
        ),
    )
    parser.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="Optional existing participants JSON to reuse cached team lists.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch tournaments even when cached data already has teams.",
    )
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()

    sports = args.sports or DEFAULT_SPORTS
    competitions = await load_competitions(args.competitions, sports)
    if args.limit is not None:
        competitions = competitions[: args.limit]

    existing_index = _load_existing_index(args.resume or args.out)

    dataset = await build_dataset(
        competitions,
        all_seasons=args.all_seasons,
        season_limit=args.season_limit,
        request_delay=args.request_delay,
        request_jitter=args.request_jitter,
        tournament_delay=args.tournament_delay,
        tournament_jitter=args.tournament_jitter,
        max_retries=args.max_retries,
        retry_delay=args.retry_delay,
        retry_statuses=args.retry_status or DEFAULT_RETRY_STATUSES,
        existing_index=existing_index,
        force=args.force,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dataset, indent=args.indent), encoding="utf-8")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
