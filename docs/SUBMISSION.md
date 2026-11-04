# Submission kit

Everything here is ready to paste. Deadline: **Wed Nov 4, 9 PM ET**. Check each field against the live form, because I could only go by the rules you shared.

## The message, in one place

Use the same words everywhere: the form, the video, the README, X. Repeating one message is what makes judges remember it.

| | |
|---|---|
| **Name** | Autoharness |
| **Tagline** | Any interface, compiled for a small model. |
| **Hook** | AI agents pay a genius to click every button. |
| **Thesis** | Computer use should be the compiler, not the runtime. |
| **Proof in one line** | Same small model, same job: 0 for 6 given the whole job, 5 for 5 compiled. |
| **Three beats** | Learn once. Run locally. Check everything. |
| **Vision** | Every interface was built for people. Now models build the model-facing version themselves. By the models, for the models. |

Rules for every claim:
- Say "no silent errors" or "it ends verified or stops and asks", never "error-free".
- Say "no cloud at run time", never "free".
- Say it matched Spark's pass rate, never that it beat Spark on accuracy.
- Attach "made-up records" to every medical example.

## One line (under 140 characters)

Meta's frontier models learn any app once. Then a small open model runs it on your computer, as a tool any agent can call.

## Short description (about 50 words)

Autoharness compiles any interface for a small model. Muse Spark uses an app once, and Muse Wonder turns that into a plan. From then on, open-weight Muse Glimmer runs the job on your own computer, with every step checked. Each job is also a tool any agent can call over MCP. Across 35 runs on four kinds of interface, nothing wrong was saved.

## Full description

Nearly every interface was built for human eyes and hands: records systems, insurer portals, back offices, desktop apps. Nobody is going to rebuild them all for AI. Today's agents cope by sending a frontier model a screenshot at almost every step. That's slow, it costs money on every run, and everything on your screen goes to the cloud.

Autoharness uses computer use as a compiler instead of a runtime. Muse Spark uses an interface once, and everything it does is recorded. Muse Wonder compiles that record into a plan: data, not code, with every decision made in advance. Then open-weight Muse Glimmer runs the plan on your own computer. It answers one narrow question per screen, while plain code holds the memory and checks every step. What it types gets read back, and what it reads gets read twice. A run ends verified, or it stops and asks. Every compiled job is also an MCP tool, so any agent can use apps that never had an API. The agent gets back only verified results, never your screen or your login.

It's plug and play. `autoharness up` starts it and checks what's ready. `autoharness teach <address> "<the job, in plain words>"` teaches a new job, and `autoharness call` runs one. Any MCP client connects with one line, by address or by command, and a job still running after 50 seconds hands back a job id, so clients with a 60-second limit still work. When Muse Spark, acting as an agent, was asked whether an order had shipped, no job could tell it. One `teach` command fixed that in 141 seconds for $0.14, and Spark then answered correctly.

It reaches apps on other computers too. The address can be a web address, a Linux app's command, or `vnc://` for a Windows PC, a Mac or a game machine, using the screen sharing they already have. Spark reads the job and picks how to learn it: a plan when the same steps work every time, or a program, written by Muse Wonder, when each move depends on the screen. Pointed at Minesweeper on another screen over VNC with one command, Spark chose a program. For $1.24, once, it then won five of five fresh games on its own with no cloud, and now it's a tool like any other. VNC was tested here against a Linux server; Mac and Windows servers speak the same protocol but weren't tested, and nothing that needs fast reflexes will work.

It can start from the manual. `--docs` takes a PDF, a picture of the controls, or a link to a help site. Muse Wonder reads it all once and tells Spark what to check, so Spark confirms the documented controls instead of trying every key. Given the online manual for GNOME Robots, a game whose keys can't be guessed, the program it wrote moved with exactly the documented keys and cleared level 1 in five of five runs on its own. Learning it cost $1.96, once. Every lesson then leaves a guide to the app, an Agent Skill, which the next lesson on that app reads first. With the person's yes, a guide joins docsdb, a shared library at autoharness.adaptabyte.com/docsdb, after a person reviews it. Then anyone's lesson on that app starts from it, and any agent that takes skills can load it. Nothing typed or read during a lesson goes into a guide.

The finding that makes this work: the same small model went 0 for 6 reading a chart in OpenEMR when given the whole job, and 5 for 5 on unseen patients once the job was compiled. Across OpenEMR, a made-up insurer's portal, a Django admin and a native desktop calculator, it passed 35 of 35 runs on the final code and saved nothing wrong. It matched Muse Spark's pass rate with no cloud at run time. On the portal it was 3.5 times faster, 157 seconds against 556.

I'm a psychiatrist. In the demo, a medication request where one page has a member ID off by one digit comes to me side by side. A clean stack fills the insurer's portal and stops at the signature.

It isn't ready for real patients. All data is made up, the samples are small, and Spark is still better at jobs it wasn't taught. Pass bars were committed to git before each test, and every failure is in the repo.

