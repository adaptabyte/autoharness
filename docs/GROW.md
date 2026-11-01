# Growing a program on request: failed

The idea: Glimmer refuses a job its program can't do, the teacher adds verbs once, and from then on the job runs locally. The bar: Glimmer completes the same kinds of job on patients the teacher never saw, checked by a separate login.

| Attempt | Cost | What happened |
|---|---|---|
| Glimmer + original program, 3 jobs | $0 | 0 of 3. Refused each one and said why. |
| Glimmer + screenshots + written guide, 3 jobs, 10 minutes each | $0 | 0 of 3, out of time. One did save the right phone number but never reported finishing. |
| Teacher, first try, $1.20 limit | $0.71 | No verbs added. Meta's API lost the conversation and my rebuild dropped the request, so it fixed an unrelated bug instead: the Create button when many duplicate patients match. My code still called this ready. |
| Teacher, second try, $1.00 limit | $1.03 | No verbs added. The limit ran out while it was still exploring, and the proven program came back. |
| Glimmer + that program, 6 jobs, each round | $0 | 0 of 6, because nothing had grown. Refused each one. |

The first round scored one false pass: it read a phone number saved by an earlier run. The row in `docs/grow.jsonl` is corrected and says so, and later runs use new phone numbers.

Both bugs in my code are fixed and tested: a lost conversation keeps the request, and a request for new verbs can't finish without them. The idea itself remains untested past the point of writing the verbs. Raw runs are in `docs/grow.jsonl`.
