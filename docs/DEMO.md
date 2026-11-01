# Demo script: 3 minutes

The video is the primary judging artifact. Everything shown must be real and built during the event.
Replace every `[measured]` with a number from your own run. Leave out any claim you did not capture on camera.

## Before recording

1. Start Glimmer: `bash serve/serve_glimmer.sh`, and wait for `Glimmer ready` in the app.
2. Start the app: `.venv-app/bin/python -m autoharness serve`.
3. **View the app from this machine, or from another one on your LAN that doesn't need the internet.**
   If you watch it over Tailscale or anything else that uses the internet, pulling the cable kills your view too.
   Unplug the rig's *WAN uplink* (router to modem) if your laptop reaches the rig through the same router.
   Glimmer's workers now use loopback, so a cable pull shouldn't hurt it, but **this hasn't been tested with a real cable yet. Rehearse it.**
4. Do one full dry run of the cable pull.
5. Clear the leftover test patients first, so the patient list looks clean on camera: from `scripts/openemr`, run `sudo docker compose down -v && sudo docker compose up -d`.

## Numbers measured so far

Yours to use, as long as your own recording shows the same. Re-measure anything you put on screen. All of these come from `docs/BENCHMARK.md`, and the home page shows the same table.

- OpenEMR, one new patient: Glimmer + the program **5/5, 111 s, $0** against Spark alone **5/5, 286 s, $0.16**. A written guide gets Glimmer to **5/5, 165 s**. Taught once for **$1.02**, paying back in about 6 runs.
- Minesweeper: Glimmer + the program **5/5, 48 s**. Glimmer with a guide **0/3**. Spark **0/2** at a **$0.40** limit that I chose, so say that. Spark has won before at $0.28 in 277 s.
- Calculator: the program **5/5, 3 s**. Spark **4/5, 24 s, $0.022**. **Don't race Calculator**: Spark is so cheap there that a lesson takes dozens of runs to pay back.
- Jobs it was never taught: Glimmer + the program **0/3, and it said so**. Spark **3/3**. Say this out loud; it's what makes the rest believable.
- One screenshot costs Glimmer **1,321 tokens**. Calculator's state costs about **22**.
- **Don't claim the clinic job works.** Prior authorization failed its test (`docs/PRIORAUTH.md`). Don't claim a harness grows on request either (`docs/GROW.md`).
- **Don't demo repair on OpenEMR.** Under a smaller window it broke, Wonder spent $0.56, and the repair still failed. It asked for a person and the proven code came back, which is the right ending but not a success.
- Recorded footage is in `clips/`. `race-mines-full.webm` is the fair medium-effort race. `race-mines.webm` has Spark at low effort, so don't use it as a comparison. `teach-openemr.mp4` is the real OpenEMR lesson's saved frames, sped up. There's only $0.61 left under the $30 limit, which isn't enough for a new lesson on camera, so use this.

## The cut

| Time | On screen | You say |
|---|---|---|
| 0:00 | `race-mines-full.webm`. Left counter climbing. Right side finishing again and again. | "Same app, same goal. On the left, a frontier model looks at every screen, the way AI agents work today. On the right is a program that model wrote for itself." |
| 0:15 | Final race numbers. | "It finished [measured] times while the frontier model finished once. That cost [measured]. This cost nothing in the cloud." |
| 0:25 | Home page, top. | "Every app on earth was built for human eyes and hands. Nobody is going to rebuild them all. So we let the model build its own way in." |
| 0:35 | `teach-openemr.mp4`. | "I gave Meta's models an app they had never seen, with no instructions. Muse Spark explores it and works out how it behaves. Muse Wonder writes the interface they wish the app had." |
| 1:00 | An app's page: proof runs passing. | "It isn't allowed to mark its own homework. The program has to pass on fresh copies with no cloud, and a separate model that never saw the code judges the result." |
| 1:15 | "Two interfaces" view. Point at the token numbers. | "Here's the app we built for people. Here's the interface the model built for itself. One look at the screen costs Glimmer [measured] tokens. This costs about [measured]." |
| 1:35 | Ask Glimmer in plain words. It calls verbs. The app moves. | "Glimmer runs on this box. It has never seen this screen." |
| 1:50 | **Reach over and pull the cable, in one shot, with the pill turning to `Internet off`.** Keep it going. | "And it doesn't need the internet." |
| 2:05 | Home page: the benchmark table. | "So is this better than computer use? I measured it. On a records system, 111 seconds and no cloud, against 286 seconds and 16 cents. Could it just be a markdown skill? On forms, nearly: a guide gets the small model there in 165 seconds. On a game that takes logic, the guide went 0 for 3 and this went 5 for 5. And it only knows what it was taught: on new jobs it stops and says so, and Spark wins those." |
| 2:35 | OpenEMR: Glimmer registers a made-up patient from a plain-English request, then show the patient list. | "I'm a psychiatrist, and most software that runs clinics has no API. Teach it once on made-up patients, and the work can happen on your own machine. It isn't ready for real patients, and every failure is in the repo." |
| 2:50 | Repo: `test_no_app_specific_code`. | "No hand-written code for any app, and a test enforces that. Computer use becomes the compiler, not the runtime." |

## Don't

- Don't say "free" without "cloud cost": electricity and the GPU are real.
- Don't say "replaces computer use": the learning phase is computer use.
- Don't show real patient data, or imply this is ready for it. Nothing here has been clinically or legally reviewed.
- Don't demo an online game with an anti-cheat or a policy against automation.
- Say which parts were built with Claude Code. Judges have to be able to tell what's new, and hiding it risks disqualification.

## The X post

> AI agents pay a genius to click buttons.
>
> So I made Meta's Muse Spark teach itself an app it had never seen, build its own interface to it, and hand the job to a tiny model on my PC.
>
> Then I pulled the ethernet cable. It kept going. (Only post this line after you've done it on camera.)
>
> Same records-system job: 286 s and $0.16 → 111 s and $0.00 in cloud. Every run and failure in the repo.

Attach the race clip. Submit the post link on the hackathon platform: Most Viral counts likes, reposts and comments through Nov 8.
