#!/bin/zsh
# Restarts the background Cipher service, e.g. after updating the code.
launchctl kickstart -k "gui/$(id -u)/com.voiceorb.server" && echo "Restarted."
