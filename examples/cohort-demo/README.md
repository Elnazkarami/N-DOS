# A cohort query, with all three answers

Four sessions, four animals, one question. The point is the third group.

```bash
ndos table check examples/cohort-demo/metadata --emit linked.json --include-empty
ndos query linked.json -w species=mouse -w sex=F -w 'target_region~CA1'
```

The output is committed beside this file as
[`query-output.txt`](query-output.txt), so you can read the result without
running anything. A test regenerates it and fails if it drifts.

## Why each animal lands where it does

| Animal | Outcome | Why |
| --- | --- | --- |
| `M101` | **matched** | Mouse, female, CA1 injection — every criterion satisfied by recorded evidence |
| `M102` | **excluded** | A rat. Recorded evidence contradicts the query |
| `M103` | **cannot be ruled out** | Mouse, CA1 injection, but sex is `unknown` — somebody checked the cage card and it was not there |
| `M104` | **cannot be ruled out** | Nothing was ever entered for this animal. It may well qualify |

`M103` and `M104` are the reason this tool exists. A query that returned only
matched and excluded would report **1 of 4** and look clean. The truth is 1
matched and 2 undecidable, and the two are undecidable for different reasons:

- `M103` was **checked and could not be determined** — the value is `unknown`.
- `M104` was **never filled in** — the value is absent.

The specification requires those to stay distinguishable (§7), because
treating either as "not a mouse" biases the cohort towards whichever animals
happened to have fuller records, and reports no sign of having done so.

The query also prints what would fix it:

> 2 sessions could not be ruled in or out, blocked by: sex (2), species (1),
> target_region (1). Treating them as non-matches would bias this cohort, so
> they are listed separately.

That is a list of three cells to fill in, not a dead end.
