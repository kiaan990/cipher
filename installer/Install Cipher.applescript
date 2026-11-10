-- Install Cipher: copies the app, sets up the background service and the Dock app,
-- then walks through macOS permissions and the Chrome extension.

property appURL : "http://localhost:3000"
property title : "Cipher"

on run
	set res to (path to me as text) & "Contents:Resources:"
	set iconFile to alias (res & "applet.icns")
	set installer to POSIX path of (res & "install.sh")

	-- 1. Welcome
	display dialog "This installs Cipher on this Mac:" & return & return & ¬
		"• the Cipher app (in your Dock and Applications)" & return & ¬
		"• a background service, so it's always ready" & return & ¬
		"• permissions so it can control your Mac" & return & ¬
		"• the Chrome extension, so it can use Chrome" & return & return & ¬
		"It takes about two minutes." buttons {"Cancel", "Install"} default button "Install" cancel button "Cancel" with title title with icon iconFile

	-- 2. Install files, service and app
	try
		do shell script "/bin/zsh " & quoted form of installer
	on error errMsg number errNum
		if errNum is 3 then
			set choice to button returned of (display dialog "Cipher needs Node.js (version 20 or newer), which isn't on this Mac yet." & return & return & ¬
				"Download the macOS installer from nodejs.org (the \"LTS\" version), install it, then open Install Cipher again." buttons {"Cancel", "Open nodejs.org"} default button "Open nodejs.org" with title title with icon caution)
			if choice is "Open nodejs.org" then open location "https://nodejs.org/en/download"
		else
			display dialog "Installation didn't finish:" & return & return & errMsg buttons {"OK"} default button 1 with title title with icon stop
		end if
		return
	end try

	-- 3. Permissions
	set choice to button returned of (display dialog "Installed. Next: permissions, so Cipher can control this Mac." & return & return & ¬
		"macOS will ask a few times whether \"node\" may control other apps: click OK each time." & return & return & ¬
		"Then System Settings opens twice. Each time, switch ON \"node\" in the list, and come back here." buttons {"Skip", "Continue"} default button "Continue" with title title with icon iconFile)
	if choice is "Continue" then my setUpPermissions(iconFile)

	-- 4. Chrome extension
	if my hasChrome() then
		set choice to button returned of (display dialog "Last step: the Chrome extension, so Cipher can read your email and use websites for you." & return & return & ¬
			"Chrome's Extensions page will open, and the extension's folder location will be copied." & return & return & ¬
			"1. Turn on \"Developer mode\" (top right)." & return & ¬
			"2. Click \"Load unpacked\"." & return & ¬
			"3. Press Cmd+Shift+G, then Cmd+V, then Return, then Select." & return & return & ¬
			"It connects by itself: no code to paste." buttons {"Skip", "Open Chrome"} default button "Open Chrome" with title title with icon iconFile)
		if choice is "Open Chrome" then my setUpChrome(iconFile)
	end if

	-- 5. Done
	display dialog "Cipher is ready." & return & return & ¬
		"Open it from the Dock any time. It starts by itself when you log in." & return & return & ¬
		"You can check permissions later in Cipher → Settings → Mac permissions." buttons {"Open Cipher"} default button 1 with title title with icon iconFile
	do shell script "open " & quoted form of (POSIX path of (path to home folder) & "Applications/Cipher.app")
end run

on setUpPermissions(iconFile)
	-- Automation: macOS shows its "node wants to control…" prompts while this runs.
	my request("automation")
	-- Accessibility and Screen Recording: opens System Settings at the right list.
	if not my request("accessibility") then
		display dialog "In System Settings → Privacy & Security → Accessibility:" & return & return & ¬
			"switch ON \"node\" (enter your Mac password if asked), then click Done." buttons {"Done"} default button 1 with title title with icon iconFile
	end if
	if not my request("screen") then
		display dialog "In System Settings → Privacy & Security → Screen & System Audio Recording:" & return & return & ¬
			"switch ON \"node\", then click Done. (If macOS offers \"Quit & Reopen\", choose Later.)" buttons {"Done"} default button 1 with title title with icon iconFile
	end if
	-- Screen Recording applies to programs started after it's switched on.
	do shell script "launchctl kickstart -k gui/$(id -u)/com.voiceorb.server >/dev/null 2>&1 || true"
	my waitUntilUp()
	set s to do shell script "curl -s -m 40 -H 'x-voice-orb: 1' " & appURL & "/api/permissions || true"
	set lines to "Control apps: " & my mark(s, "automation") & return & ¬
		"Click and type: " & my mark(s, "accessibility") & return & ¬
		"See the screen: " & my mark(s, "screen")
	display dialog "Permissions:" & return & return & lines & return & return & ¬
		"Anything not ticked can be finished later in Cipher → Settings → Mac permissions." buttons {"Continue"} default button 1 with title title with icon iconFile
end setUpPermissions

on request(which)
	try
		set r to do shell script "curl -s -m 120 -X POST -H 'x-voice-orb: 1' " & appURL & "/api/permissions/" & which
		return r contains "\"granted\":true"
	on error
		return false
	end try
end request

on mark(statusJSON, which)
	if statusJSON contains ("\"" & which & "\":true") then return "✓ on"
	return "✗ not yet"
end mark

on waitUntilUp()
	repeat 40 times
		try
			do shell script "curl -s -m 1 -o /dev/null " & appURL & "/healthz"
			return
		end try
		delay 0.5
	end repeat
end waitUntilUp

on hasChrome()
	return (do shell script "test -d '/Applications/Google Chrome.app' && echo yes || echo no") is "yes"
end hasChrome

on setUpChrome(iconFile)
	set extFolder to POSIX path of (path to home folder) & "Library/Application Support/Voice Orb/app/chrome-extension"
	set the clipboard to extFolder
	do shell script "open -a 'Google Chrome' 'chrome://extensions/'"
	display dialog "In Chrome:" & return & return & ¬
		"1. Turn on \"Developer mode\" (top right)." & return & ¬
		"2. Click \"Load unpacked\"." & return & ¬
		"3. Press Cmd+Shift+G, then Cmd+V, then Return, then Select." & return & return & ¬
		"Click Done when \"Cipher Bridge\" appears in the list." buttons {"Done"} default button 1 with title title with icon iconFile
	set connected to false
	repeat 30 times
		try
			if (do shell script "curl -s -m 2 " & appURL & "/api/status") contains "\"chrome\":true" then
				set connected to true
				exit repeat
			end if
		end try
		delay 1
	end repeat
	if connected then
		display dialog "Chrome extension connected. ✓" buttons {"Continue"} default button 1 with title title with icon iconFile
	else
		display dialog "The extension hasn't connected yet. If \"Cipher Bridge\" is in Chrome's list, it will connect within a minute. If it isn't, check Developer mode is on and try Load unpacked again." & return & return & ¬
			"Folder: " & extFolder buttons {"Continue"} default button 1 with title title with icon caution
	end if
end setUpChrome
