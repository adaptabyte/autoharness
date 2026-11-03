# Agents calling compiled interfaces

Every compiled job is a tool, served over the [Model Context Protocol](https://modelcontextprotocol.io) at `http://127.0.0.1:4140/mcp/ui`. The calling agent only picks the job and its inputs. The job itself runs on this computer: Muse Glimmer operates the real interface, and plain code checks every step. The agent gets back only what the plan verified. It never sees a screenshot, and it never sees a login kept in `~/.autoharness/logins.json`.

In the runs below, the agent is Muse Spark, through [`scripts/ask.py`](../scripts/ask.py). The server was also tested with the official MCP Python SDK (2.3.0): `initialize`, `tools/list`, and a `tools/call` to `backoffice__read_order` that came back verified in 44 s. All records are made up.

## Results

| Request | What the agent did | Result | Checked against the app's own data | Agent's cloud cost |
|---|---|---|---|---|
| "Has order ORD-10530 shipped? And what's its total?" | Called the Django admin's `read_order` | Verified in 41 s | Number, customer and total match the database | $0.0048 |
| Renata Ashby's prior authorization, first try | Read her OpenEMR chart, then called the portal's `save_request` | Chart verified in 214 s. The portal job **stopped**, and nothing was saved | Nothing to check: nothing was saved | $0.0102 |
| Same request, after the fix below | Read the chart, then filed the request in the portal | Chart verified in 142 s. Portal saved PA-837691 in 159 s and **stopped for the prescriber's signature** | Every field in the saved request matches the made-up chart | $0.0161 |
| "What email and city do we have on file for Astrid Kowalczyk?" | Called `lookup_customer`, a Django job taught from the screen minutes earlier, on Theo Rasmussen only, for $0.13 | Verified in 34 s | Email and city match the database | $0.0041 |

The full transcripts are in [docs/agent/](agent/).

## What went wrong, and what the checks did

- **The agent asked a question the job can't answer.** The order lookup reads number, customer and total, not shipping status. Spark said so plainly, and didn't guess.
- **The agent sent `30.0` for a quantity.** The plan typed "30.0", the portal didn't accept it, and the next check failed ("Is step 3, Diagnosis, showing?"). The run stopped before saving anything. Whole numbers from a caller are now passed on as whole numbers, and the tool schema says "integer" (`test_a_whole_number_sent_as_a_float_is_typed_as_a_whole_number`).
- **The agent passed the wrong name.** On the run that succeeded, Spark first called the chart job with `{"first": "Renata Ashby", "last": "Ashby"}`. The plan didn't open the closest-looking patient. It stopped after 62 s: "the exact name 'Ashby, Renata Ashby' isn't a row in the results". Spark then called again with the right name.

## What it shows

- **Two apps with no API between them, joined by an agent.** The agent read a chart in one system and filed a request in another. It did that through jobs Wonder compiled from watching the screen, with no connector written by hand.
- **The small model did all the screen work.** The frontier model spent under two cents choosing jobs and inputs.
- **Mistakes from the agent end in a stop, not a wrong save.** These are four runs, not a benchmark, so read them as examples.

## Try it

```bash
.venv-app/bin/python scripts/ask.py "What's the total on order ORD-10530?"
```

To use it from another MCP client, add `http://127.0.0.1:4140/mcp/ui` as a streamable-HTTP server, or `http://127.0.0.1:4140/mcp/ui/<interface>` for a single interface. Jobs take 15 to 220 seconds, so give the client a tool timeout long enough for that.
