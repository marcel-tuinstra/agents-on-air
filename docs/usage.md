# Using Agents on Air

[Back to the studio overview](../README.md)

## Choose a chat

Click the chat name beneath the title to open the chat drawer. Choose a channel for the whole app, then select a Codex or Claude Code chat. Use the work-screen controls for compact view and the transcript. Compact view keeps the selected chat.

The list includes chats with recorded activity in the last **24 hours**. Main-agent and subagent messages, work events and task transitions count. Reading a chat, renaming it or playing audio does not reset that clock.

After **one hour** without activity, the lights dim and the presenter dozes or taps the desk. New work wakes the studio. After 24 hours, the chat leaves the list without switching you to another chat. A lost connection has its own notice and preserves the last received work.

## Follow the conversation

Speech bubbles show the current speaker’s words, even when muted. Supporting agents appear beside their own bubble; generated summaries are marked **AI studio update** beside the lead. Use the bubble’s arrows to reread a passage, or pause both text and sound. The final bubble stays for four seconds; pausing, rereading or focusing its controls keeps it visible. Open the transcript for the original messages. The transcript supports Markdown and holds up to 200 messages.

Browse recorded images and patches with the arrows beneath the work screen. Each contribution retains its author and source. Claude edit requests appear as proposals. Before/after images need a pair recorded by the source. Shell edits appear as diffs only if the source records a patch.

The cast supports a lead presenter, five detailed supporting characters and five silhouettes. The lead presenter can work alone.

## Sound and motion

Use the speaker button to mute or unmute gibberish. Each channel has its own sound and cast profiles. The browser may need a click or keypress before playback. Mute is remembered on this browser.

The app generates the sounds with Web Audio; it does not play voice recordings or read the text aloud. Mouth shapes and captions use the same sound plan and clock. Pause freezes playback; switching chat or channel stops it and clears the queue. Older messages do not autoplay.

Open `/voice-lab` on your local server to hear the casts in a fictional conversation. Your system's reduced-motion setting removes the studio-building intro and reduces character movement. You can also skip the intro with **Skip intro**.

## Start options

In the extracted release folder, run `python3 start_studio.py` on macOS/Linux or `py -3 start_studio.py` on Windows. The launcher opens the browser. Stop the server with Ctrl+C in its terminal.

Use `--port 8879` if the default port is occupied. Source locations default to `$CODEX_HOME` or `~/.codex`, and `$CLAUDE_CONFIG_DIR` or `~/.claude`. Override them with `--codex-home /path/to/codex` and `--claude-home /path/to/claude`.

The interface uses English. Chat titles, messages and captions retain their original language.

## Custom studio updates

Open **Settings** using the sliders icon in the header. The presentation source defaults to **Original agent contributions**.

Choose one of two optional routes:

- **Local CLI:** Codex or Claude Code must be installed and signed in. The settings page reports whether the executable was found. A model ID is optional. The separate session runs in an empty temporary directory with tools, hooks and integrations disabled. API-key environment variables are not forwarded to the CLI. The selected CLI still uses its configured account and may process text in the cloud.
- **Your API key:** choose OpenAI or Anthropic, enter the exact model ID and your key. The key goes only to the local server and then to that selected provider when you request an update. It is not returned by the settings API, logged or stored in browser storage.

The presenter names the contributors, explains what changed and mentions open work or decisions in two or three short sentences. A single contribution may need only one sentence. Later reports take precedence over earlier reports about the same work; a failed check that someone fixed should not become a current blocker.

An optional **Presentation direction** controls language, tone and emphasis. For example: “Present in Dutch. Use three short sentences. Name the contributors and any open decisions.” Without a language instruction, the presenter follows the latest selected message. Updates describe recorded reports, which may no longer reflect what an agent is doing now.

Confirm the processing/usage notice and save. Saving makes **Create studio update** available in the studio; it does **not** start a model call. Each press selects up to eight messages from the last 32 nonempty visible agent contributions. Each contributor gets their latest message included before spare slots fill with recent context. If more than eight agents contributed, the eight most recent contributors take priority. This keeps a busy lead agent from crowding out the rest of the cast, while keeping the input bounded.

The request preserves message order, speaker identities, timestamps and source message IDs. Messages over 3,000 characters retain their beginning and end, with the omitted middle marked. No user messages, hidden reasoning or binary attachments are added. Visible agent text can still contain project information. The result is labeled **AI studio update**, displayed as captions and optionally played as gibberish. The original transcript remains intact. There is no automatic processing or silent fallback between methods.

Settings and keys live in server memory for the current server session. A blank key retains an existing key only for the same BYOK provider. Turning custom updates off clears the in-memory key. Restarting restores the launch configuration.

Environment configuration is also supported: `STUDIO_NARRATION_MODE=off|cli|byok`, `STUDIO_NARRATION_PROVIDER=codex|claude|openai|anthropic`, `STUDIO_NARRATION_MODEL`, `STUDIO_NARRATION_STYLE`. BYOK uses `STUDIO_NARRATION_API_KEY`; CLI requires `STUDIO_NARRATION_CLI_APPROVED=1`. Never commit keys. Unrelated general API keys are not discovered or reused.

### Integration verification

On 15 October 2026, a live test through the narration adapter succeeded with Codex CLI 0.162.1 and a fictional agent contribution. Claude Code 2.1.287 was installed but signed out, so a live Claude result remains unverified. Install detection in Settings does not verify account sign-in.

On the same date, OpenAI BYOK succeeded with `gpt-4.1-mini` through the authenticated Settings and studio-update HTTP routes, using a fictional contribution and a user-authorized key held in memory for the test. The response retained its source message ID; disabling custom updates cleared the key. Anthropic request/response handling has mock coverage, but a live Anthropic API call remains unverified. A successful test does not validate another account, key or model entered in Settings.

A follow-up live check used three fictional contributors, including a quiet tester, an open decision and ten repeated layout updates. Both Codex CLI and OpenAI BYOK included all three contributors, kept the corrected test outcome and the open decision, and followed a Dutch presentation direction despite English source messages. The OpenAI check used the authenticated Settings and update routes again. These checks demonstrate those scenarios, not a guarantee that a model will summarize every conversation correctly.

## Data and privacy

Codex uses read-only SQLite/JSONL; Claude uses local project and subagent JSONL. Provider-scoped identities, `lastActivityAt`, normalized events and artifact references carry agent/time/provenance. Polling every two seconds feeds SSE. This is saved-log viewing, not token streaming or proof that a process is alive.

The adapters depend on version-sensitive local storage formats. Cloud-only and remote-computer chats are not included. The transcript is capped at 200 messages and at most 100 recent descendant relationships. Uncertain relationships are not asserted as a known cast. Saved Codex groups and Claude project folders are preserved.

The server binds only to loopback. Access uses Host/Origin/Fetch-Site checks, a random HttpOnly/SameSite cookie, no-store responses and CSP. Existing agents cannot be prompted, started, stopped or approved through the viewer. Optional studio-update requests are separate and off by default. This is not a security boundary against other processes running as the same local user.

Artifact URLs use opaque IDs. Only verified, chat-linked local files are served, with type, size, location, symlink and file-change checks. Arbitrary paths, executable HTML/SVG previews and continuous screen capture are unsupported. Sensitive diff paths are withheld. A shared Git diff is never used to infer individual contributions.

Browser storage holds display preferences, not keys or chat transcripts. Normal viewing and audio stay local until custom updates are configured and requested.

