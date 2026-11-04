# Demo: 3 minutes

The video is the main thing judges look at. Everything in it is a real run, and the numbers come from [PROOF.md](PROOF.md). If your recording shows a different number, say the number it shows.

`clips/draft.mp4` is a complete captioned cut, made from real runs by `scripts/make_clips.py` and `scripts/make_video.py`. You can submit it as it is. It's much stronger with your voice over it and your face in one shot (see "Only you can do").

## The story in five beats

1. **Hook:** the same small model went from 0 for 6 to 5 for 5, and the model didn't change.
2. **Problem:** software is built for people, and today's agents pay a frontier model at every click.
3. **Idea:** computer use is the compiler, not the runtime. Learn once, run locally, check everything.
4. **Proof:** it learns an app it has never seen, an agent calls the result as a tool, it's three commands to try, and the numbers hold up.
5. **Why it matters:** your own clinic paperwork, and the vision: by the models, for the models.

## Script

`clips/draft.mp4` runs 2:55 with burned-in captions, so it works without a voice. If you record one, speak at a normal pace over these times; it's about 460 words.

| Time | On screen | You say |
|---|---|---|
| 0:00 | **Swarm:** eight screens, all moving | "These are eight apps built for people, and nobody here is a person. It's one small open model, on my desk, with no cloud." |
| 0:06 | **Card:** 0 of 6 → 5 of 5 | "When I gave this model a whole job, reading a patient's chart, it went zero for six. Then a frontier model compiled that job for it, and it went five for five. The model didn't change." |
| 0:14 | **Cards:** the problem, then the idea | "I'm a psychiatrist, and a lot of my week goes into records systems and insurer portals that have no API. AI agents can use them, but they pay a frontier model to look at a screenshot at almost every click. So I built a compiler." |
| 0:29 | **Home page** | "Meta's frontier models learn an interface once, and from then on a small open model runs it on my own computer." |
| 0:34 | **Teach:** the address and the job, Spark exploring, the plan | "Here's an app it has never seen. Muse Spark uses it once, Muse Wonder turns that into a plan, and Glimmer has to pass on its own before it's kept." |
| 0:58 | **Teach:** Learned | "That cost thirteen cents, once." |
| 1:03 | **Agent:** terminal and app | "Now it's a tool any agent can call. Spark is the agent here. It picks the job, the small model does the work on my machine, and Spark gets back the verified answer, never my screen or my password." |
| 1:21 | **Card:** plug and play | "One command teaches any app, even one on another computer." |
| 1:28 | **Card:** give it the manual | "Not just forms. This game's keys can't be guessed, so I gave it the manual. Wonder read it and told Spark what to check." |
| 1:35 | **Robots:** the program playing | "The program it wrote moves with exactly those keys, and it cleared the level five times out of five on its own." |
| 1:42 | **docsdb** | "What it learns becomes a guide that any agent can use." |
| 1:47 | **Run:** live screen and the checks | "The small model only answers one narrow question per screen. Code holds the memory and checks everything. A run ends verified, or it stops and asks." |
| 2:00 | **Results table** | "Thirty-five of thirty-five on inputs it hadn't seen, nothing wrong saved, and no cloud. Spark still does better on jobs it wasn't taught." |
| 2:11 | **One wrong digit** | "Paper is an interface too. One digit in this member ID differs between pages, so it brings both to me." |
| 2:24 | **Clean stack** | "A clean stack fills the insurer's portal and stops at the signature, because only a person signs." |
| 2:36 | **Card:** what it isn't | "It isn't ready for real patients. The records are made up, and every failure is in the repo." |
| 2:42 | **Card:** the vision | "Every interface was built for people. Now models build the version for models." |
| 2:48 | **End card:** the repo, the live demo, docsdb | "Autoharness. Built with Meta's Muse models. Claude Code wrote most of the code." |

## Before recording

```bash
cd ~/muse && source .venv-app/bin/activate
autoharness up        # starts the app, the made-up portal and Django admin, and Glimmer if it isn't running
autoharness check     # every line should be ✓ before you record
```

OpenEMR has to be up on :8300. Its patient list has leftover test patients. To clean it, run `cd scripts/openemr && sudo docker compose down -v && sudo docker compose up -d`, then `.venv-app/bin/python scripts/priorauth/seed_chart.py` and `.venv-app/bin/python scripts/priorauth/seed_chart.py cases2.json`.

Watch the app on this machine or over your LAN, not over Tailscale. Otherwise pulling the cable cuts your view too. **The cable pull hasn't been tested with a real cable, so do one dry run first.** The draft is 2:55 and the limit is 3:00, so a cable-pull shot has room for at most 5 seconds. Glimmer's status is checked every 2 seconds, so pull the cable right as the shot starts.

To rebuild the draft from fresh recordings: `.venv-app/bin/python scripts/make_clips.py home teach agent`, then `.venv-app/bin/python scripts/make_video.py`. Recording `teach` spends about $0.20 of real API budget.

## Only you can do

These take about 20 minutes, and they do more for the entry than anything else left:

1. **Your voice** over the script above. A person who has the problem is more convincing than any narration.
2. **The cable pull**, filmed in one shot with your phone, with the screen visible.
3. **Your face for about ten seconds** at 0:16: "I'm a psychiatrist." That credibility is the point.
4. **Real pen and paper.** This is optional but strong. Print [print-and-fill.pdf](print-and-fill.pdf), fill it in by hand for the made-up patient, change one digit on the order form, photograph the pages, and drop them in on camera. All my tests use fonts and simulated damage, so this would be the first real handwriting it has seen. Try it before you film. If it fails, leave it out and tell me what it did.

## Don't

- Don't say "free" without "in the cloud". The electricity and the GPUs are real.
- Don't say "error-free". Say it finishes verified or stops and asks, and add "in these tests".
- Don't say it "replaces computer use". Computer use is how it learns.
- Don't imply a plan can handle jobs it wasn't taught. Spark does better on those.
- Don't show real patient data, or imply it's ready for it.
- Don't say it's more accurate than Spark. Spark passed every job here too.
- Don't say the swarm is faster. On this rig it isn't, really: about 34 jobs an hour at 8 at once, against about 30 one at a time. Use the swarm to show that copies don't get mixed up.
- Do say that Claude Code wrote most of the code. Judges must be able to tell what was built during the event and how, and leaving it unclear risks disqualification.
