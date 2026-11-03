---
name: gnome-robots
description: "Guide to operating GNOME Robots through its screen when starting games, moving, teleporting, waiting and clearing levels."
license: CC-BY-SA-4.0
metadata:
  app: "GNOME Robots"
  matches: "gnome-robots"
  platforms: "Linux"
  sources: "https://help.gnome.org/users/gnome-robots/stable/"
  updated: "2026-11-03"
  made-by: "Autoharness: Muse Wonder read the docs, Muse Spark checked them on the screen"
  proven: "learned: a program written from this passed 5/5 runs on its own, 2026-11-03"
---

# GNOME Robots

## What it is
GNOME Robots is a turn-based board game. You control a main character on a checkerboard field with enemy robots. The aim is to destroy all robots by getting them to crash into each other or into junk heaps from previous collisions, without a robot catching you. Play continues level by level until you are caught.

## Controls
| Input | What it does | Status |
|---|---|---|
| Menu button in top-right corner of window > New Game | Starts a new game | seen on screen |
| Ctrl+N | Asks to discard current game with options to keep playing or start a new game | seen on screen |
| y | Move one square northwest | seen on screen |
| k | Move one square north | seen on screen |
| u | Move one square northeast | seen on screen |
| h | Move one square west | seen on screen |
| l | Move one square east | seen on screen |
| b | Move one square southwest | seen on screen |
| j | Move one square south | seen on screen |
| n | Move one square southeast | seen on screen |
| Space | Stay in same square for one turn | from the docs |
| Alt+S | Teleport safely | from the docs |
| Alt+R | Teleport randomly | from the docs |
| Alt+W | Wait for the robots | from the docs |
| Mouse click around main character | Move one square in the shown direction | from the docs |
| Click on main character | Stay put in same square | seen on screen |
| Teleport Randomly button at bottom-left of window | Teleport to a random spot, only the player moves | seen on screen |
| Teleport Safely button in bottom-center of window | Teleport to a safe spot; disabled when none remain, with remaining count shown | the screen showed disabled with Remaining: 0 at start of a game set to robots2 type, which disagrees with docs that list a starting safe teleport for that type |
| Wait for Robots button at bottom-right of window | Let enemy robots finish all their moves | seen on screen |
| High-score dialog Done button | Closes dialog and auto-starts a new first level | seen on screen |
| Discard dialog Keep Playing / New Game buttons | Keep current game or discard it and start fresh | seen on screen |
| Escape with Preferences open | Closes Preferences dialog | seen on screen |
| Ctrl+Q | Quit the game | from the docs |
| Preferences > Game tab: Game Type, Use safe moves, Use super safe moves, Enable sounds | Changes rules, difficulty and sound | seen on screen |
| Preferences > Keyboard tab, Restore Defaults | Shows and resets movement and action keys | seen on screen |

## How to do common jobs
1. Start a new game with the menu button in the top-right > New Game, or Ctrl+N and confirm to discard the current game with New Game, or keep it with Keep Playing.
2. Check the board before moving: blue-gray checker board in center of window, main character near the center, enemy robots scattered, junk heaps if collisions have happened. Positions are random each new game.
3. Check header at top of window for Level and Score, and bottom buttons for Teleport Safely remaining count before planning.
4. Move one adjacent square per turn including diagonally, using letter keys, so pursuing robots run into each other or into junk. Clicking the player stays put for one turn.
5. After each of your moves, enemy robots take a turn moving toward you.
6. Use Wait for Robots when waiting is wanted to let robots finish moves, Teleport Safely when a safe jump is wanted and teleports remain, Teleport Randomly when a random jump is wanted. Random teleport moves only the player; robots stay where they were.
7. Repeat moving, waiting and teleporting until all robots on the level are destroyed without one reaching you.
8. Confirm level cleared by header showing next Level with live player and fresh robots and continued Score; level play continues without manual restart.
9. If caught, the player signals being caught with a speech bubble, controls grey out, a high-score dialog appears, then Done starts a fresh first level.
10. Check and set options first in Preferences > Game tab and Appearance settings if available, and in Preferences > Keyboard tab if movement keys do not respond as expected. The screen showed Game Type robots2, Use safe moves checked, Use super safe moves checked, sounds checked, with keyboard defaults intact for all eight directions and hold position.

## How it behaves
- Turn-based: after each player move or wait, enemy robots move closer to the player by stepping toward the player.
- In one turn you can move to any adjacent square including diagonally, or stay put.
- Collisions between robots, or a robot hitting a junk heap, destroys those robots and creates or leaves a junk heap. Junk looks distinct from live robots as orange starburst-like shapes versus green-red robot sprites in the observed theme.
- Score increases as robots are destroyed.
- Safe teleports are limited per game and the remaining count is shown on the Teleport Safely button; the button is disabled when none remain. The screen showed none remaining at the start of a game set to robots2 type, which disagrees with docs that list a starting safe teleport for that type.
- Random teleports go to a random spot that may not be safe, are unlimited, and move only the player. The screen showed only the player changes position; robots stay where they were.
- Game types change starting enemies and safe teleports. Docs list types including nightmare, robots2, robots with safe teleport, classic robots, and robots2 easy, with different mixes of low-risk and high-risk enemies and safe teleports. The screen showed Game Type set to robots2, while a later high-score dialog named a different game type; treat the on-screen dialog as not matching Preferences.
- Use safe moves, if checked, blocks a move that would let a robot kill you unless only teleporting can survive. Use super safe moves, if checked, forces teleport in that case. The screen showed both checked. A refused keyboard move leaves the board unchanged, so another move must be tried.
- Scores are recorded separately for each combination of game type and safe-move option, per docs.
- Image theme and background can change appearance; the screen showed a blue-gray checker board with green-red robot sprites and orange starburst-like junk.
- Keyboard bindings are customizable and defaults match the documented letter keys; the screen showed defaults intact for all eight directions and hold position.
- Level transition is automatic: clearing all robots advances the header to the next Level with a live player and a new set of robots.

## Traps
- Waiting is not advisable unless very few robots remain and you are sure they will all perish before reaching you.
- Random teleport destination may not be safe.
- Safe teleports are limited; confirm remaining count on the button before relying on them. Do not assume a safe teleport is available at start for robots2; the screen showed none remaining.
- Keyboard controls can be remapped, so do not assume defaults without checking Preferences > Keyboard tab.
- If Use safe moves or Use super safe moves is checked, some moves may be blocked and teleporting may be forced.
- Changing Game Type changes difficulty, starting enemies and safe teleports; confirm it before a run.
- Mouse direction arrow on hover around the character was documented but not observable during the lesson; do not rely on seeing it in screenshots.
- High-score dialog game-type text may not match the type shown in Preferences; confirm current type in Preferences rather than the dialog.
- A dialog overlaying the board can hide the player; identify high-score, discard, dead, or preferences state before trying to move.

## Not known yet
- How the game visually signals a cleared level beyond header advancing to the next Level with fresh robots.
- Exact board size in squares and exact starting layout beyond random placement with player near center.
- Visual distinction between high-risk and low-risk enemies in the observed theme, where all robots looked the same.
- Details of safe-move blocking behavior in play beyond refusing fatal moves.
- Whether Alt shortcuts and Space to stay work as documented, as they were not tested on screen.
- Exact robot step rules, diagonal collision rules, and junk-heap formation rules beyond crashing into each other or junk heaps.
- How many safe teleports are granted in later levels for each game type.

## Sources

- https://help.gnome.org/users/gnome-robots/stable/
