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

Speak at a normal pace. The times match `clips/draft.mp4`, which runs 2:58. The script is about 450 words, or 150 a minute.

| Time | On screen | You say |
|---|---|---|
| 0:00 | **Swarm:** eight screens, all moving | "These are eight apps built for people, and nobody here is a person. It's one small open model, on my desk, with no cloud." |
| 0:06 | **Card:** 0 of 6 → 5 of 5 | "When I gave this model a whole job, reading a patient's chart, it went zero for six. Then a frontier model compiled that job for it, and it went five for five. The model didn't change." |
| 0:14 | **Cards:** the problem, then the idea. Or your face, if you film it | "I'm a psychiatrist, and a lot of my week goes into records systems and insurer portals that have no API. AI agents can use them, but they pay a frontier model to look at a screenshot at almost every click. That's slow, every run costs money, and my screen goes to the cloud." |
| 0:32 | **Home page** | "So I built a compiler. Meta's frontier models learn an interface once, and from then on a small open model runs it on my own computer." |
| 0:37 | **Teach:** typing the address and the job | "Here's an app it has never seen. I give it the address and the job, in plain words." |
| 0:44 | **Teach:** Spark exploring, then the plan | "Muse Spark uses it once, and everything gets recorded. Muse Wonder turns that into a plan, with every decision made in advance. Then Glimmer has to pass on its own before the plan is kept." |
| 1:03 | **Teach:** Learned | "That cost thirteen cents, once." |
| 1:09 | **Agent:** terminal on the left, the app on the right | "And now it's a tool any agent can call. Here Muse Spark is the agent, asking about a customer the plan was never taught on. It picks the job, and the small model does the work on my machine. Spark gets back the verified answer, never my screen and never my password." |
| 1:31 | **Card:** plug and play | "Plug and play: one command teaches any app, even one on another computer, and any agent connects with one line." |
| 1:38 | **Run:** live screen and the feed of checks | "The small model only answers one narrow question per screen. Code holds the memory and checks everything. What it types gets read back, and what it reads gets read twice. A run ends verified, or it stops and asks." |
| 1:54 | **Cable pull, in one shot,** in place of the 4-second "$0.00 in the cloud" shot. The pill turns to `Internet off`, and it keeps running | "And it doesn't need the internet." |
| 1:58 | **Results table** | "I measured it, with pass bars set before the runs: thirty-five of thirty-five on inputs it hadn't seen, nothing wrong saved, and no cloud. Spark still does better on jobs it wasn't taught." |
| 2:10 | **One wrong digit:** a stack is read, and two values come up side by side | "Paper is an interface too. This medication request has one wrong digit in a member ID. The pages disagree, so instead of picking one, it brings both to me." |
| 2:25 | **Clean stack:** approve, the portal fills, it stops at the signature | "A clean stack fills the insurer's portal and stops at the signature, because only a person signs." |
| 2:38 | **Card:** what it isn't | "It isn't ready for real patients. The records are made up, the samples are small, and every failure is in the repo." |
| 2:45 | **Card:** the vision | "Every interface was built for people. Now models build the version for models. By the models, for the models." |
| 2:52 | **End card** | "Autoharness. Built with Meta's Muse models. Claude Code wrote most of the code." |

## Before recording

```bash
cd ~/muse && source .venv-app/bin/activate
autoharness up        # starts the app, the made-up portal and Django admin, and Glimmer if it isn't running
autoharness check     # every line should be ✓ before you record
```

OpenEMR has to be up on :8300. Its patient list has leftover test patients. To clean it, run `cd scripts/openemr && sudo docker compose down -v && sudo docker compose up -d`, then `.venv-app/bin/python scripts/priorauth/seed_chart.py` and `.venv-app/bin/python scripts/priorauth/seed_chart.py cases2.json`.

Watch the app on this machine or over your LAN, not over Tailscale. Otherwise pulling the cable cuts your view too. **The cable pull hasn't been tested with a real cable, so do one dry run first.** The draft is 2:58 and the limit is 3:00, so the cable-pull shot has to replace the 4-second "$0.00 in the cloud" shot at 1:54, not add to it. Glimmer's status is checked every 2 seconds, so pull the cable right as the shot starts.

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
