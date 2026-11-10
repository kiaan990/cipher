#!/bin/zsh
# Stops the background Cipher service and stops it starting at login.
LABEL="com.voiceorb.server"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "Stopped." || echo "It wasn't running."
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Cipher will no longer start by itself. (Your memories and settings are kept.)"
