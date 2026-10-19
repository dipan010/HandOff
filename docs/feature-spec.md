# HandOff — Feature Spec

This document lists what HandOff should do, described from the user's side: what they see, hear and can rely on. It says nothing about how any other product is built, and it contains no code. Build each feature from the behaviour described here.

Status key: **Have** = already in HandOff, **New** = to build.

---

## 1. Getting HandOff's attention

| Feature | Behaviour | Status |
|---|---|---|
| Wake phrase | Saying "Hey HandOff" anywhere on the computer opens HandOff and starts listening. Works offline and needs no paid key. | New |
| Keyboard shortcut for voice | A global shortcut opens HandOff in listening mode. | New |
| Keyboard shortcut for typing | A second shortcut opens a small text box for typed requests. | New |
| Close | Esc hides HandOff. If a task is running, the task keeps running unless the user says or clicks "stop". | New |
| Dashboard start | The web dashboard can still start a task by text or voice. | Have |

## 2. The on-screen pill (desktop app)

- A small, see-through, rounded bar that floats above every window, including full-screen apps, without stealing focus.
- It changes shape and content with what HandOff is doing:
  - **Idle:** a microphone icon and "Hey HandOff".
  - **Listening:** the words appear as they are heard.
  - **Thinking:** a small animation.
  - **Doing:** the icon of the app being used and a short line such as "Typing your message".
- Clicks pass through the pill except on its own buttons.
- A **Stop** button is always visible while a task runs.
- **Reply card:** longer answers open in a card under the pill that supports formatted text, tables, code, maths and images. It can be scrolled, copied and closed.
- **Plan preview:** before long or risky tasks, the card shows the planned steps with "Go ahead" and "Cancel".
- The animations between states are smooth and never flash over full-screen apps.

## 3. First launch

- A short setup screen asks for the Gemini API key and checks it works.
- It checks microphone permission and, on macOS, Accessibility permission. It explains how to grant each one and re-checks automatically.
- It offers a link to install the Chrome extension and shows when the extension is connected.
- It shows the keyboard shortcuts.
- HandOff starts its own background service on launch. If one is already running, HandOff reuses it.

## 4. Understanding the request

- **Quick replies:** greetings, thanks and simple questions are answered straight away (under a second where possible), without starting a task.
- **Acknowledgement:** every real task gets an immediate short spoken reply ("Sure, opening that now") before the work starts.
- **Fast vs. careful:** simple one-step requests use a fast model. Requests with many steps or real ambiguity use a stronger model. If the stronger model fails, a backup model takes over without the user noticing.
- **Asking back:** if something important is missing ("which Sarah?"), HandOff asks one short question and waits for the spoken or typed answer.

## 5. Doing the task: plan, do, check

- **Plan:** for anything with more than one part, HandOff first writes a short numbered list of steps. Each step says what "done" looks like ("the email draft is open with the subject filled in").
- **Do:** HandOff works through one step at a time. It only considers the actions that make sense for that step.
- **Check:** after each action, HandOff confirms it worked by looking at what changed (the page, the window, the address, the screen) before moving on.
  - If it did not work, HandOff tries another way, up to three times.
  - If a step keeps failing, it rewrites the remaining plan.
  - If it is truly stuck, it tells the user plainly what went wrong.
- **Limits:**
  - A task has a maximum number of actions, so it can never run forever.
  - Repeating the same action on an unchanged screen ends the task.
  - The user can stop at any moment, and HandOff stops before its next action.
- **Safety pauses (Have, extend):** HandOff always asks before payments, sign-ins, sending messages, deleting files or posting publicly. On a login page it pauses so the user can sign in, then continues.
- **Patience mode (Have):** longer waits between actions for slow connections and heavy sites.
- **Grandparents mode (Have):** warm, first-person, jargon-free wording for every status and narration line.

## 6. Seeing the screen

- **Structure first:** HandOff reads the structure of the page (links, buttons, fields and their labels) or of the app window (its controls and their names) before anything else. This is fast and exact.
- **Screenshots as a backup:** a screenshot is only used when the structure isn't enough, for example with canvas apps, odd custom controls or images of text.
- **Context:** before each task HandOff knows which app is in front, the window title and, in the browser, the page address.

