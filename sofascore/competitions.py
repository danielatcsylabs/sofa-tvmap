import argparse
import asyncio
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from sofascore_wrapper.api import SofascoreAPI
from sofascore_wrapper.league import League

DEFAULT_SPORT = "football"


async def fetch_competitions(sport_slug: str) -> List[Dict[str, object]]:
    """Fetch every competition (unique tournament) for a given SofaScore sport."""
    api = SofascoreAPI()
    league_client = League(api, 0)
    competitions: List[Dict[str, object]] = []

    try:
        categories_payload = await api._get(f"/sport/{sport_slug}/categories")
        categories = categories_payload.get("categories", [])

        for category in categories:
            category_id = category.get("id")
            if category_id is None:
                continue

            tournaments_payload = await league_client.leagues(category_id)
            groups = list(tournaments_payload.get("groups", []))

            # Some responses hold tournaments directly instead of inside groups
            if tournaments_payload.get("uniqueTournaments"):
                groups.append({"uniqueTournaments": tournaments_payload["uniqueTournaments"]})

            for group in groups:
                for tournament in group.get("uniqueTournaments", []):
                    competitions.append(
                        {
                            "sportSlug": sport_slug,
                            "categoryId": category_id,
                            "categoryName": category.get("name"),
                            "categorySlug": category.get("slug"),
                            "categoryAlpha2": category.get("alpha2"),
                            "tournamentId": tournament.get("id"),
                            "tournamentName": tournament.get("name"),
                            "tournamentSlug": tournament.get("slug"),
                            "priority": tournament.get("priority"),
                        }
                    )
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ Failed to fetch competitions for {sport_slug}: {exc}")
    finally:
        await api.close()

    return competitions


async def fetch_soccer_competitions() -> List[Dict[str, object]]:
    """Backward-compatible helper returning football competitions only."""
    return await fetch_competitions(DEFAULT_SPORT)


async def fetch_competitions_for_sports(sports: Iterable[str]) -> List[Dict[str, object]]:
    competitions: List[Dict[str, object]] = []
    for sport in sports:
        competitions.extend(await fetch_competitions(sport))
    return competitions


def _serialize(data: List[Dict[str, object]], output_path: Optional[Path], indent: int) -> None:
    serialized = json.dumps(data, indent=indent)
    if output_path:
        output_path.write_text(serialized, encoding="utf-8")
    else:
        print(serialized)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch SofaScore competitions for one or more sports."
    )
    parser.add_argument(
        "--sport",
        dest="sports",
        action="append",
        help="SofaScore sport slug. Repeat flag for multiple sports (default: football).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional path to save the competitions JSON. Defaults to stdout.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Pretty-print indent for JSON output (default: 2).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sports = args.sports or [DEFAULT_SPORT]
    data = asyncio.run(fetch_competitions_for_sports(sports))
    _serialize(data, args.out, args.indent)


if __name__ == "__main__":
    main()
