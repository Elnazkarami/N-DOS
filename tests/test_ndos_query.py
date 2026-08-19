"""Tests for cohort queries.

The behaviour that carries the most scientific weight is the three-way split:
a session whose deciding value was never recorded must not be silently
treated as a non-match, because doing so biases the cohort invisibly.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ndos_query import (
    QueryError,
    build_cohort,
    diagnose,
    evaluate,
    parse_constraint,
    render,
    run_query,
)


def _session(ndos_id, path="p", declared=None, observed=None):
    base = {"path": path, "file_count": 1, "bytes": 10, "modalities": []}
    base.update(observed or {})
    return {
        "ndos_id": ndos_id,
        "observed": base,
        "declared": {
            key: (value if isinstance(value, dict) else {"value": value, "status": "declared"})
            for key, value in (declared or {}).items()
        },
    }


def _metadata(*sessions):
    return {
        "metadata_version": "0.1",
        "generated_at": "2026-01-01T00:00:00Z",
        "session_count": len(sessions),
        "sessions": list(sessions),
    }


class ParsingTests(unittest.TestCase):
    def test_operators_are_parsed_longest_first(self):
        # '>=' must not be read as '>' followed by '='.
        self.assertEqual(parse_constraint("session_date>=2025-01-01")["operator"], ">=")
        self.assertEqual(parse_constraint("file_count<=5")["operator"], "<=")
        self.assertEqual(parse_constraint("sex!=M")["operator"], "!=")
        self.assertEqual(parse_constraint("notes~theta")["operator"], "~")

    def test_query_values_are_normalised_like_the_data(self):
        constraint = parse_constraint("species=mouse")
        self.assertEqual(constraint["value"], "mus musculus")
        self.assertEqual(constraint["resolved_from"], "mouse")

    def test_observed_fields_are_recognised_with_or_without_a_prefix(self):
        self.assertEqual(parse_constraint("modalities~ephys")["source"], "observed")
        self.assertEqual(parse_constraint("observed.file_count>3")["field"], "file_count")

    def test_presence_and_unknown_shorthands(self):
        self.assertEqual(parse_constraint("strain=*")["operator"], "present")
        self.assertEqual(parse_constraint("sex=?")["operator"], "unknown")

    def test_unusable_constraints_are_rejected_with_guidance(self):
        with self.assertRaises(QueryError):
            parse_constraint("species")
        with self.assertRaises(QueryError):
            parse_constraint("nonexistent_field=1")
        with self.assertRaises(QueryError) as caught:
            parse_constraint("nonexistent_field=1")
        self.assertIn("Available fields", str(caught.exception))


class ThreeWayOutcomeTests(unittest.TestCase):
    """A missing value is not evidence against a session."""

    def test_a_never_entered_field_yields_unresolved_not_excluded(self):
        metadata = _metadata(_session("ndos-0000000001", declared={"species": "mus musculus"}))
        result = run_query(metadata, [parse_constraint("sex=F")])

        self.assertEqual(result["counts"]["matched"], 0)
        self.assertEqual(result["counts"]["unresolved"], 1)
        self.assertEqual(result["counts"]["excluded"], 0)
        self.assertEqual(result["unresolved"][0]["missing"][0]["reason"], "never entered")

    def test_a_value_recorded_as_unknown_also_yields_unresolved(self):
        metadata = _metadata(
            _session("ndos-0000000001", declared={"sex": {"value": "unknown", "status": "unknown"}})
        )
        result = run_query(metadata, [parse_constraint("sex=F")])

        self.assertEqual(result["counts"]["unresolved"], 1)
        self.assertIn("could not be determined", result["unresolved"][0]["missing"][0]["reason"])

    def test_a_recorded_contradiction_excludes(self):
        metadata = _metadata(_session("ndos-0000000001", declared={"sex": "M"}))
        result = run_query(metadata, [parse_constraint("sex=F")])

        self.assertEqual(result["counts"]["excluded"], 1)
        self.assertEqual(result["counts"]["unresolved"], 0)

    def test_a_real_failure_takes_precedence_over_a_missing_value(self):
        # Excluded by species, and separately missing sex: it is excluded, not
        # unresolved, because we already know it does not qualify.
        metadata = _metadata(_session("ndos-0000000001", declared={"species": "rattus norvegicus"}))
        result = run_query(
            metadata, [parse_constraint("species=mouse"), parse_constraint("sex=F")]
        )

        self.assertEqual(result["counts"]["excluded"], 1)
        self.assertEqual(result["counts"]["unresolved"], 0)

    def test_the_unknown_shorthand_finds_explicitly_unknown_values(self):
        metadata = _metadata(
            _session("ndos-0000000001", declared={"sex": {"value": "unknown", "status": "unknown"}}),
            _session("ndos-0000000002", declared={"sex": "F"}),
        )
        result = run_query(metadata, [parse_constraint("sex=?")])

        self.assertEqual(result["counts"]["matched"], 1)
        self.assertEqual(result["matched"][0]["ndos_id"], "ndos-0000000001")


class EvidenceCitationTests(unittest.TestCase):
    def test_every_match_cites_its_field_value_and_status(self):
        metadata = _metadata(_session("ndos-0000000001", declared={"sex": "F"}))
        result = run_query(metadata, [parse_constraint("sex=F")])

        evidence = result["matched"][0]["evidence"][0]
        self.assertEqual(evidence["field"], "sex")
        self.assertEqual(evidence["value"], "F")
        self.assertEqual(evidence["status"], "declared")

    def test_the_originally_entered_text_is_cited_when_a_value_was_mapped(self):
        metadata = _metadata(
            _session(
                "ndos-0000000001",
                declared={
                    "species": {
                        "value": "mus musculus",
                        "status": "declared",
                        "as_entered": "mouse",
                    }
                },
            )
        )
        result = run_query(metadata, [parse_constraint("species=mouse")])
        self.assertEqual(result["matched"][0]["evidence"][0]["as_entered"], "mouse")

    def test_only_the_matching_list_entries_are_cited(self):
        metadata = _metadata(
            _session(
                "ndos-0000000001",
                observed={"modalities": ["Electrophysiology", "Imaging and video"]},
            )
        )
        result = run_query(metadata, [parse_constraint("modalities~electrophysiology")])
        self.assertEqual(result["matched"][0]["evidence"][0]["value"], ["Electrophysiology"])


class ComparisonTests(unittest.TestCase):
    def test_iso_dates_order_correctly(self):
        metadata = _metadata(
            _session("ndos-0000000001", declared={"session_date": "2025-03-14"}),
            _session("ndos-0000000002", declared={"session_date": "2025-01-02"}),
        )
        result = run_query(metadata, [parse_constraint("session_date>=2025-03-01")])
        self.assertEqual([r["ndos_id"] for r in result["matched"]], ["ndos-0000000001"])

    def test_numeric_fields_compare_as_numbers_not_strings(self):
        metadata = _metadata(
            _session("ndos-0000000001", observed={"file_count": 9}),
            _session("ndos-0000000002", observed={"file_count": 100}),
        )
        result = run_query(metadata, [parse_constraint("file_count>10")])
        self.assertEqual([r["ndos_id"] for r in result["matched"]], ["ndos-0000000002"])

    def test_text_matching_ignores_case(self):
        metadata = _metadata(_session("ndos-0000000001", declared={"target_region": "ca1"}))
        result = run_query(metadata, [parse_constraint("target_region=CA1")])
        self.assertEqual(result["counts"]["matched"], 1)

    def test_no_constraints_returns_everything(self):
        metadata = _metadata(_session("ndos-0000000001"), _session("ndos-0000000002"))
        result = run_query(metadata, [])
        self.assertEqual(result["counts"]["matched"], 2)


class DiagnosisTests(unittest.TestCase):
    def test_an_empty_result_names_the_constraint_responsible(self):
        metadata = _metadata(
            _session("ndos-0000000001", declared={"species": "rattus norvegicus"}),
            _session("ndos-0000000002", declared={"species": "rattus norvegicus"}),
        )
        result = run_query(metadata, [parse_constraint("species=mouse")])
        notes = " ".join(diagnose(result))

        self.assertIn("species=mouse", notes)
        self.assertIn("2 excluded", notes)

    def test_a_gap_in_the_data_is_distinguished_from_a_bad_query(self):
        metadata = _metadata(_session("ndos-0000000001", declared={"species": "mus musculus"}))
        result = run_query(
            metadata, [parse_constraint("species=mouse"), parse_constraint("genotype=WT")]
        )
        notes = " ".join(diagnose(result))

        self.assertIn("never entered", notes)
        self.assertIn("not a different query", notes)

    def test_already_excluded_sessions_are_not_blamed_on_missing_fields(self):
        # Filling in 'genotype' for a rat would not help someone looking for
        # mice, so it must not be suggested.
        metadata = _metadata(_session("ndos-0000000001", declared={"species": "rattus norvegicus"}))
        result = run_query(
            metadata, [parse_constraint("species=mouse"), parse_constraint("genotype=WT")]
        )
        notes = " ".join(diagnose(result))

        self.assertNotIn("genotype", notes)

    def test_empty_metadata_says_so_plainly(self):
        result = run_query(_metadata(), [parse_constraint("sex=F")])
        self.assertIn("no sessions", " ".join(diagnose(result)))


class CohortTests(unittest.TestCase):
    def _result(self):
        metadata = _metadata(
            _session("ndos-0000000001", "a", declared={"sex": "F"}),
            _session("ndos-0000000002", "b", declared={"species": "mus musculus"}),
            _session("ndos-0000000003", "c", declared={"sex": "M"}),
        )
        return metadata, run_query(metadata, [parse_constraint("sex=F")])

    def test_a_cohort_excludes_unresolved_sessions_by_default(self):
        metadata, result = self._result()
        cohort = build_cohort(result, metadata, Path("m.json"), name="c")

        self.assertEqual(cohort["member_count"], 1)
        self.assertFalse(cohort["includes_unresolved"])
        self.assertEqual(cohort["members"][0]["inclusion"], "matched")

    def test_unresolved_sessions_can_be_included_and_are_labelled(self):
        metadata, result = self._result()
        cohort = build_cohort(
            result, metadata, Path("m.json"), name="c", include_unresolved=True
        )

        self.assertEqual(cohort["member_count"], 2)
        self.assertTrue(cohort["includes_unresolved"])
        self.assertEqual(
            {m["inclusion"] for m in cohort["members"]}, {"matched", "unresolved"}
        )

    def test_the_cohort_records_the_query_that_produced_it(self):
        metadata, result = self._result()
        cohort = build_cohort(result, metadata, Path("m.json"))

        self.assertEqual(cohort["query_plan"][0]["as_typed"], "sex=F")
        self.assertEqual(cohort["source"]["metadata_version"], "0.1")
        # Counts of what was left out travel with the cohort, not just members.
        self.assertEqual(cohort["counts"]["excluded"], 1)
        self.assertEqual(cohort["counts"]["unresolved"], 1)

    def test_cohorts_validate_against_the_published_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed; NDOS core stays stdlib-only")

        schema_path = (
            Path(__file__).resolve().parent.parent / "schemas" / "cohort.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        metadata, result = self._result()
        for include in (False, True):
            jsonschema.validate(
                build_cohort(
                    result, metadata, Path("m.json"), name="c", include_unresolved=include
                ),
                schema,
            )


class RenderingTests(unittest.TestCase):
    def test_the_report_separates_the_three_outcomes(self):
        metadata = _metadata(
            _session("ndos-0000000001", "a", declared={"sex": "F"}),
            _session("ndos-0000000002", "b"),
            _session("ndos-0000000003", "c", declared={"sex": "M"}),
        )
        text = render(run_query(metadata, [parse_constraint("sex=F")]))

        self.assertIn("MATCHED (1)", text)
        self.assertIn("CANNOT BE RULED OUT (1)", text)
        self.assertIn("EXCLUDED (1)", text)
        self.assertIn("They are not non-matches.", text)

    def test_the_query_plan_shows_what_a_typed_value_resolved_to(self):
        metadata = _metadata(_session("ndos-0000000001", declared={"species": "mus musculus"}))
        text = render(run_query(metadata, [parse_constraint("species=mouse")]))
        self.assertIn("you typed 'mouse'", text)


if __name__ == "__main__":
    unittest.main()
