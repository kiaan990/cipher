-- Cipher: opens the app in its own window. Makes sure the background service is
-- running first (it normally is: it starts when you log in).
on run
	set appURL to "http://localhost:3000"
	if not my isUp(appURL) then
		do shell script "launchctl kickstart gui/$(id -u)/com.voiceorb.server >/dev/null 2>&1 || true"
		repeat 40 times
			if my isUp(appURL) then exit repeat
			delay 0.5
		end repeat
	end if
	if not my isUp(appURL) then
		display dialog "Cipher's background service isn't running." & return & return & "Open \"Install Cipher\" again to repair it." buttons {"OK"} default button 1 with icon caution with title "Cipher"
		return
	end if
	if (do shell script "test -d '/Applications/Google Chrome.app' && echo yes || echo no") is "yes" then
		-- Its own window, without tabs or an address bar.
		do shell script "open -na 'Google Chrome' --args --app=" & appURL & " --window-size=1280,860"
	else
		open location appURL
	end if
end run

on isUp(appURL)
	try
		do shell script "curl -s -m 1 -o /dev/null " & appURL & "/api/status"
		return true
	on error
		return false
	end try
end isUp
