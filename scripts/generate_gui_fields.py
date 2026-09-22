#!/usr/bin/env python3
"""Write the interface's field definitions from the ones the tools use.

The interface needs to know which fields exist and what values they accept.
Those facts already live in ndos_table, and a hand-written copy in TypeScript
drifted from them: the interface offered "male" and "female" where the standard
says F and M, and had no way to record a lesion at all.

So the copy is generated. Run this after changing a vocabulary, and the test
beside it fails if the checked-in file no longer matches.

    python3 scripts/generate_gui_fields.py            # write it
    python3 scripts/generate_gui_fields.py --check    # is it current?
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ndos_table  # noqa: E402  (after sys.path is set)

TARGET = ROOT / "gui" / "src" / "lib" / "ndos-generated.ts"

#: A short description per field, since the code carries the rules but not the
#: words a person needs to see beside an input.
HINTS = {
    "subject_id": "Identifier for this animal, e.g. M123",
    "species": "Common names are accepted: mouse, rat",
    "strain": "e.g. C57BL/6J",
    "sex": "F, M, or unknown once checked",
    "date_of_birth": "YYYY-MM-DD",
    "genotype": "e.g. WT",
    "source": "Where the animal came from",
    "notes": "Anything that does not fit elsewhere",
    "procedure_id": "Your own label for this procedure",
    "procedure_date": "YYYY-MM-DD",
    "procedure_type": "What was done",
    "target_region": "e.g. CA1",
    "construct_or_drug": "What was delivered",
    "dose": "e.g. 300 nL",
    "session_date": "YYYY-MM-DD",
    "session_type": "What kind of recording",
    "task": "e.g. linear track",
    "qc_status": "Whether this session passed your checks",
}

HEADER = """/**
 * Generated from the Python that validates this data. Do not edit by hand.
 *
 * Source: ndos_table.py (field lists, vocabularies and synonyms)
 * Regenerate: python3 scripts/generate_gui_fields.py
 *
 * A hand-written copy of these definitions drifted once: the interface offered
 * "male" and "female" where the standard says F and M, and could not express a
 * lesion at all. Generating them means the interface and the tools cannot
 * disagree about what the standard allows.
 */

export interface GeneratedField {
  key: string;
  hint: string;
  required: boolean;
  /** Values the tools accept, or null where any text is allowed. */
  enumValues: string[] | null;
  /** Spellings the tools map onto a listed value. */
  synonyms: Record<string, string>;
  isDate: boolean;
}
"""


def _fields(names, required, synonyms_for):
    out = []
    for key in names:
        vocabulary = ndos_table.VOCABULARIES.get(key)
        out.append(
            {
                "key": key,
                "hint": HINTS.get(key, ""),
                "required": key in required,
                "enumValues": list(vocabulary) if vocabulary else None,
                "synonyms": synonyms_for(key),
                "isDate": key in ndos_table.DATE_COLUMNS,
            }
        )
    return out


def _synonyms(key: str):
    table = {
        "sex": ndos_table.SEX_SYNONYMS,
        "species": ndos_table.SPECIES_SYNONYMS,
        "session_type": ndos_table.SESSION_TYPE_SYNONYMS,
        "procedure_type": ndos_table.PROCEDURE_TYPE_SYNONYMS,
    }.get(key)
    return dict(table) if table else {}


def render() -> str:
    groups = {
        "ANIMAL_FIELDS": _fields(
            ndos_table.ANIMAL_COLUMNS, ndos_table.REQUIRED_ANIMAL_FIELDS + ("subject_id",), _synonyms
        ),
        "PROCEDURE_FIELDS": _fields(
            ndos_table.PROCEDURE_COLUMNS, ("subject_id", "procedure_date", "procedure_type"), _synonyms
        ),
        "SESSION_FIELDS": _fields(
            ndos_table.SESSION_DECLARED_COLUMNS, ndos_table.REQUIRED_FOR_COMPLETE, _synonyms
        ),
    }
    parts = [HEADER]
    for name, fields in groups.items():
        parts.append(
            f"\nexport const {name}: GeneratedField[] = "
            + json.dumps(fields, indent=2)
            + ";\n"
        )
    parts.append(
        "\n/** The date form the standard asks for, and refuses to guess at. */\n"
        'export const ISO_DATE = /^\\d{4}-\\d{2}-\\d{2}$/;\n'
    )
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the checked-in file is out of date",
    )
    args = parser.parse_args()

    wanted = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else ""
        if current != wanted:
            print(
                f"{TARGET.relative_to(ROOT)} is out of date.\n"
                "Run: python3 scripts/generate_gui_fields.py",
                file=sys.stderr,
            )
            return 1
        print(f"{TARGET.relative_to(ROOT)} is current")
        return 0

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(wanted, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
