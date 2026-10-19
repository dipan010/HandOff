UDAA Project Handoff Context
Project Name: Universal Digital Accessibility Agent (UDAA)
Current Status: Version 1.0 (Live Browser Stable)
Last Updated: 2026-03-14

🚀 Mission Statement
HandOff helps people who find websites hard to use. It watches the browser tab through screenshots, asks Gemini what to do next, and carries out real browser actions (click, type, scroll) while narrating out loud.

🛠 Technical Architecture
The assistant works inside the user's own, signed-in Chrome.

- **Backend**: FastAPI (Python 3.11).
- **Frontend**: Next.js 15+ (TypeScript, Tailwind CSS).
- **Browser Control**: Chrome extension + Python `webbrowser` module. The backend opens a tab and the extension carries out actions inside the user's signed-in Chrome (Netflix, WhatsApp, etc.). The old Playwright "Remote mode" has been removed.
- **Models**:
    - **Actions**: `gemini-2.5-computer-use-preview-10-2025`.
    - **Narration**: `gemini-2.5-flash-native-audio-preview-12-2025` (via Gemini Live API).

💡 Key Features & Recent Fixes (CRITICAL)

1. **Live Browser Persistence**
   - Playwright was dropped to avoid OS-level file locks on the user's Chrome profile.
   - The backend now opens a standard Chrome tab with a `udaa_session_id` parameter. The extension auto-connects to the backend via WebSocket.

2. **Keystroke & Action Parsing**
   - Gemini's Computer Use model emits special strings like `backspace*11` or `control+a`.
   - The `content_script.js` now contains a robust parser to translate these strings into real DOM keyboard events and value deletions.
   - Coordinates are scaled from Gemini's 1000x1000 grid to the user's actual `window.innerWidth/Height`.

3. **UI Status Banner**
   - Added a persistent, dark-themed overlay banner in the active tab.
   - It pulses blue during actions and turns green upon task completion.
   - It works even on sites with strict Content Security Policies (CSP) via a fallback renderer in `content_script.js`.

⚙️ Environment Configuration
Ensure `backend/.env` has:
- `COMPUTER_USE_MODEL=gemini-2.5-computer-use-preview-10-2025`
- `LIVE_MODEL=gemini-2.5-flash-native-audio-preview-12-2025`
- `USE_FIRESTORE=false` (unless you have a Service Account key).

🤝 Collaboration Protocol
- **Start Backend**: `cd backend && python -m app.main` (inside the venv)
- **Run Tests**: `cd backend && python -m pytest`
- **Start Frontend**: `cd frontend && npm run dev`
- **Extension**: Load the `extension/` folder as an "Unpacked Extension" in Chrome.

📂 Check `task.md` for the current checklist status.