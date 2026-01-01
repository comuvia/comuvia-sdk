"""Write the synthetic ForeGlass-format fixture and its expectations.

Standard library only; Python 3.11+.

    python -I tools/make_foreglass_fixture.py           # (re)write the fixture files
    python -I tools/make_foreglass_fixture.py --check   # fail if any file is stale

Every metric, value, statement, source and locator is fictional; locators inside text
use example.org. Only the *format* matches the public ForeGlass artifacts measured on
2026-09-24 (public ledger build "2026-09-09", 699,605 bytes, sha256 3c97f09f...):

- ledger.json: the v1 top-level keys in order, 2-space indent, ASCII with \\uXXXX escapes,
  CRLF line endings and a trailing CRLF; lane keys in the published order.
- ledger-archive index.json: LF line endings, UTF-8 (a literal non-ASCII character).
- fragility latest.json: indented LF JSON reading with a caveat.

Files are written to fixtures/synthetic/foreglass-ledger/ and copied byte-for-byte into
packages/foreglass/tests/vectors/foreglass-ledger/ for installed tests. No public
ForeGlass bytes are copied.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "fixtures" / "synthetic" / "foreglass-ledger"
PACKAGE_COPY = REPO / "packages" / "foreglass" / "tests" / "vectors" / "foreglass-ledger"
MIDDOT, EN_DASH, EM_DASH = chr(0xB7), chr(0x2013), chr(0x2014)
BUILT = "2026-09-20"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cut(text: str, length: int) -> str:
    """Cut ``text`` to ``length`` characters, asserting the cut lands mid-word."""
    assert len(text) > length and text[length - 1].isalpha() and text[length].isalpha(), (text[length - 2:length + 2])
    return text[:length]


def lane(**fields) -> dict:
    """A lane with keys in the published order; optional keys only when given."""
    order = [
        "id", "metric", "due", "predShort", "predFull", "kind", "arm", "status", "naive_value", "scope", "sha",
        "statement", "source", "criteria", "qid", "sealed_at", "prompt_version", "val", "lo", "hi", "model", "unit",
        "gkey", "obsKey", "marker", "arm_label", "validation_status", "core_sha256",
        "validation_card_url", "caveat", "caveat_id", "withheld_fields",
    ]
    core = sha("synthetic-core|" + fields["id"] + "|" + repr(fields["val"]))
    fields.setdefault("core_sha256", core)
    fields.setdefault("sha", core[:6])
    fields.setdefault("status", "open")
    fields.setdefault("validation_status", "experimental")
    fields.setdefault("arm_label", "")
    fields.setdefault("prompt_version", None)
    extra = [k for k in fields if k not in order]
    return {k: fields[k] for k in order + extra if k in fields}


QID_BERTH = "q:harbor_berth_closure@2026-12-15"
GKEY_BERTH = QID_BERTH + "||binary||probability (event = Meridian harbor announces a berth closure)"

LANES = [
    # 1. Engine interval lane that is a scenario span (val == hi).
    lane(id="eng-2026-11-30-canal-delay-days-scenario", metric="canal_delay_days", due="2026-11-30",
         predShort="14 days", predFull="14.0 [6.5" + EN_DASH + "14.0] days", kind="interval", arm="engine",
         naive_value=9.0, scope="Meridian",
         statement="Average vessel delay at the fictional Meridian Canal in November 2026, engine scenario span.",
         source="Meridian Canal Authority (fictional) monthly transit note, https://example.org/synthetic/meridian/transit",
         criteria="Average of daily reported delays for November 2026 as first published.",
         qid="q:canal_delay_days@2026-11-30", sealed_at="2026-09-12", val=14.0, lo=6.5, hi=14.0, model="ForeGlass",
         unit="days", gkey="q:canal_delay_days@2026-11-30||interval||days of average vessel delay"),
    # 2. Interval lane whose coverage appears only in its statement text.
    lane(id="llm-2026-12-31-harbor-teu-index", metric="harbor_teu_index", due="2026-12-31",
         predShort="112.4", predFull="112.4 [104.0" + EN_DASH + "121.5] index", kind="interval", arm="llm",
         scope="Meridian", statement="Meridian harbor TEU index for December 2026; an 80% interval is stated by the model.",
         source="Harbor Statistics Office (fictional), https://example.org/synthetic/harbor/teu",
         criteria="Index value for December 2026 in the first release.", qid="q:harbor_teu_index@2026-12-31",
         sealed_at="2026-09-13", prompt_version=3, val=112.4, lo=104.0, hi=121.5, model="model-alpha",
         unit="index", gkey="q:harbor_teu_index@2026-12-31||interval||index points (2020 = 100)"),
    # 3. Point lane (no lo/hi), with obsKey and marker.
    lane(id="ens-2026-10-31-lantern-price-level", metric="lantern_price_level", due="2026-10-31",
         predShort="3.1 %", predFull="3.1 % y/y", kind="point", arm="ensemble", naive_value=2.8, scope=EM_DASH,
         statement="Lantern City consumer price change for October 2026, year over year.",
         source="Lantern City Statistics Bureau (fictional), https://example.org/synthetic/lantern/prices",
         criteria="Year-over-year change of the headline index for October 2026 as first published.",
         qid="q:lantern_price_level@2026-10-31", sealed_at="2026-09-14", val=3.1, lo=None, hi=None,
         model="ens" + MIDDOT + "median", unit="% y/y", gkey="q:lantern_price_level@2026-10-31||point||% change y/y",
         obsKey="lantern_cpi.yoy",
         marker={"due": "2026-10-31", "kind": "point", "unit": "% y/y", "value": 3.1, "low": 2.9, "high": 3.3}),
    # 4. Binary lane, unit "probability", "(event = ...)" gkey.
    lane(id="llm-2026-12-15-harbor-berth-closure-alpha", metric="harbor_berth_closure", due="2026-12-15",
         predShort="35%", predFull="35% probability", kind="binary", arm="llm", scope="Meridian",
         statement="Will the fictional Meridian harbor authority announce a berth closure by 15 December 2026?",
         source="Meridian harbor notices (fictional), https://example.org/synthetic/harbor/notices",
         criteria="Resolves yes if a berth closure notice is published on the notices page by 15 December 2026.",
         qid=QID_BERTH, sealed_at="2026-09-15", prompt_version=3, val=0.35, lo=None, hi=None, model="model-alpha",
         unit="probability", gkey=GKEY_BERTH, arm_label="alpha (llm)"),
    # 5. Binary "indicator over ..." lane whose criteria is exactly 220 characters, cut mid-word.
    lane(id="llm-2027-03-31-lantern-rate-cut", metric="lantern_rate_cut", due="2027-03-31",
         predShort="60%", predFull="60% probability", kind="binary", arm="llm", scope="Lantern",
         statement="Will the fictional Lantern City reserve board cut its policy rate in the first quarter of 2027?",
         source="Lantern reserve board (fictional) decisions, https://example.org/synthetic/lantern/board",
         criteria=cut("Indicator equals one if the Lantern reserve board announces a reduction of its main policy rate "
                      "at any scheduled or unscheduled meeting between 1 January 2027 and 31 March 2027 inclusive, as "
                      "recorded in the board's published decisions archive and minutes", 220),
         qid="q:lantern_rate_cut@2027-03-31", sealed_at="2026-09-15", prompt_version=3, val=0.6, lo=None, hi=None,
         model="model-beta", unit="indicator over quarter",
         gkey="q:lantern_rate_cut@2027-03-31||binary||indicator over quarter (event = policy rate cut announced)"),
    # 6. Model-conditional binary lane: CI95 in predFull, lo/hi set, &middot; entity.
    lane(id="eng-2027-01-31-canal-closure-hazard", metric="canal_closure_hazard", due="2027-01-31",
         predShort="22%", predFull="22% p &middot; CI95 [0.1, 0.3825]", kind="binary", arm="engine",
         scope="Meridian", statement="Will the fictional Meridian Canal close to traffic for at least one day in January 2027?",
         source="Meridian Canal Authority (fictional) status page, https://example.org/synthetic/meridian/status",
         criteria="Resolves yes if the status page reports a full closure lasting at least 24 hours in January 2027.",
         qid="q:canal_closure_hazard@2027-01-31", sealed_at="2026-09-16", val=0.22, lo=0.1, hi=0.3825,
         model="ForeGlass", unit="probability",
         gkey="q:canal_closure_hazard@2027-01-31||binary||probability (event = canal closed at least one day)",
         validation_status="model-conditional", caveat_id="crisis-hazard-model-conditional",
         caveat="Conditional on the fictional hazard model's regime staying in its calm state; not an unconditional probability."),
    # 7. Binary lane whose outcome was published before the seal.
    lane(id="llm-2026-09-10-lantern-fair-attendance", metric="lantern_fair_attendance", due="2026-09-10",
         predShort="80%", predFull="80% probability", kind="binary", arm="llm", scope="Lantern",
         statement="Will the fictional Lantern City autumn fair report more than 50,000 visitors?",
         source="Lantern fair organisers (fictional), https://example.org/synthetic/lantern/fair",
         criteria="Resolves yes if the organisers' published total exceeds 50,000 visitors.",
         qid="q:lantern_fair_attendance@2026-09-10", sealed_at="2026-09-17", prompt_version=3, val=0.8, lo=None,
         hi=None, model="model-beta", unit="probability",
         gkey="q:lantern_fair_attendance@2026-09-10||binary||probability (event = attendance above 50,000)",
         caveat_id="outcome-published-before-seal",
         caveat="The organisers published the attendance total before this lane was sealed."),
    # 8. Binary lane with a blank qid.
    lane(id="llm-2026-12-01-harbor-strike", metric="harbor_strike", due="2026-12-01", predShort="15%",
         predFull="15% probability", kind="binary", arm="llm", scope="Meridian",
         statement="Will fictional Meridian dock workers strike before December 2026?",
         source="Meridian labour notices (fictional), https://example.org/synthetic/harbor/labour",
         criteria="Resolves yes if a strike is reported in the labour notices before 1 December 2026.",
         qid="", sealed_at="2026-09-17", prompt_version=3, val=0.15, lo=None, hi=None, model="model-alpha",
         unit="probability", gkey="||binary||probability (event = dock strike begins)"),
    # 9. Binary lane with withheld_fields (source withheld) and a statement of exactly 320 characters.
    lane(id="ens-2026-11-15-canal-toll-increase", metric="canal_toll_increase", due="2026-11-15",
         predShort="45%", predFull="45% probability", kind="binary", arm="ensemble", scope="Meridian",
         statement=cut("Will the fictional Meridian Canal Authority announce an increase to the standard transit toll for "
                       "container vessels, effective on or before 15 November 2026, as stated in a published tariff "
                       "notice that names the new toll schedule and its effective date, excluding temporary surcharges "
                       "and excluding changes limited to bulk carriers or passenger vessels travelling northbound", 320),
         criteria="Resolves yes if a tariff notice raising the standard container toll takes effect by 15 November 2026.",
         qid="q:canal_toll_increase@2026-11-15", sealed_at="2026-09-18", val=0.45, lo=None, hi=None,
         model="ens" + MIDDOT + "inv-var", unit="probability",
         gkey="q:canal_toll_increase@2026-11-15||binary||probability (event = container toll increase effective)",
         withheld_fields=["source"]),
    # 10. Second binary lane on the qid of lane 4, different arm.
    lane(id="ens-2026-12-15-harbor-berth-closure", metric="harbor_berth_closure", due="2026-12-15",
         predShort="40%", predFull="40% probability", kind="binary", arm="ensemble", scope="Meridian",
         statement="Will the fictional Meridian harbor authority announce a berth closure by 15 December 2026?",
         source="Meridian harbor notices (fictional), https://example.org/synthetic/harbor/notices",
         criteria="Resolves yes if a berth closure notice is published on the notices page by 15 December 2026.",
         qid=QID_BERTH, sealed_at="2026-09-18", val=0.4, lo=None, hi=None, model="ens" + MIDDOT + "trimmed",
         unit="probability", gkey=GKEY_BERTH, arm_label="ensemble (trimmed)"),
    # 11. Binary lane carrying unrecognized future outcome keys and an unknown non-outcome field.
    lane(id="llm-2026-10-20-lantern-bridge-opening", metric="lantern_bridge_opening", due="2026-10-20",
         predShort="70%", predFull="70% probability", kind="binary", arm="llm", scope="Lantern",
         statement="Will the fictional Lantern river bridge open to traffic by 20 October 2026?",
         source="Lantern public works (fictional), https://example.org/synthetic/lantern/works",
         criteria="Resolves yes if public works reports the bridge open to general traffic by 20 October 2026.",
         qid="q:lantern_bridge_opening@2026-10-20", sealed_at="2026-09-19", prompt_version=3, val=0.7, lo=None,
         hi=None, model="model-alpha", unit="probability",
         gkey="q:lantern_bridge_opening@2026-10-20||binary||probability (event = bridge opens to traffic)",
         outcome={"value": 1, "published": "2026-10-21"}, graded_at="2026-10-22", horizon_days=31),
    # 12. Valid binary lane that publishes no unit: unit "" and an empty third gkey segment.
    lane(id="ens-2027-06-30-lantern-slowdown-2027h1", metric="lantern_slowdown_2027h1", due="2027-06-30",
         predShort="55%", predFull="55% probability", kind="binary", arm="ensemble", scope="Lantern",
         statement="Will the fictional Lantern City economy record two consecutive quarters of contraction in 2027H1?",
         source="Lantern City Statistics Bureau (fictional) quarterly accounts, https://example.org/synthetic/lantern/accounts",
         criteria="Resolves yes if the first estimates for 2027Q1 and 2027Q2 both show quarter-on-quarter contraction.",
         qid="q:lantern_slowdown_2027h1@2027-06-30", sealed_at="2026-09-19", val=0.55, lo=None, hi=None,
         model="ens" + MIDDOT + "median", unit="", gkey="q:lantern_slowdown_2027h1@2027-06-30||binary||"),
]

WITHHELD_COUNT = 1


def ledger_document() -> dict:
    commitments = [
        {"id": l["id"], "core_sha256": l["core_sha256"], "sealed_at": l["sealed_at"]}
        for l in LANES if l["id"] not in ("llm-2026-12-01-harbor-strike", "llm-2026-10-20-lantern-bridge-opening")
    ]
    return {
        "_schema": "foreglass.verification-ledger/v1",
        "tier": "public",
        "built": BUILT,
        "registry_schema": "foreglass.prediction-registry/v0",
        "seal": {
            "algorithm": "sha256",
            "recipe": "sha256 over the canonical lane core (synthetic fixture recipe; not the provider's recipe)",
            "verifiable_here": "commitment-equality",
            "note": "Synthetic fixture for the comuvia SDK. Values and commitments are fictional.",
        },
        "counts": {"included": len(LANES), "held": len(commitments), "withheld": WITHHELD_COUNT},
        "lanes": LANES,
        "commitments": commitments,
    }


def ledger_bytes(document: dict) -> bytes:
    text = json.dumps(document, indent=2, ensure_ascii=True)
    return (text.replace("\n", "\r\n") + "\r\n").encode("ascii")


OTS_BYTES = (
    b"SYNTHETIC FIXTURE - NOT AN OPENTIMESTAMPS PROOF\n"
    b"These bytes stand in for ledger.json.ots in the comuvia SDK fixture. They prove nothing.\n"
)


def archive_index_bytes(ledger: bytes) -> bytes:
    second = hashlib.sha256(b"synthetic second build of " + BUILT.encode()).hexdigest()
    index = {
        "schema": "foreglass.ledger-archive/v1",
        "note": "Synthetic archive index for the comuvia SDK fixture; identify a build by sha256, not by file name.",
        "source_pack_bytes": "not published " + EM_DASH + " synthetic fixture",
        "files": [
            {"file": f"{BUILT}.json", "bytes": len(ledger), "sha256": hashlib.sha256(ledger).hexdigest(), "ots": f"{BUILT}.json.ots"},
            {"file": f"{BUILT}b.json", "bytes": 4096, "sha256": second, "ots": f"{BUILT}b.json.ots"},
        ],
    }
    return (json.dumps(index, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def latest_bytes() -> bytes:
    reading = {
        "date": "2026-09-20",
        "reading": 0.412,
        "regime": "calm",
        "provisional": True,
        "provisional_quarter": "2026Q3",
        "qtd_through": "2026-09-18",
        "leg_freshness": [{"leg": "harbor freight leg", "through": "2026-09-18"}, {"leg": "canal leg", "through": "2026-09-15"}],
        "staleness": {"oldest_leg_through": "2026-09-15", "max_age_days": 5, "note": "Synthetic reading; legs lag."},
        "deltas": {"vs_prior_day": None, "vs_quarter_open": -0.031},
        "settle_band": {"low": 0.38, "high": 0.45},
        "last_settled": {"quarter": "2026Q2", "reading": 0.44, "regime": "calm"},
        "caveat": "Index reading, not a forecast or a probability; synthetic fixture values.",
    }
    return (json.dumps(reading, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def expected(ledger: bytes) -> dict:
    """Hand-specified expectations for normalization, evaluation and intake."""
    binary_mapped = {
        "llm-2026-12-15-harbor-berth-closure-alpha": {"question_qid": QID_BERTH, "limitations": []},
        "llm-2027-03-31-lantern-rate-cut": {"question_qid": "q:lantern_rate_cut@2027-03-31", "limitations": ["text_possibly_truncated"]},
        "eng-2027-01-31-canal-closure-hazard": {"question_qid": "q:canal_closure_hazard@2027-01-31", "limitations": [], "conditional": True},
        "llm-2026-09-10-lantern-fair-attendance": {"question_qid": "q:lantern_fair_attendance@2026-09-10",
                                                   "limitations": ["outcome_published_before_registration"]},
        "ens-2026-11-15-canal-toll-increase": {"question_qid": "q:canal_toll_increase@2026-11-15",
                                               "limitations": ["text_possibly_truncated", "provider_fields_withheld"]},
        "ens-2026-12-15-harbor-berth-closure": {"question_qid": QID_BERTH, "limitations": []},
        "llm-2026-10-20-lantern-bridge-opening": {"question_qid": "q:lantern_bridge_opening@2026-10-20", "limitations": []},
        "ens-2027-06-30-lantern-slowdown-2027h1": {"question_qid": "q:lantern_slowdown_2027h1@2027-06-30", "limitations": [],
                                                   "question_unit": {"unknown": "provider_declares_no_unit"}},
    }
    base = ["incomplete_question", "missing_required_time"]
    reasons = {
        "llm-2026-12-15-harbor-berth-closure-alpha": base + ["no_outcome_recorded"],
        "llm-2027-03-31-lantern-rate-cut": base + ["resolution_rule_incomplete", "no_outcome_recorded"],
        "eng-2027-01-31-canal-closure-hazard": ["incomplete_question", "conditional_scenario", "missing_required_time",
                                                "no_outcome_recorded"],
        "llm-2026-09-10-lantern-fair-attendance": base + ["retrospective_registration", "no_outcome_recorded"],
        "ens-2026-11-15-canal-toll-increase": base + ["resolution_rule_incomplete", "no_outcome_recorded"],
        "ens-2026-12-15-harbor-berth-closure": base + ["no_outcome_recorded"],
        "llm-2026-10-20-lantern-bridge-opening": base + ["no_outcome_recorded"],
        "ens-2027-06-30-lantern-slowdown-2027h1": base + ["no_outcome_recorded"],
    }
    return {
        "fixture": "foreglass-ledger",
        "status": "synthetic",
        "note": "Expected results, specified by hand. foreglass normalization and the comuvia evaluator must reproduce them.",
        "ledger": {"byte_length": len(ledger), "sha256": hashlib.sha256(ledger).hexdigest(), "crlf": True, "ascii": True},
        "lanes": {
            "count": len(LANES),
            "by_kind": {"binary": 9, "interval": 2, "point": 1},
        },
        "mapping": {
            "mapped": binary_mapped,
            "not_mapped": {
                "eng-2026-11-30-canal-delay-days-scenario": "unsupported_output_kind",
                "llm-2026-12-31-harbor-teu-index": "unsupported_output_kind",
                "ens-2026-10-31-lantern-price-level": "unsupported_output_kind",
                "llm-2026-12-01-harbor-strike": "no_pinned_question",
            },
            "questions": 7,
            "forecasts": 8,
            "same_family": [["llm-2026-12-15-harbor-berth-closure-alpha", "ens-2026-12-15-harbor-berth-closure"]],
        },
        "drift": [
            {"lane": "llm-2026-10-20-lantern-bridge-opening", "field": "outcome", "code": "outcome_normalization_unsupported"},
            {"lane": "llm-2026-10-20-lantern-bridge-opening", "field": "graded_at", "code": "outcome_normalization_unsupported"},
            {"lane": "llm-2026-10-20-lantern-bridge-opening", "field": "horizon_days", "code": "unrecognized_provider_field"},
        ],
        "evaluation": {
            "counts": {"candidates": 8, "forecasts": 8, "independent_questions": 7, "forecast_families": 7,
                       "eligible": 0, "scored": 0, "unresolved": 0, "excluded": 8},
            "reasons": reasons,
        },
        "never": [
            "an interval or point lane becomes a forecast",
            "lo/hi becomes a coverage level",
            "a reading, naive_value or CI becomes a probability",
            "built becomes source_published_at",
            "a blank qid gets an identity",
        ],
        "intake": {
            "complete_bundle": "accepted",
            "truncated_ledger": "parse_refused",
            "missing_declared_role": "incomplete_intake",
            "wrong_schema": "schema_mismatch",
            "counts_mismatch": "counts_mismatch",
            "digest_mismatch": "digest_mismatch",
            "archive_index_without_ledger": "archive_index_mismatch",
            "replay": "verified, never accepted as the live snapshot",
        },
    }


def outputs() -> dict[str, bytes]:
    ledger = ledger_bytes(ledger_document())
    files = {
        "source/ledger.json": ledger,
        "source/ledger.json.ots": OTS_BYTES,
        "source/ledger-archive-index.json": archive_index_bytes(ledger),
        "source/fragility-latest.json": latest_bytes(),
    }
    files["expected.json"] = (json.dumps(expected(ledger), indent=2, ensure_ascii=True) + "\n").encode("ascii")
    return files


def main() -> int:
    check = "--check" in sys.argv[1:]
    stale = []
    for root in (FIXTURE, PACKAGE_COPY):
        for name, data in outputs().items():
            path = root / name
            if not path.exists() or path.read_bytes() != data:
                stale.append(path)
                if not check:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
    for path in stale:
        print(("STALE " if check else "wrote ") + path.relative_to(REPO).as_posix())
    if check:
        print("PASS" if not stale else "FAIL")
        return 1 if stale else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
