# LanPC (Python)

A desktop in the browser, hosted from one machine and usable from any device on your LAN.

## Run
Needs Python 3.8+. No packages required (standard library only).

    python server.py        # Windows
    python3 server.py       # macOS / Linux

It prints addresses like `http://192.168.1.20:8080`. Open one on any device on the same network.

Option: `PORT=9000` changes the port. `pip install psutil` (optional) improves CPU/memory stats on macOS.

## First start
The first device to open LanPC runs setup: create the account (user name + password), pick a theme, install.
Then restart and sign in. Do this yourself right after starting the server, because whoever opens it first creates the account.

## Settings
- **Appearance:** six themes, saved on the server.
- **Account:** display name for chat on this device, change password (signs other devices out).
- **System:** Restart, Shut down, Stop server.
- **Data:** Destroy all data deletes every shared file, the chat history and the account, then returns to first-time setup. Needs your password.

## Power
- **Restart:** plays the boot animation and returns to the sign-in screen.
- **Shut down:** black screen on this device. Press Enter 3 times to turn it on (tap 3 times on touch screens).
- **Stop server:** stops `server.py` for every device. Start it again from the host machine.

## Files
Shared files live in `shared/`. The account is stored in `system/config.json` (password stored as a salted hash).

## Notes
- If other devices can't connect, allow Python through your firewall on private networks.
- Traffic is plain HTTP, so use it only on a network you trust.


## Built-in apps added
- **Media:** plays images, video and music from the shared drive. Upload goes into `shared/Media/`.
- **Files:** New file creates an empty file in the current folder. Terminal also has `touch`.
- **Code:** a VS Code-style workspace over the shared drive (explorer, tabs, save, preview, AI panel).
- **AI Hub:** chat that calls OpenRouter. The API key is saved only in this browser and is sent only to OpenRouter.

## App Store
More offline apps (Pomodoro, passwords, flashcards, budget, weather, and others) and games (2048, Minesweeper, Breakout, Hangman, Simon, Tetris, and others). Install from the store to pin them on the desktop.