## 7. Working in the browser

- **Any tab:** HandOff works in the user's own signed-in Chrome, on the tab it opened or on any tab the user points it to.
- **Real input:** clicks and key presses behave like a real person's, so sites that ignore fake events still respond.
- **Bigger actions:** single actions that do several small steps internally:
  - search the web and open the best result
  - read a page as clean text
  - pull a list or table out of a page (prices, listings, results)
  - fill a whole form from a set of values
  - pick an item from a dropdown or date picker by its visible text
- **Search or go direct:** fixed rules decide when to search and when to go straight to a known site.
- **On-page feedback (Have):** a banner in the tab shows what HandOff is doing, and the element about to be clicked is highlighted.

## 8. Working in other apps (Windows and macOS)

- Open, switch to and quit apps; list and focus windows.
- Read the controls in the front window and click them by name.
- Type text and press keyboard shortcuts.
- Set the volume, play or pause media.
- Take a screenshot when needed (see §6).
- The behaviour is the same on Windows and macOS. Anything that only works on one OS says so clearly.

## 9. Voice

- **Speech to text** for everything the user says after the wake phrase or shortcut.
- **Spoken replies** start playing within moments, sentence by sentence, instead of waiting for the whole answer.
- **Interrupting:** if the user starts talking, HandOff stops speaking and listens.
- **Conversation mode:** after a reply, the microphone reopens automatically so the user can keep going. Saying "that's all" or pressing Esc ends it.
- **Narration while working (Have):** HandOff describes what it is doing as it does it, with a choice of plain or Grandparents wording. It can be turned off.

## 10. Remembering

- **Conversation:** HandOff remembers the current conversation. Older parts are shortened automatically so long chats keep working.
- **Across sessions:** past conversations are kept and searchable by meaning, not just exact words.
- **Personal notes:** "Remember that my mum's number is …" saves a note. "What's my mum's number?" or "text my mum the list I mentioned yesterday" uses it.
- **Control:** the user can list, edit and delete what HandOff remembers from the dashboard.
- **Storage:** on the computer by default. In the cloud (Firestore + Cloud Storage) when cloud mode is on, so memory follows the user.

## 11. Background tasks

- The user can ask for a task to run in the background ("read this PDF and summarise it") while using HandOff for something else.
- Background tasks never take over the mouse or keyboard unless the user allows it.
- Each one has a status (running, waiting for you, done, failed, stopped), a log and a result.
- A task can pause and ask the user to approve something or give feedback, then carry on.
- They are shown in the dashboard and as a small badge on the pill. They can be stopped at any time.

## 12. Google apps and files

- **Gmail:** search, read, draft and send (sending always asks first).
- **Calendar:** list, create and change events.
- **Docs and Sheets:** create, read and edit.
- **Drive:** find and open files.
- Signing in uses the user's Google account with the smallest set of permissions needed.
- **Files on the computer:** read, write and list, limited to the user's own folders.
- **Web pages:** fetch a page's text without opening a browser.

## 13. Cloud mode

- The thinking part of HandOff can run on Google Cloud Run, so it is always on and can later be reached from other devices.
- Anything that has to touch the user's computer (clicking, typing, reading the screen, the browser) is sent from the cloud back to the desktop app, which does it and returns the result.
- Cloud mode is protected by a token or Google sign-in.
- One script sets up Cloud Run, Firestore and storage, and prints the settings the desktop app needs.
- A health check address reports whether the service is up.

## 14. Getting and installing HandOff

- An installer for Windows and a disk image for macOS.
- The Chrome extension as a download with short install steps.
- An optional simple download page.

## 15. Quality checks

- Automated tests for planning, checking, the tools, page reading and memory, using fake model replies so they run offline.
- A set of repeatable scenarios (for example the YouTube, MakeMyTrip and Wikipedia flows, plus desktop ones) to measure how often tasks succeed.
- The plain-words test (`backend/tests/test_plain_words.py`) keeps buzzwords out of the code, UI and docs.
