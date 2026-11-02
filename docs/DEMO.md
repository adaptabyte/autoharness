# Demo: 3 minutes

The video is the main judging artifact. Everything in it is a real run. Numbers come from [PROOF.md](PROOF.md). If your recording shows a different number, say the number your recording shows.

`clips/draft.mp4` is a complete captioned cut, made from real runs by `scripts/make_clips.py` and `scripts/make_video.py`. You can submit it as it is. It's much stronger with your voice and your face in two shots, listed under "Only you can do".

## Before recording

```bash
cd ~/muse
bash serve/serve_glimmer.sh                                   # wait for it to answer on :8001
.venv-app/bin/python scripts/priorauth/portal.py &            # the made-up portal, :8310
~/.autoharness/backoffice-venv/bin/python scripts/backoffice/run.py &   # the Django admin, :8320
.venv-app/bin/python -m autoharness serve                     # http://127.0.0.1:4140
```

OpenEMR has to be up on :8300. Its patient list has leftover test patients. To clean it: `cd scripts/openemr && sudo docker compose down -v && sudo docker compose up -d`, then `.venv-app/bin/python scripts/priorauth/seed_chart.py` and `.venv-app/bin/python scripts/priorauth/seed_chart.py cases2.json`.

Watch the app on this machine or over your LAN, not over Tailscale, or pulling the cable will cut your view too. **The cable pull hasn't been tested with a real cable. Do one dry run first.**

## The cut

| Time | On screen | You say |
|---|---|---|
| 0:00 | The swarm: eight screens, all moving | "Every one of these is an app built for human eyes and hands. Nobody on this screen is a person, and none of it is in the cloud. It's one small open model on my desk." |
| 0:12 | Home page | "AI agents today pay a genius to look at a screenshot and click a button. So I built a compiler. Give it any interface, and Meta's strongest models learn it once, then hand it to a small model for good." |
| 0:25 | `teach`: typing an address and a job, then Spark exploring | "I'll give it a Django admin it has never seen. No API and no instructions. Muse Spark uses it once, and everything it sees and does gets recorded." |
| 0:45 | `teach`: the plan appears | "Muse Wonder turns that into a plan. It isn't code, and it isn't a prompt. It's every decision made in advance, so the small model never has to think about what to do next." |
| 1:00 | `run`: live screen with the feed of checks | "Now Muse Glimmer runs it on my machine. It only ever answers one narrow question per screen. Where's this button? Is this the right page? What does this say? Code holds all the memory." |
| 1:20 | The feed: a read-back, and a compare | "And code checks everything. What it types gets read back. What it reads gets read twice. So a run ends verified, or it stops and asks. It doesn't quietly get it wrong." |
| 1:35 | **Pull the cable, in one shot.** The pill turns to `Internet off`. Keep it running | "And it doesn't need the internet." |
| 1:45 | The table from PROOF.md | "Is that as good as a frontier model? I measured it, with bars I committed before running. Reading a whole chart in a real records system: this same small model used to go 0 for 6. Now it's 5 for 5 on patients it's never seen, in 167 seconds and no cloud. Spark takes 218 seconds and 9 cents. On small jobs Spark's about as fast and costs cents, and it does better on anything it wasn't taught. So this is for repeated, long or private work." |
| 2:10 | `digit`: drop a stack, the disagreement side by side | "I'm a psychiatrist, and paper's an interface too. Here's a medication request with one wrong digit in a member ID. The pages disagree, so it comes to me. It doesn't pick one." |
| 2:30 | `clean`: approve, Glimmer fills the portal, stops at signature | "When I approve a clean stack, the same small model fills the insurer's portal, a compiled interface with no connector anyone wrote, and stops at the signature. Only a person can sign." |
| 2:45 | README: What failed | "It isn't ready for real patients. These are all made-up records and a small sample, and every failure's in the repo." |
| 2:52 | Home page | "Computer use becomes the compiler, not the runtime. For the models, by the models." |

## Only you can do

These take about 20 minutes and do more for the entry than anything else left:

1. **Your voice** over the script above. A person who has the problem beats any narration.
2. **The cable pull**, filmed in one shot with your phone, with the screen visible.
3. **Ten seconds of your face** at 2:10: "I'm a psychiatrist." The credibility is the point.
4. **Real pen and paper, optional but strong.** Print [print-and-fill.pdf](print-and-fill.pdf), fill it in by hand with the made-up patient, change one digit on the order form, photograph the pages, and drop them in on camera. All my tests use fonts and simulated damage, so this would be the first real handwriting it has seen. Try it before you film. If it fails, don't use it, and tell me what it did.

## Don't

- Don't say "free" without "in the cloud": electricity and the GPUs are real.
- Don't say "error-free." Say it either finishes verified or stops and asks. Say "in these tests."
- Don't say "replaces computer use." The learning phase is computer use.
- Don't imply the plan handles jobs it wasn't taught. Spark wins those.
- Don't show real patient data, or imply it's ready for it.
- Don't say it's more accurate than Spark. Spark also passed every job here.
- Say that Claude Code wrote most of the code. Judges must be able to tell what was built during the event and how, and hiding it risks disqualification.
