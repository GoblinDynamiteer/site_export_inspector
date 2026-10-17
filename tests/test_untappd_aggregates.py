from __future__ import annotations

import ast
from pathlib import Path

import pytest

from export_inspector import untappd
from export_inspector.untappd import aggregates, details


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def entries() -> list[dict]:
    return untappd.load_export(FIXTURES / "untappd" / "checkins_multi.json")


def by_id(entries: list[dict], checkin_id: int) -> dict:
    return next(entry for entry in entries if entry["checkin_id"] == checkin_id)


def test_keys_prefer_ids_and_fall_back_to_names(entries) -> None:
    assert aggregates.beer_key(by_id(entries, 101)) == "bid:11"
    assert aggregates.beer_key(by_id(entries, 104)) == "name:demo brewing co.|mock lager"
    assert aggregates.brewery_key(by_id(entries, 101)) == "brewery:501"
    assert aggregates.brewery_key(by_id(entries, 105)) == "name:|fixture ales"
    assert aggregates.venue_key(by_id(entries, 101)) == "venue:sweden|stockholm|example taproom"
    assert aggregates.venue_key(by_id(entries, 103)) == "venue:||example bottle shop"
    assert aggregates.venue_key(by_id(entries, 104)) == ""
    assert aggregates.entry_key(by_id(entries, 101)) == "checkin:101"
    assert aggregates.entry_key({"created_at": "2022-01-01 10:00:00", "bid": 7}) == (
        "fallback:bid:7|2022-01-01 10:00:00"
    )


def test_had_counts_number_checkins_oldest_first(entries) -> None:
    had = aggregates.HadCounts.from_entries(list(reversed(entries)))
    assert [had.checkin_index(by_id(entries, cid)) for cid in (101, 102, 103, 104, 105)] == [
        1,
        2,
        3,
        4,
        5,
    ]
    assert had.had_index(by_id(entries, 101)) == 1
    assert had.had_index(by_id(entries, 102)) == 2
    assert had.had_count(by_id(entries, 101)) == 2
    assert had.had_count(by_id(entries, 103)) == 1
    # A copied dict (as Qt item data may hand back) resolves by key, not identity.
    assert had.had_index(dict(by_id(entries, 102))) == 2
    assert aggregates.HadCounts().checkin_index(by_id(entries, 101)) == 0


def test_beer_groups(entries) -> None:
    groups = aggregates.build_beer_groups(entries)
    assert [group["beer"] for group in groups] == [
        "Example Sour",
        "Mock Lager",
        "Test Stout",
        "Sample Pale Ale",
    ]
    pale = groups[-1]
    assert [entry["checkin_id"] for entry in pale["entries"]] == [101, 102]
    assert pale["ratings"] == [4.0, 3.75]
    assert pale["first_dt"].strftime("%Y-%m-%d") == "2022-01-01"
    assert pale["latest_dt"].strftime("%Y-%m-%d") == "2022-02-05"
    assert groups[1]["ratings"] == []


def test_brewery_and_venue_groups(entries) -> None:
    breweries = {group["brewery"]: group for group in aggregates.build_brewery_groups(entries)}
    assert breweries["Demo Brewing Co."]["unique_beers"] == 2
    assert breweries["Example Brewery"]["unique_beers"] == 1
    assert breweries["Fixture Ales"]["country"] == "-"

    venues = {group["venue"]: group for group in aggregates.build_venue_groups(entries)}
    assert set(venues) == {"Example Taproom", "Example Bottle Shop"}
    taproom = venues["Example Taproom"]
    assert len(taproom["entries"]) == 3
    assert taproom["unique_beers"] == 2
    assert taproom["unique_breweries"] == 2


def test_ratings_abv_and_top_counts(entries) -> None:
    assert aggregates.mean_rating_value([]) == -1.0
    assert aggregates.mean_rating_text([]) == "-"
    assert aggregates.mean_rating_text([4.0, 3.75]) == "3.88"
    assert aggregates.mean_rating_text([4.0, 4.0]) == "4"

    assert aggregates.abv_table_text(by_id(entries, 101)) == "5.2%"
    assert aggregates.abv_table_text(by_id(entries, 104)) == "0.0%"
    assert aggregates.abv_table_text({}) == "-"
    assert aggregates.abv_table_text({"beer_abv": "n/a"}) == "n/a%"
    assert aggregates.abv_sort_value({"beer_abv": "n/a"}) == -1.0
    assert aggregates.abv_sort_value(by_id(entries, 103)) == 8.0

    assert aggregates.top_counts(entries, aggregates.venue_label, limit=2) == [
        ("Example Taproom", 3),
        ("-", 1),
    ]


def test_search_blobs(entries) -> None:
    had = aggregates.HadCounts.from_entries(entries)
    blob = aggregates.entry_search_blob(by_id(entries, 102), had).split("\n")
    assert blob[:3] == ["2022-02-05 18:00:00", "2", "Sample Pale Ale"]

    beer_blob = aggregates.beer_search_blob(aggregates.build_beer_groups(entries)[-1])
    assert beer_blob.startswith("Example Brewery\nSample Pale Ale\n")

    venue = aggregates.build_venue_groups(entries)[0]
    venue_blob = aggregates.aggregate_search_blob(venue)
    assert "Example Taproom" in venue_blob
    assert "[4.0" not in venue_blob  # ratings lists are not part of the blob


def test_detail_texts(entries) -> None:
    had = aggregates.HadCounts.from_entries(entries)
    text = details.checkin_details_text(by_id(entries, 102), entries, had)
    assert text.startswith("Beer: Sample Pale Ale\nBrewery: Example Brewery\n")
    assert "Check-in: 2\nTotal had with this check-in: 2\nTotal Had: 2\n" in text
    assert text.endswith("Had dates:\n2022-02-05 18:00:00\n2022-01-01 19:30:00")

    summary = details.checkin_summary_line(by_id(entries, 103), had)
    assert summary.startswith(
        "2022-03-10 20:15:00 | beer=Test Stout | brewery=Demo Brewing Co. "
        "| venue=Example Bottle Shop | rating=4.25 | check-in=3 | had=1"
    )

    beer_text = details.beer_details_text(aggregates.build_beer_groups(entries)[-1], had)
    assert "\nTop venues:\n2  Example Taproom\n" in beer_text
    assert "\nCheck-ins:\n2022-02-05 18:00:00 | venue=Example Taproom | rating=3.75" in beer_text

    venue_text = details.venue_details_text(aggregates.build_venue_groups(entries)[0], had)
    assert venue_text.startswith("Venue: Example Taproom\nCity: Stockholm\n")
    assert "Unique breweries: 2" in venue_text


@pytest.mark.parametrize("module", [aggregates, details])
def test_untappd_logic_modules_do_not_import_qt_or_the_cli(module) -> None:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not {name for name in imported if name and name.startswith("PySide6")}
    assert "export_inspector.untappd.cli" not in imported
