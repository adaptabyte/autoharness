---
name: gnome-mines
description: "Guide to recognizing board state and operating a Mines game through its window when playing a small minefield."
license: CC-BY-SA-4.0
metadata:
  app: "GNOME Mines"
  matches: "gnome-mines"
  platforms: "Linux"
  updated: "2026-11-03"
  made-by: "Autoharness: Muse Spark used the app on the screen"
  proven: "learned: a program written from this passed 5/5 runs on its own, 2026-11-03"
---

# GNOME Mines

## What it is
GNOME Mines is a Minesweeper-style game in a single centered window. The board is on the left and center of the window. A side panel on the right shows a flag counter under a flag icon, a timer under a clock icon, and a vertical stack of buttons.

## Controls
| Input | What it does | Status |
|---|---|---|
| Left-click covered square | Reveals square; first click of a game is safe and opens an area | seen on screen |
| Right-click covered square, once | Places flag and increments flag counter | seen on screen |
| Right-click flagged square, again | Changes flag to question-mark; question-mark does not count toward flag counter | seen on screen |
| Right-click question-mark square, again | Returns square to covered with no mark | seen on screen |
| Left-click flagged square | Does nothing | seen on screen |
| Click Start Over in side panel | Restarts same difficulty during a game; disabled when board is fresh, enabled while playing | seen on screen |
| Click Play Again in side panel | Starts a new game after win or loss | seen on screen |
| Click Pause in side panel | Pauses game and shows Paused overlay | seen on screen |
| Click Resume in Paused overlay | Returns to in-progress game | seen on screen |
| Click Change Difficulty in side panel or overlay | Opens difficulty choice | seen on screen |
| Click Best Times in side panel after game ends | Opens Best Times dialog with ranking table | seen on screen |
| Press Escape | Closes Congratulations or Best Times dialog; does not pause game | seen on screen |
| Click Done or X in dialog | Closes Congratulations or Best Times dialog | seen on screen |

## How to do common jobs
- Start a guaranteed fresh game yourself: if side panel shows Play Again, click Play Again. If a Congratulations or Best Times dialog is visible, close it with Escape or Done / X, then click Play Again. If game is in progress, click Start Over. If Paused overlay is visible, click Resume then Start Over. If board is all covered, still use Start Over or Play Again to ensure a new layout rather than continuing a prior board.
- Reveal safely: left-click covered squares. Use number clues to decide.
- Flag suspected mines: right-click once only. Avoid double right-click because second click removes the counted flag and leaves only a question-mark.
- Track progress: flag counter on the right shows flagged count out of total mines for the minefield. Timer on the right runs while playing and stops when game ends.
- Tell in-game vs ended: in-game side panel shows Start Over and Pause. Ended side panel shows Play Again and Best Times instead. Button labels are the reliable state signal.
- Handle pause: if a large overlay with Paused text covers the board area, click Resume in that overlay. Do not click outside the Mines window to recover.
- Handle win: all safe squares revealed and mines flagged. Timer stops, side panel switches to ended buttons, plus a modal Congratulations dialog appears over the window with title, result line, minefield description, Rank / Time / Player table, editable Player field, Done button and X. Close it with Done or Escape / X before starting next game.
- Handle loss: exploded mine shown in red with other mines revealed as dark starbursts on grey, timer stops, side panel switches to ended buttons, no popup dialog. Start next game with Play Again.
- Check after every move for win or loss by looking for dialog appearance, side-panel button change, and presence or absence of red / revealed mine icons.

## How it behaves
- Board is all covered grey raised squares with light border when fresh. Timer shows zero and Start Over is disabled.
- While playing, revealed squares change appearance: empty with no adjacent mines becomes flat light grey, distinct from raised covered grey. Numbered clues have tinted backgrounds by value: low numbers greenish, middle numbers yellowish / beige, higher numbers orangish / peach, with dark digits.
- Flagged squares in play show a flag icon. Question-marked squares show flag plus question-mark and do not advance the counter.
- On win, mines remain flagged with dark cover and flag icons.
- On loss, mines are uncovered with starburst icons; the triggered mine has red background.
- Losing focus by clicking outside the window triggers the Paused overlay with Start Over, Change Difficulty, and Resume. The overlay hides the board until resumed.
- Mine positions are random for each new game. Board size, mine total, window layout, colors, and button order stay constant.

## Traps
- Never click outside the Mines window during play; it pauses the game and hides the board. Always stay inside the window and use Resume if paused.
- Escape does not pause or resume; it only closes dialogs. Use Pause button to pause and Resume button to resume.
- A single right-click flags; a second right-click uncounts it. Extra right-clicks lose flag count.
- Play Again is the top button in the ended state where Start Over was during play. Confusing the two or using image position alone causes mis-clicks; read button labels.
- A fresh-looking all-covered board may be leftover from before. Always start a new game in the current run before counting a win.
- Win requires confirmation on screen in the current run: either Congratulations dialog or ended buttons with flagged mines and no red mine. Do not declare success from board appearance alone before the move.

## Not known yet
- Full contents of Change Difficulty options.
- Background colors for higher clue numbers beyond those seen.
- Whether clicking an already revealed number chords or does anything.
- Exact Best Times persistence behavior across restarts.