## Track and prizes

**Track: Build for Your World.** Lead with the clinic story. Impact is worth the most points, and you're the person who has the problem.

Enter every prize the rules allow. Ask in Discord whether one project can compete for several:

| Prize | Why it fits |
|---|---|
| **Indie** | The whole product |
| **Open Weight** | Run time is entirely open-weight Muse Glimmer, on your own GPUs |
| **Agentic** | Models build tools for models. Spark acts as an agent, calling compiled apps over MCP, and a job it lacked was taught with one command |
| **Community Vote** | The 0/6 → 5/5 story and the clinic demo travel well |
| **Most Viral** | X posts below |

## How Meta's models are used

- **Muse Spark 1.3:** explores each interface through computer use, and judges the final screen while teaching. It's also the example agent that calls compiled jobs over MCP (`scripts/ask.py`).
- **Muse Wonder 1.0:** compiles what Spark did into a plan, repairs the plan from failed runs, and designs reading plans for new paperwork.
- **Muse Glimmer**, open weights, served by vLLM on four 16 GB GPUs: runs every job at run time, with no cloud. A plan never needs another model.

## Built during the event

All of it. The repo's history shows the work from Oct 28 on. I directed it, and Claude Code wrote most of the code. No Claude model runs in the product.

## Links

- Repo: https://github.com/adaptabyte/autoharness
- Proof, including every failed round: https://github.com/adaptabyte/autoharness/blob/master/docs/PROOF.md
- Video: yours to upload. `clips/draft.mp4` is a complete captioned cut.
- Live demo, for judges: https://demo.adaptabyte.com. Put the user name and password only in the field that judges alone see. If the platform has no private field, send them to the organisers instead of putting them in the public description.
- docsdb, the shared guides: https://autoharness.adaptabyte.com/docsdb/

Text for the judges' private field:

> Try it live at https://demo.adaptabyte.com. User name: judge. Password: (from `autoharness demo password`). Pick anything under "Try one it already learned" and watch a small model run it on my GPUs, for free. Or teach it something new on any public website, with or without a manual (`Add docs`). One lesson runs at a time, at most $1.50 each. Please don't use real accounts.

## X posts

Post the main one with the video or `clips/teaser.mp4` (49 s, now with the Robots game). Only claim what the video shows. **Check first:** the participant guide said Most Viral counts engagement "after the Event", so ask in Discord whether posts before Nov 4 count.

Main post:

> AI agents pay a genius to click every button.
>
> So I had Meta's frontier models learn an app once and compile it. Now a small open model runs it on my own PC, and every step is checked.
>
> Same small model, same job (reading a medical chart, made-up patients):
> Given the whole job: 0 for 6
> Compiled: 5 for 5

Reply 1, with the agent clip:

> Every compiled job is also a tool. Here Muse Spark asks for a customer's email. A small model does the work in the app, on my machine. Spark gets the verified answer back, and never sees the screen or the password.

Reply 2:

> 35 of 35 runs on inputs it hadn't seen: OpenEMR, an insurer portal, a Django admin and a desktop app. Nothing wrong saved. Bars were committed before the runs, and every failure is in the repo: [repo link]

Reply 3:

> I'm a psychiatrist. I built this during the Meta AI hackathon, with Claude Code writing most of the code. Computer use should be the compiler, not the runtime.

Reply 4, if there's room:

> Plug and play: `autoharness teach <address> "<the job, in plain words>"`, and the job becomes a tool any MCP client can call. Teaching a Django admin to report an order's shipping status took 141 s and $0.14, once. Every run after that: $0 in the cloud.

Reply 5, if there's room:

> Not just forms. Point it at a game on another computer over VNC, and Spark sees that a fixed plan won't do: each move depends on the board. So Muse Wonder writes a program instead. It won 5 of 5 fresh games on its own, with no cloud. One command.

Reply 6, the strongest for "any app":

> Give it the manual. GNOME Robots' keys can't be guessed: y k u h l b j n. Muse Wonder read the help site and told Spark what to check, and the program it wrote moves with exactly those keys. Level 1 cleared in 5 of 5 runs on its own. What a lesson learns becomes a guide any agent can use: autoharness.adaptabyte.com/docsdb

If you filmed the cable pull, add this to the main post: "Then I pulled the ethernet cable. It kept going."

## Before you press submit

1. The repo is public, and `master` has the final work.
2. The video is under 3 minutes and says that Claude Code wrote most of the code.
3. There's no real patient data anywhere. The repo has none, but check anything you add, including your own photos.
4. Don't link the Tailscale address or token anywhere.
5. The live demo is up (`autoharness demo status`), and Glimmer is loaded. Keep both running until judging ends, and don't switch those GPUs to another model in the meantime.
6. The judge password is only in the private field. After judging, revoke the demo's API key and run `autoharness demo down`.
