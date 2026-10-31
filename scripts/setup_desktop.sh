#!/usr/bin/env bash
# The virtual screen and sample apps. With sudo, install them normally. Without it, unpack them for this user only.
set -euo pipefail
PKGS="xvfb openbox gnome-mines"
if sudo -n true 2>/dev/null; then
  sudo apt-get install -y $PKGS
else
  ROOT="$HOME/.local/autoharness-sys"; mkdir -p "$ROOT/debs" "$ROOT/root" "$ROOT/patched"
  cd "$ROOT/debs"
  apt-get download $PKGS libgnome-games-support-1-3 libgnome-games-support-common dconf-gsettings-backend libdconf1 libobt2v5 libobrender32v5 libimlib2t64 libid3tag0 2>/dev/null
  for f in *.deb; do dpkg -x "$f" "$ROOT/root"; done
  glib-compile-schemas "$ROOT/root/usr/share/glib-2.0/schemas"
  # gnome-mines hard-codes where its art lives. Point it at an equally long path that can be a user-owned link.
  python3 - "$ROOT" <<'PY'
import os, sys
root = sys.argv[1]
binary = open(f"{root}/root/usr/games/gnome-mines", "rb").read()
open(f"{root}/patched/gnome-mines", "wb").write(binary.replace(b"/usr/share/gnome-mines", b"/tmp/.ahs/gnome-mines0"))
os.chmod(f"{root}/patched/gnome-mines", 0o755)
open(f"{root}/patched/links.txt", "w").write(f"/tmp/.ahs/gnome-mines0 {root}/root/usr/share/gnome-mines\n")
PY
fi
# A real browser for web targets.
python -m playwright install chromium
echo "Ready."
