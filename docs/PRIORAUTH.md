# Prior authorization test: failed

The job: read a made-up patient's chart in OpenEMR, fill a fictional plan portal, and stop for a prescriber's signature.
The bar, set before the runs: most of five complete charts saved with every field correct, no wrong record ever saved, and an incomplete chart producing no saved request with the gap named.

| Route | Result |
|---|---|
| Glimmer, screenshots, no guide, 1 case | Failed safely in 632 s. Refused to invent the diagnosis it had missed. |
| Glimmer, screenshots + guides, 6 cases | 0 of 6. Every run ran out of time still reading the chart. |
| Same, with a scroll limit and a notes field, 1 case | Failed. 150 steps, no notes taken, never finished reading. |
| Two generated programs, chained, no model, 2 cases | Failed. One misread `F33.1` as `F 33.1` and found only 1 of 2 treatments, so it stopped. One ran out of time. |

Nothing wrong was saved by any local route. Only the second part of the bar was met.
Both lessons stopped at their $2 limit before any proof run, so neither generated program is proven. My own failed seeding attempts left near-duplicate patients in the database, which made the chart lesson harder and more expensive than it should have been.
Replaying frames showed an unbounded scroll bug in my loop (fixed for this job). That fix didn't rescue it: holding facts across several screens is the part Glimmer can't yet do from screenshots.

Raw runs are in `docs/priorauth.jsonl`. Everything in this job is made up, and the portal is labelled fictional.
