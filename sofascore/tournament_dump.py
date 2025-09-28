import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

if __package__ is None or __package__ == "":
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from sofascore.competitions import fetch_competitions_for_sports
else:  # pragma: no cover - handled when executed as module
    from .competitions import fetch_competitions_for_sports

from sofascore_wrapper.api import SofascoreAPI
from sofascore_wrapper.league import League

DEFAULT_SPORTS = ["football"]
DEFAULT_COMPETITIONS_FILE = Path("data/competitions.json")
DEFAULT_OUTPUT_FILE = Path("data/tournaments_full.json")

LEAGUE_CALLS = {
    "overview": League.get_league,
    "currentSeason": League.current_season,
    "latestHighlights": League.get_latest_highlights,
    "featuredGames": League.featured_games,
    "nextFixtures": League.next_fixtures,
    "lastFixtures": League.last_fixtures,
}

SEASON_CALLS = {
    "info": League.get_info,
    "topPlayersPerGame": League.top_players_per_game,
    "topPlayers": League.top_players,
    "topTeams": League.top_teams,
    "standings": League.standings,
    "standingsHome": League.standings_home,
    "standingsAway": League.standings_away,
    "playerOfSeason": League.player_of_the_season,
    "rounds": League.rounds,
    "currentRound": League.current_round,
    "cupTree": League.cup_tree,
}


async def safe_call(fn, *args) -> Any:
    """Execute an async SofaScore call and capture failures as error payloads."""
    try:
        return await fn(*args)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


async def load_competitions(
    path: Optional[Path], sports: Iterable[str]
) -> List[Dict[str, Any]]:
    sports_list = list(sports)
    sports_set = set(sports_list)

    if path and path.exists():
        competitions = json.loads(path.read_text(encoding="utf-8"))

        # Backfill sport slug when legacy dumps (e.g., football-only) omit it.
        if len(sports_set) == 1:
            fallback_sport = next(iter(sports_set))
        else:
            fallback_sport = None

        for competition in competitions:
            if "sportSlug" not in competition and fallback_sport:
                competition["sportSlug"] = fallback_sport

        if sports_set:
            competitions = [
                comp
                for comp in competitions
                if comp.get("sportSlug") in sports_set or not comp.get("sportSlug")
            ]

        return competitions

    return await fetch_competitions_for_sports(sports_list)


def resolve_seasons(
    seasons: List[Dict[str, Any]],
    *,
    all_seasons: bool,
    season_limit: Optional[int],
) -> List[Tuple[int, Dict[str, Any]]]:
    resolved: List[Tuple[int, Dict[str, Any]]] = []
    for season in seasons:
        season_id = season.get("id")
        if season_id is None:
            continue
        resolved.append((season_id, season))
        if not all_seasons:
            break

    if season_limit is not None:
        resolved = resolved[:season_limit]

    return resolved


async def collect_tournament_snapshot(
    api: SofascoreAPI,
    competition: Dict[str, Any],
    *,
    all_seasons: bool,
    season_limit: Optional[int],
) -> Dict[str, Any]:
    tournament_id = competition.get("tournamentId")
    league = League(api, tournament_id)

    snapshot: Dict[str, Any] = {
        "metadata": competition,
        "league": {},
        "seasons": [],
        "seasonDetails": [],
    }

    for name, fn in LEAGUE_CALLS.items():
        snapshot["league"][name] = await safe_call(fn, league)

    seasons_payload = await safe_call(League.get_seasons, league)
    if isinstance(seasons_payload, dict) and "error" in seasons_payload:
        snapshot["seasonsError"] = seasons_payload
        return snapshot

    seasons: List[Dict[str, Any]] = seasons_payload or []
    snapshot["seasons"] = seasons

    chosen_seasons = resolve_seasons(
        seasons, all_seasons=all_seasons, season_limit=season_limit
    )

    for season_id, season_meta in chosen_seasons:
        season_block: Dict[str, Any] = {
            "seasonId": season_id,
            "season": season_meta,
        }

        for name, fn in SEASON_CALLS.items():
            season_block[name] = await safe_call(fn, league, season_id)

        snapshot["seasonDetails"].append(season_block)

    return snapshot


async def build_dataset(
    competitions: Iterable[Dict[str, Any]],
    *,
    all_seasons: bool,
    season_limit: Optional[int],
) -> Dict[str, Dict[str, Any]]:
    api = SofascoreAPI()
    dataset: Dict[str, Dict[str, Any]] = {}

    try:
        competitions_list = list(competitions)
        total = len(competitions_list)
        for index, competition in enumerate(competitions_list, start=1):
            sport = competition.get("sportSlug", "unknown")
            tournament_id = competition.get("tournamentId")
            name = competition.get("tournamentName", str(tournament_id))
            category = competition.get("categoryName", "?")
            print(
                f"[{index}/{total}] {sport} | {category} – {name} ({tournament_id})"
            )

            sport_bucket = dataset.setdefault(sport, {})
            sport_bucket[str(tournament_id)] = await collect_tournament_snapshot(
                api,
                competition,
                all_seasons=all_seasons,
                season_limit=season_limit,
            )
    finally:
        await api.close()

    return dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch detailed SofaScore data for tournaments across sports."
    )
    parser.add_argument(
        "--sport",
        dest="sports",
        action="append",
        help="SofaScore sport slug to harvest. Repeat flag to include multiple (default: football).",
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
        help="Where to store the aggregated tournament dataset.",
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
        help="Collect data for every available season (default: only the first season).",
    )
    parser.add_argument(
        "--season-limit",
        type=int,
        default=None,
        help="Clamp the number of seasons harvested per tournament (applied after --all-seasons).",
    )
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()

    sports = list(args.sports or DEFAULT_SPORTS)
    competitions = await load_competitions(args.competitions, sports)
    if args.limit is not None:
        competitions = competitions[: args.limit]

    dataset = await build_dataset(
        competitions,
        all_seasons=args.all_seasons,
        season_limit=args.season_limit,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dataset, indent=args.indent), encoding="utf-8")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
