# docsdb

Guides to apps, one per app, written by Autoharness from real use and checked on the real screen. Browse them at [adaptabyte.github.io/autoharness/docsdb](https://adaptabyte.github.io/autoharness/docsdb/), which will also be served at autoharness.adaptabyte.com/docsdb.

Each guide is `docsdb/<name>/SKILL.md`, an [Agent Skill](https://agentskills.io): a name, a one-sentence description, and then the guide.

- **What it is:** two sentences.
- **Controls:** each one marked "seen on screen", "from the docs", or with what the screen showed instead.
- **How to do common jobs.**
- **How it behaves.**
- **Traps.**
- **Not known yet.**

## How guides get here

1. Someone teaches Autoharness a job in the app: `autoharness teach <address> "<the job>" --docs <manual>`. The lesson writes or updates the guide on their computer.
2. They run `autoharness share <name>`. They see the whole guide and what it changes here, and nothing is sent without their yes.
3. It arrives as a pull request. The `docsdb` check runs on it. A person reads it before merging.
4. Merging rebuilds the site.

## What a guide never holds

These never go in a guide:

- Anything typed or read during a lesson: inputs, logins, or values seen on the screen.
- People, patients, customers, records or accounts.
- Network addresses, hostnames, file paths, keys or tokens.
- HTML or script.

The model that writes a guide never sees the lesson's inputs. Code removes what it can recognise. The check refuses anything that still looks private, and the reviewer looks again.

## Reviewing a pull request

- Does every point describe the app, not one person's use of it?
- Are instructions plain facts about the interface? Refuse any guide that tells an agent to send, type or reveal anything beyond what the job needs. Guides become instructions for other people's agents.
- Is the name the app's, in lowercase with hyphens, like `gnome-robots`?

Guides are shared under CC BY-SA 4.0, because the docs they're built from often are.
