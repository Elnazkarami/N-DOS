/**
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

export const ANIMAL_FIELDS: GeneratedField[] = [
  {
    "key": "subject_id",
    "hint": "Identifier for this animal, e.g. M123",
    "required": true,
    "enumValues": null,
    "synonyms": {},
    "isDate": false
  },
  {
    "key": "species",
    "hint": "Common names are accepted: mouse, rat",
    "required": true,
    "enumValues": [
      "mus musculus",
      "rattus norvegicus",
      "macaca mulatta",
      "danio rerio",
      "drosophila melanogaster",
      "unknown"
    ],
    "synonyms": {
      "mouse": "mus musculus",
      "mice": "mus musculus",
      "mus": "mus musculus",
      "m. musculus": "mus musculus",
      "rat": "rattus norvegicus",
      "rats": "rattus norvegicus",
      "r. norvegicus": "rattus norvegicus",
      "macaque": "macaca mulatta",
      "rhesus": "macaca mulatta",
      "zebrafish": "danio rerio",
      "fly": "drosophila melanogaster",
      "fruit fly": "drosophila melanogaster"
    },
    "isDate": false
  },
  {
    "key": "strain",
    "hint": "e.g. C57BL/6J",
    "required": false,
    "enumValues": null,
    "synonyms": {},
    "isDate": false
  },
  {
    "key": "sex",
    "hint": "F, M, or unknown once checked",
    "required": true,
    "enumValues": [
      "F",
      "M",
      "unknown"
    ],
    "synonyms": {
      "female": "F",
      "f": "F",
      "fem": "F",
      "male": "M",
      "m": "M",
      "unk": "unknown",
      "n/a": "unknown",
      "na": "unknown",
      "?": "unknown"
    },
    "isDate": false
  },
  {
    "key": "date_of_birth",
    "hint": "YYYY-MM-DD",
    "required": false,
    "enumValues": null,
    "synonyms": {},
    "isDate": true
  },
  {
    "key": "genotype",
    "hint": "e.g. WT",
    "required": false,
    "enumValues": null,
    "synonyms": {},
    "isDate": false
  },
  {
    "key": "source",
    "hint": "Where the animal came from",
    "required": false,
    "enumValues": null,
    "synonyms": {},
    "isDate": false
  },
  {
    "key": "notes",
    "hint": "Anything that does not fit elsewhere",
    "required": false,
    "enumValues": null,
    "synonyms": {},
    "isDate": false
  }
];

export const PROCEDURE_FIELDS: GeneratedField[] = [
  {
    "key": "procedure_id",
    "hint": "Your own label for this procedure",
    "required": false,
    "enumValues": null,
    "synonyms": {},
    "isDate": false
  },
  {
    "key": "subject_id",
    "hint": "Identifier for this animal, e.g. M123",
    "required": true,
    "enumValues": null,
    "synonyms": {},
    "isDate": false
  },
  {
    "key": "procedure_date",
    "hint": "YYYY-MM-DD",
    "required": true,
    "enumValues": null,
    "synonyms": {},
    "isDate": true
  },
  {
    "key": "procedure_type",
    "hint": "What was done",
    "required": true,
    "enumValues": [
      "surgery",
      "injection",
      "implant",
      "lesion",
      "drug",
      "stimulation",
      "training",
      "perfusion",
      "other",
      "unknown"
    ],
    "synonyms": {
      "viral injection": "injection",
      "virus injection": "injection",
      "aav": "injection",
      "craniotomy": "surgery",
      "probe implant": "implant",
      "electrode implant": "implant",
      "cannula": "implant",
      "headplate": "implant",
      "headbar": "implant",
      "ip injection": "drug",
      "i.p.": "drug",
      "perfusion/fixation": "perfusion",
      "transcardial perfusion": "perfusion"
    },
    "isDate": false
  },
  {
    "key": "target_region",
    "hint": "e.g. CA1",
    "required": false,
    "enumValues": null,
    "synonyms": {},
    "isDate": false
  },
  {
    "key": "construct_or_drug",
    "hint": "What was delivered",
    "required": false,
    "enumValues": null,
    "synonyms": {},
    "isDate": false
  },
  {
    "key": "dose",
    "hint": "e.g. 300 nL",
    "required": false,
    "enumValues": null,
    "synonyms": {},
    "isDate": false
  },
  {
    "key": "notes",
    "hint": "Anything that does not fit elsewhere",
    "required": false,
    "enumValues": null,
    "synonyms": {},
    "isDate": false
  }
];

export const SESSION_FIELDS: GeneratedField[] = [
  {
    "key": "subject_id",
    "hint": "Identifier for this animal, e.g. M123",
    "required": true,
    "enumValues": null,
    "synonyms": {},
    "isDate": false
  },
  {
    "key": "session_date",
    "hint": "YYYY-MM-DD",
    "required": true,
    "enumValues": null,
    "synonyms": {},
    "isDate": true
  },
  {
    "key": "session_type",
    "hint": "What kind of recording",
    "required": false,
    "enumValues": [
      "electrophysiology",
      "calcium imaging",
      "behaviour",
      "histology",
      "surgery",
      "training",
      "other",
      "unknown"
    ],
    "synonyms": {
      "ephys": "electrophysiology",
      "e-phys": "electrophysiology",
      "electrophys": "electrophysiology",
      "electrophysiology recording": "electrophysiology",
      "lfp": "electrophysiology",
      "spikes": "electrophysiology",
      "imaging": "calcium imaging",
      "ca imaging": "calcium imaging",
      "ca2+ imaging": "calcium imaging",
      "2p": "calcium imaging",
      "two-photon": "calcium imaging",
      "miniscope": "calcium imaging",
      "behavior": "behaviour",
      "behavioral": "behaviour",
      "behavioural": "behaviour",
      "histo": "histology",
      "surgical": "surgery"
    },
    "isDate": false
  },
  {
    "key": "task",
    "hint": "e.g. linear track",
    "required": false,
    "enumValues": null,
    "synonyms": {},
    "isDate": false
  },
  {
    "key": "qc_status",
    "hint": "Whether this session passed your checks",
    "required": false,
    "enumValues": [
      "pass",
      "fail",
      "review",
      "unknown"
    ],
    "synonyms": {},
    "isDate": false
  },
  {
    "key": "notes",
    "hint": "Anything that does not fit elsewhere",
    "required": false,
    "enumValues": null,
    "synonyms": {},
    "isDate": false
  }
];

/** The date form the standard asks for, and refuses to guess at. */
export const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
