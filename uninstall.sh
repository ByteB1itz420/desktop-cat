#!/usr/bin/env bash
# Remove the Desktop Cat service and launcher (keeps your settings unless --purge).
systemctl --user disable --now desktop-cat.service 2>/dev/null
rm -f ~/.config/systemd/user/desktop-cat.service ~/.local/bin/desktop-cat
systemctl --user daemon-reload
if [ "$1" = "--purge" ]; then
  rm -rf ~/.config/desktop-cat ~/.local/share/desktop-cat ~/.cache/desktop-cat
  echo "Removed Desktop Cat and all its data."
else
  echo "Removed Desktop Cat. Settings kept in ~/.config/desktop-cat (use --purge to delete them)."
fi
