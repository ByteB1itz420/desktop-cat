#!/usr/bin/env bash
# Desktop Cat installer: installs dependencies and an always-on systemd user service.
set -e
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

have() { command -v "$1" >/dev/null 2>&1; }
deps_ok() {
  python3 - <<'PY' 2>/dev/null
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, GtkLayerShell
import cairo
PY
}

if ! deps_ok; then
  echo "Installing dependencies (needs sudo)…"
  if have pacman; then
    sudo pacman -S --needed gtk-layer-shell python-gobject python-cairo gtk3
  elif have apt-get; then
    sudo apt-get update && sudo apt-get install -y gir1.2-gtklayershell-0.1 python3-gi python3-gi-cairo python3-cairo gir1.2-gtk-3.0
  elif have dnf; then
    sudo dnf install -y gtk-layer-shell python3-gobject python3-cairo gtk3
  elif have zypper; then
    sudo zypper install -y typelib-1_0-GtkLayerShell-0_1 python3-gobject python3-gobject-cairo gtk3
  else
    echo "Couldn't detect your package manager. Please install: gtk-layer-shell, PyGObject, pycairo, GTK 3."
    exit 1
  fi
  deps_ok || { echo "Dependencies still missing. See README for manual install."; exit 1; }
fi

case "${XDG_SESSION_TYPE:-}" in
  wayland) ;;
  *) echo "⚠️  Desktop Cat needs a Wayland session with wlr-layer-shell (Hyprland, Sway, river, niri, KDE Plasma…)." ;;
esac

mkdir -p ~/.local/bin ~/.config/systemd/user
ln -sf "$DIR/desktop-cat" ~/.local/bin/desktop-cat
cat > ~/.config/systemd/user/desktop-cat.service <<UNIT
[Unit]
Description=Desktop Cat 🐱
StartLimitIntervalSec=0
PartOf=graphical-session.target
After=graphical-session.target

[Service]
WorkingDirectory=$DIR
ExecStart=/usr/bin/env python3 -m catpet.app
Restart=always
RestartSec=2

[Install]
WantedBy=graphical-session.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now desktop-cat.service
echo
echo "🐾 Desktop Cat is running and will start at every login."
echo "   Hold or right-click a cat for its menu.  Control: desktop-cat menu|treat|pet|play|focus|hide|show"
echo "   Stop:      systemctl --user stop desktop-cat"
echo "   Uninstall: ./uninstall.sh"
if ! systemctl --user is-active --quiet graphical-session.target; then
  echo
  echo "ℹ️  Your session doesn't use graphical-session.target, so autostart may not trigger."
  echo "   Add 'desktop-cat' to your compositor's autostart instead (e.g. Hyprland: exec-once = desktop-cat)."
fi
