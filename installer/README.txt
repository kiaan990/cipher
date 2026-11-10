VOICE ORB: HOW TO INSTALL
=========================

1. Double-click "Install Cipher".

2. The first time, macOS says it can't verify the developer
   (this app isn't from the App Store). Click "Done", then:
   System Settings → Privacy & Security → scroll down →
   next to "Install Cipher was blocked", click "Open Anyway",
   then "Open Anyway" again and enter your Mac password.

3. Follow the steps. The installer:
   • installs the app and adds Cipher to your Dock
   • sets it up to run in the background (starts at login)
   • asks macOS for permissions: click OK on each prompt, and switch ON
     "node" when System Settings opens (Accessibility, Screen Recording)
   • opens Chrome to add the Cipher Bridge extension

Needs Node.js 20 or newer (the installer tells you if it's missing).

Running the installer again updates Cipher and keeps your memories.
It also stops any older copy of Cipher (e.g. one started with "npm start").

SOMETHING NOT RIGHT, OR SLOW?
Double-click "Cipher Diagnostics" (right-click → Open the first time).
It checks the Mac, the network and Cipher itself, runs a short live
test, and saves a report to your Desktop (no keys or passwords in it).
AirDrop the report to whoever is helping you.

PRIVATE: this installer contains your API keys. Don't share it.
