#!/usr/bin/env bash
# Keeps the live demo up while judging runs. Cron calls it every 5 minutes, and it starts whatever has stopped: the app,
# Glimmer, the made-up demo apps, the demo and its tunnel, and the stand-in game screen. It does nothing if all is up.
#
#   (crontab -l; echo "*/5 * * * * $HOME/muse/scripts/demo_watchdog.sh") | crontab -     # install
#   touch ~/.autoharness-demo/watchdog.off                                                # pause it
#
# It stops by itself after AUTOHARNESS_WATCH_UNTIL (2026-11-17, the day after the community vote), so it can't outlive
# the judging and start Glimmer on GPUs you've since given to something else.
set -u
cd "$(dirname "$0")/.." || exit 1
UNTIL="${AUTOHARNESS_WATCH_UNTIL:-2026-11-17}"
[[ "$(date +%F)" > "$UNTIL" ]] && exit 0
[ -f "$HOME/.autoharness-demo/watchdog.off" ] && exit 0
mkdir -p "$HOME/.autoharness-demo/logs"
exec >>"$HOME/.autoharness-demo/logs/watchdog.log" 2>&1
APP=.venv-app/bin/autoharness
note() { echo "$(date -Is) $*"; }

# Lost on a reboot: where the unpacked game finds its data, and the stand-in screen the Minesweeper tool plays on.
[ -e /tmp/autoharness-robots ] || ln -sfn "$HOME/.local/autoharness-sys/root/usr/share/gnome-robots" /tmp/autoharness-robots
if ! ss -ltn | grep -q ':5912 '; then
  note "game screen down: starting it"
  setsid .venv-app/bin/python scripts/vnc_box.py --port 5912 --password playtime --size 1280x800 gnome-mines --small >/dev/null 2>&1 &
fi

# The app, the made-up demo apps and Glimmer: `up` starts only what isn't running.
if ! curl -s -o /dev/null -m 5 http://127.0.0.1:4140/api/state || ! curl -s -o /dev/null -m 5 http://127.0.0.1:8001/v1/models; then
  note "app or Glimmer down: autoharness up"
  $APP up --tailscale >/dev/null 2>&1
fi

# The demo and its tunnel.
if $APP demo status | grep -q "not running"; then
  note "demo or tunnel down: autoharness demo up"
  $APP demo up >/dev/null 2>&1
fi
