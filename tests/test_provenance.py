"""Data provenance classification and summarisation."""

from __future__ import annotations

from services.data.provenance import (
    FABRICATED,
    LIVE,
    STALE,
    UNKNOWN,
    Provenance,
    classify,
    label_for,
)


class _FakeFundService:
    """Stands in for FundService's tracked-source maps."""

    def __init__(self, nav: dict[str, str], holdings: dict[str, str]) -> None:
        self._nav = nav
        self._holdings = holdings

    def get_nav_source(self, code: str) -> str:
        return self._nav.get(str(code), "unknown")

    def get_holdings_source(self, code: str) -> str:
        return self._holdings.get(str(code), "unknown")


def test_classify_covers_every_source_the_clients_emit():
    # The full set emitted by mfapi_client / holdings_client / fund_service.
    assert classify("mfapi") == LIVE
    assert classify("tigzig") == LIVE
    assert classify("amfi") == LIVE
    assert classify("disk_cache") == LIVE
    assert classify("sqlite") == LIVE
    assert classify("groww") == LIVE
    assert classify("groww_cache") == LIVE
    assert classify("disk_cache_stale") == STALE
    assert classify("synthetic") == FABRICATED
    assert classify("sample") == FABRICATED
    assert classify("mfapi_error") == UNKNOWN
    assert classify(None) == UNKNOWN
    assert classify("") == UNKNOWN


def test_classify_is_case_and_whitespace_insensitive():
    assert classify("  SYNTHETIC ") == FABRICATED
    assert classify("Sample") == FABRICATED


def test_unrecognised_source_is_treated_as_live_not_fabricated():
    # A new provider must not be silently labelled fabricated.
    assert classify("some_new_provider") == LIVE


def test_flags_fabricated_nav_and_holdings_separately():
    prov = Provenance(
        nav={"Alpha Fund": "mfapi", "Beta Fund": "synthetic"},
        holdings={"Alpha Fund": "groww", "Gamma Fund": "sample"},
    )
    assert prov.fabricated_nav == ["Beta Fund"]
    assert prov.fabricated_holdings == ["Gamma Fund"]
    assert prov.has_fabricated is True


def test_clean_portfolio_reports_nothing_fabricated():
    prov = Provenance(nav={"A": "mfapi", "B": "sqlite"}, holdings={"A": "groww"})
    assert prov.has_fabricated is False
    assert prov.fabricated_nav == []
    assert prov.stale_nav == []


def test_stale_cache_is_flagged_but_not_fabricated():
    prov = Provenance(nav={"A": "disk_cache_stale"})
    assert prov.stale_nav == ["A"]
    assert prov.has_fabricated is False


def test_source_counts_group_by_label():
    prov = Provenance(nav={"A": "mfapi", "B": "mfapi", "C": "synthetic"})
    assert prov.source_counts("nav") == {"mfapi.in": 2, "SYNTHETIC": 1}


def test_from_service_skips_funds_never_fetched():
    svc = _FakeFundService(nav={"100": "mfapi"}, holdings={})
    prov = Provenance.from_service(svc, [("Alpha", "100"), ("Never fetched", "999")])
    assert prov.nav == {"Alpha": "mfapi"}
    # 999 was never fetched, so it must not appear as a source at all.
    assert "Never fetched" not in prov.nav
    assert prov.holdings == {}


def test_from_service_ignores_blank_codes():
    svc = _FakeFundService(nav={"100": "synthetic"}, holdings={})
    prov = Provenance.from_service(svc, [("", ""), ("Alpha", "100")])
    assert prov.fabricated_nav == ["Alpha"]


def test_from_service_falls_back_to_code_when_label_missing():
    svc = _FakeFundService(nav={"100": "synthetic"}, holdings={})
    prov = Provenance.from_service(svc, [("", "100")])
    assert prov.fabricated_nav == ["100"]


def test_round_trip_through_dict_preserves_fabricated_flags():
    prov = Provenance(nav={"A": "synthetic"}, holdings={"A": "sample"})
    restored = Provenance.from_dict(prov.to_dict())
    assert restored.fabricated_nav == ["A"]
    assert restored.fabricated_holdings == ["A"]
    assert restored.has_fabricated is True


def test_from_dict_handles_missing_and_empty_payloads():
    assert Provenance.from_dict(None).is_empty is True
    assert Provenance.from_dict({}).is_empty is True
    assert Provenance.from_dict({"nav": {}, "holdings": {}}).has_fabricated is False


def test_to_dict_is_json_safe_for_the_analysis_payload():
    import json

    prov = Provenance(nav={"A": "synthetic"}, holdings={"A": "groww"})
    payload = json.loads(json.dumps(prov.to_dict()))
    assert payload["has_fabricated"] is True
    assert payload["fabricated_nav"] == ["A"]


def test_label_for_maps_raw_sources_to_display_names():
    assert label_for("mfapi") == "mfapi.in"
    assert label_for("synthetic") == "SYNTHETIC"
    assert label_for("unheard_of") == "unheard_of"
