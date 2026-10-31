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
4. Do one full dry run of the race and the cable pull. Teaching takes a while, so record it once and speed it up.

## Numbers measured so far

Yours to use, as long as your own recording shows the same. Re-measure anything you put on screen.

- Minesweeper, taught from nothing: **$1.56, 45 minutes**, 5 of 5 judged proof runs, 2 of 2 Glimmer-alone runs.
- Harness against Spark on Minesweeper: typically **about 45 s at $0.00** against **277 s at $0.28** when Spark won. Spark
  is inconsistent: at medium effort another race gave no win in 14 minutes for $0.56, and at low effort none in 10 minutes.
  The harness isn't perfect either: 2 of 22 race laps hung until their time limit (laps are now capped at 3 minutes). Race laps report their own success; only proof runs are judged.
- That pays back the lesson in about 6 runs. **Don't race Calculator**: Spark does that in 17 s for $0.018, which takes 59 runs to pay back.
- One screenshot costs Glimmer **1,321 tokens**. Calculator's state costs about **22**.
- OpenEMR, taught from nothing with Wonder writing the code: **$1.02, 31 minutes**, 4 of 5 judged proof runs (one failed on `Could not find field label 'Name:'`), 2 of 2 Glimmer-alone runs.
- OpenEMR, one new patient: about **86 s at $0.00** against Spark alone at **223 s and $0.16**, so about 6 runs to pay back. A patient it had never seen appeared in OpenEMR's own patient list. Glimmer did the same from a plain-English request in 118 s, 3 steps, mostly through the single `register_patient` verb.
- **Don't demo repair on OpenEMR.** In a smaller window it broke, Wonder spent $0.56 on a repair, and that still failed. It asked for a person and the proven code came back, which is the right ending but not a success.
- Self-repair on Calculator (Spark as teacher, so say so): a dark theme broke it, Spark found "the = key changed from orange to blue" and fixed it for **$0.11** in the same run.
- Recorded races are in `clips/`. `race-mines-full.webm` is the fair medium-effort race. `race-mines.webm` has Spark at low effort, so don't use it as a comparison.

## The cut

| Time | On screen | You say |
|---|---|---|
| 0:00 | Race screen already running. Left counter climbing. Right side finishing again and again. | "Same app, same goal. On the left, a frontier model looks at every screen, the way AI agents work today. On the right is a program that model wrote for itself." |
| 0:15 | Final race numbers. | "It finished [measured] times while the frontier model finished once. That cost [measured]. This cost nothing in the cloud." |
| 0:25 | Home page. | "Every app on earth was built for human eyes and hands. Nobody is going to rebuild them all. So we let the model build its own way in." |
| 0:35 | Teach view, sped up: live screen, cost meter, program appearing. | "I gave Meta's models an app they had never seen, with no instructions. Muse Spark explores it and works out how it behaves. Muse Wonder writes the interface they wish the app had." |
| 1:00 | Proof runs passing. | "It isn't allowed to mark its own homework. The program has to pass on fresh copies with no cloud, and a separate model that never saw the code judges the result." |
| 1:15 | "Two interfaces" view. Point at the token numbers. | "Here's the app we built for people. Here's the interface the model built for itself. One look at the screen costs Glimmer [measured] tokens. This costs about [measured]." |
| 1:35 | Ask Glimmer in plain words. It calls verbs. The app moves. | "Glimmer runs on this box. It has never seen this screen." |
| 1:50 | **Reach over and pull the cable, in one shot, with the pill turning to `Internet off`.** Keep it going. | "And it doesn't need the internet." |
| 2:05 | Calculator, run with "Change the app under it". It breaks, then Spark repairs it once for [measured]. | "When software changes, it can call its teacher back once and fix itself. Here that worked. When it can't, it asks a person." Only claim what your recording shows. |
| 2:25 | OpenEMR: Glimmer registers a made-up patient from a plain-English request, then show the patient list. | "I'm a psychiatrist. Minesweeper isn't the point. Most software that runs clinics has no API, and my staff and I lose hours inside it. Teach it once on made-up patients, and the real ones never leave the building." |
| 2:45 | Repo: `test_no_app_specific_code`. Library of apps. | "There's no hand-written code for any app in this repo, and a test enforces that. Computer use becomes the compiler, not the runtime. For the models, by the models." |

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
> Then I pulled the ethernet cable. It kept going.
>
> Cost per run: $[measured] → $0.00 in cloud

Attach the race clip. Submit the post link on the hackathon platform: Most Viral counts likes, reposts and comments through Nov 8.
