# Universal Digital Accessibility Agent (HandOff) ☸️

**HandOff** is an AI-powered co-pilot designed to become the "hands on screen" for users with accessibility needs. By combining **Gemini 2.5 Computer Use** for visual navigation and **gemini-2.5-flash-native-audio** for real-time narration, HandOff bridge the gap between user intent and complex digital interfaces.

Built for the **Gemini Live Agent Challenge** under the **UI Navigator** category.

---

## 🌟 Key Features

- **Double-Agent Loop (Remote + Live)**: 
    - **Remote Mode**: Uses Playwright for an isolated, sandboxed experience.
    - **Live Mode**: Pilots the user's *actual* browser via a Chrome Extension—perfect for Netflix, YouTube, or WhatsApp where you're already logged in.
- **Patience Mode 🐢**: When enabled, the agent slows down its reaction time and waits longer for pages to settle—ideal for slow connections or heavy sites.
- **Grandparents Mode 👵**: Replaces technical logs with warm, first-person narration (e.g., "I'm looking for your recipe now!").
- **Visual-First Intelligence**: Interprets screens purely through images using `gemini-2.5-computer-use-preview`.
- **Real-Time Narration**: Summarizes every action as it happens via `gemini-2.5-flash-native-audio`.
- **Safety First**: Built-in "Require Confirmation" system stops the AI before performing sensitive actions like payments.

---

## 🛠 Tech Stack

- **AI**: Gemini Multi-modal (Computer Use), Gemini Live (Narration)
- **Frontend**: Next.js 15, TypeScript, Vanilla CSS (Premium Dark Mode)
- **Backend**: FastAPI, Python 3.11, Playwright (Remote Engine)
- **Integration**: Chrome Manifest V3 Extension (Live Engine)
- **Infrastructure**: Designed for Google Cloud Run & Firestore

---

## 🚀 Quick Start

### 1. Backend Setup
```bash
cd backend
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Install deps:
pip install -r requirements.txt
playwright install chromium
```
Create `backend/.env` with your `GOOGLE_API_KEY`.

**Run (Windows Warning: Do not use --reload if using Remote Mode):**
```bash
.\venv\Scripts\python.exe -m app.main
```

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
