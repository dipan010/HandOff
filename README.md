# Universal Digital Accessibility Agent (HandOff) ☸️

**HandOff** is an assistant that acts as the "hands on screen" for people who find websites hard to use. You tell it what you want; it clicks, types and scrolls in your own Chrome while describing out loud what it is doing. It uses **Gemini 2.5 Computer Use** to decide what to do on screen and **Gemini Live (native audio)** to talk you through it.

Built for the **Gemini Live Agent Challenge** under the **UI Navigator** category.

---

## 🌟 Key Features

- **Works in your own browser**: A Chrome extension lets HandOff operate the Chrome you already use, so sites where you are signed in (Netflix, YouTube, WhatsApp) just work.
- **Patience Mode 🐢**: When enabled, the agent slows down its reaction time and waits longer for pages to settle—ideal for slow connections or heavy sites.
- **Grandparents Mode 👵**: Replaces technical logs with warm, first-person narration (e.g., "I'm looking for your recipe now!").
- **Reads the screen from screenshots**: Decides where to click from screenshots using `gemini-2.5-computer-use-preview`.
- **Real-Time Narration**: Summarizes every action as it happens via `gemini-2.5-flash-native-audio`.
- **Asks before risky actions**: HandOff stops and asks you before payments, sign-ins and other sensitive steps.

---

## 🛠 Tech Stack

- **Models**: Gemini 2.5 Computer Use (actions), Gemini Live native audio (narration)
- **Frontend**: Next.js 15, TypeScript, Tailwind CSS
- **Backend**: FastAPI, Python 3.11
- **Browser control**: Chrome Manifest V3 extension
- **Storage**: Local files by default; Firestore when `USE_FIRESTORE=true`

---

## 🚀 Quick Start

### 1. Backend Setup
```bash
cd backend
python -m venv venv
# macOS / Linux:
source venv/bin/activate
# Windows:
.\venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # then set GOOGLE_API_KEY
python -m app.main     # serves on http://127.0.0.1:8080
```

Run the tests with `python -m pytest` from `backend/`.

### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
Open [http://localhost:3000](http://localhost:3000).

### 3. Live Browser Extension
1. Open Chrome and go to `chrome://extensions`.
2. Enable "Developer mode" (top right).
3. Click "Load unpacked" and select the `extension/` folder in this repo.

Once loaded, HandOff will automatically connect to any tab it opens!

---

## 🧪 Recommended Test Flows

Execute these tasks in **Live Mode** to see the recent accuracy and synchronization fixes in action:

### 1. The "Entertainment" Test (YouTube)
*   **Instruction**: "Go to YouTube, search for 'lofi hip hop radio', and play the first result."
*   **What to expect**: 
    - The agent will navigate to YouTube.
    - It will precisely click the search bar, type the query, and find the video.
    - Because of **Screenshot Sync**, it will correctly detect that the video has started playing and declare the task complete.

### 2. The "Form Master" Test (MakeMyTrip)
*   **Instruction**: "Search for flights on MakeMyTrip from Delhi to Mumbai for tomorrow, then select 'Student' special fare."
*   **What to expect**:
    - The agent will interact with the complex MMT date picker.
    - It will precisely target the **Student** fare checkbox even if it's crowded by other UI elements.
    - You will see the cyan highlight overlay appearing exactly on the targeted elements.

### 3. The "Deep Research" Test (Wikipedia)
*   **Instruction**: "Go to Wikipedia, search for 'DeepMind', and tell me the name of its founders."
*   **What to expect**:
    - The agent will use the search bar, type the query, and press Enter.
    - It will read the page content and provide a verbal/text summary of the founders.
    - This demonstrates the agent's ability to transition from "acting" to "interpreting" information.

---

## 🏆 Hackathon Alignment: UI Navigator Track

HandOff addresses the core requirements of the **UI Navigator** track by:
1. **Becoming the user's hands**: Direct physical manipulation of the browser.
2. **Visual Understanding**: Interpreting UI with or *without* DOM access (Live mode is 100% visual coordinate based).
3. **Multimodal Core**: Every action is guided by the latest Gemini multimodal screenshot processing.
