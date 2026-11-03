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
| "Has order ORD-10530 shipped? If so, what's the tracking number?" | Called `orders__read_order`, taught from the terminal with one `autoharness teach` command for $0.14, because no job could answer this in the first run | Verified in 35 s: shipped, TRK942213 | Status and tracking match the database | $0.0069 |

The full transcripts are in [docs/agent/](agent/).

## What went wrong, and what the checks did

- **The agent asked a question the job can't answer.** The order lookup reads number, customer and total, not shipping status. Spark said so plainly, and didn't guess.
- **The agent sent `30.0` for a quantity.** The plan typed "30.0", the portal didn't accept it, and the next check failed ("Is step 3, Diagnosis, showing?"). The run stopped before saving anything. Whole numbers from a caller are now passed on as whole numbers, and the tool schema says "integer" (`test_a_whole_number_sent_as_a_float_is_typed_as_a_whole_number`).
- **The agent passed the wrong name.** On the run that succeeded, Spark first called the chart job with `{"first": "Renata Ashby", "last": "Ashby"}`. The plan didn't open the closest-looking patient. It stopped after 62 s: "the exact name 'Ashby, Renata Ashby' isn't a row in the results". Spark then called again with the right name.

## A gap, closed with one command

In the first run, Spark was asked whether ORD-10530 had shipped, and said plainly that no job could tell it. So the job was taught from the terminal ([transcript](agent/5-taught-from-the-terminal.txt)):

```bash
autoharness teach http://127.0.0.1:8320/admin/ "Log in with username manager and password demo-pass. Open order ORD-10530 and report its status and tracking number." --name orders
```

Spark explored the admin once, Wonder wrote the plan, and Glimmer passed on its own: 141 s and $0.14, once. The login went into `~/.autoharness/logins.json`, not into the tool. The new tool, `orders__read_order(order_number)`, then read two orders it wasn't taught on, and both matched the database: ORD-26616 (Shipped, TRK953690) and ORD-40632 (New, with no tracking number, read back as empty). Asked the same question again, Spark called the new tool and answered "Yes — ORD-10530 has shipped. Tracking: TRK942213" ([transcript](agent/6-asked-again.txt)).

## What it shows

- **Two apps with no API between them, joined by an agent.** The agent read a chart in one system and filed a request in another. It did that through jobs Wonder compiled from watching the screen, with no connector written by hand.
- **The small model did all the screen work.** The frontier model spent under two cents choosing jobs and inputs.
- **A missing job is one command away.** What an agent can't do yet, a person can teach in plain words, and the agent uses it on the next request.
- **Mistakes from the agent end in a stop, not a wrong save.** These are five runs, not a benchmark, so read them as examples.

## Try it

```bash
autoharness call orders__read_order order_number=ORD-26616        # one job, from the terminal
.venv-app/bin/python scripts/ask.py "Has order ORD-10530 shipped?"  # Muse Spark as the agent
autoharness connect                                                 # settings for any other MCP client
```

Any MCP client can use `http://127.0.0.1:4140/mcp/ui` (streamable HTTP), or start `autoharness mcp` (stdio). Both were tested with the official MCP Python SDK. Jobs take 15 s to a few minutes, and most clients give up on a call after 60 s. So a call still running after 50 s answers with a job id, the job keeps going, and the agent collects the result with the `wait_for_job` tool. A client that can wait longer can add `?wait=600` to the address.
