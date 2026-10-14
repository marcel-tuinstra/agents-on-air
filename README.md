# Agents on Air

**Your agent chats, animated.**

You run tasks in Codex and Claude. To follow the work, you switch between chats and read each agent’s updates.

With Agents on Air, you watch those contributions in a studio beside your work. Follow the cast through short captions and inspect the images or code changes they shared. Open Codex or Claude to reply or take action.

Choose Midnight, Paper or Pocket for the cast and set. Listen to gibberish or mute it. You can read the original messages in the transcript and configure a provider to prepare shorter updates on request.

## Start

Requires **Python 3.9 or newer**; 3.12 recommended. No API key is needed for normal viewing. Audio is generated locally in the browser using Web Audio.

| Platform | Check installation | Start |
| --- | --- | --- |
| macOS | `python3 setup_studio.py` | `Start Studio.command` |
| Windows | `py -3 setup_studio.py` | `Start Studio.bat` |
| Linux | `python3 setup_studio.py` | `sh "Start Studio.sh"` |

Setup only checks Python; it downloads no models or voices. Open **http://127.0.0.1:8878**. Stop the server with Ctrl+C. You can also run `python3 start_studio.py` and pass options such as `--port 8879`.

Sources default to `$CODEX_HOME` or `~/.codex`, and `$CLAUDE_CONFIG_DIR` or `~/.claude`. Override with `--codex-home /path/to/codex` and `--claude-home /path/to/claude`.

The interface defaults to **English**. Chat titles, messages and captions keep their original language.

## Watch the studio

- On opening, a five-second sequence assembles the set, screen, desk and lights. **Skip intro** opens the available content. Reduced motion removes the sequence and delay. A slow source continues to show a loading state; the animation is not a data-progress indicator. Switching chats does not replay the intro.
- The subtitle below Agents on Air opens grouped chats and the global channel selector. **Midnight** is a warm evening show, **Paper** a papercraft studio, and **Pocket** a pixel broadcast.
- Only chats with recorded activity in the last **24 hours** appear. Empty groups disappear. Main-agent and subagent messages, recorded work and task transitions count. Renaming, reading, audio playback, file timestamps and connection checks do not extend activity.
- After **one hour** without activity, the set dims and the presenter dozes, waking and tapping the desk. Work and controls remain readable. New activity wakes the studio. A chat that passes 24 hours disappears without selecting another one. Disconnection has its own state and preserves the last received work.
- The shared work screen shows available local images and explicit recorded changes, with the original agent, timestamp and provenance. Claude edit requests remain labeled as proposals. Before/after images appear when the source pairs them. A missing artifact gets an empty state.
- Use the arrows below the work screen to browse shared files. New work appears first. Command activity appears above the last shared image or diff. Shell and script edits are only visible as diffs when the source records a patch; the viewer does not reconstruct them from the filesystem.
- Compact view and transcript controls are icons in the work-screen frame. Compact view keeps the selected chat. **Read contribution** opens the original text. The transcript supports Markdown and readable question/answer blocks.
- Captions use short successive pieces, with pause and previous/next controls. Five detailed supporting characters and five silhouettes are supported. Main presenters also work alone.
- Bodies, arms and hands have separate movement. Mouths follow the same sound plan and audio clock as gibberish. Reduced motion respects the system preference.

## Settings and custom studio updates

Open **Settings** using the sliders icon in the header. The presentation source defaults to **Original agent contributions**.

Choose one of two optional routes:

- **Local CLI:** Codex or Claude Code must be installed and signed in. The settings page reports whether the executable was found. A model ID is optional. The separate session runs in an empty temporary directory with tools, hooks and integrations disabled. API-key environment variables are not forwarded to the CLI. The selected CLI still uses its configured account and may process text in the cloud.
- **Your API key:** choose OpenAI or Anthropic, enter the exact model ID and your key. The key goes only to the local server and then to that selected provider when you request an update. It is not returned by the settings API, logged or stored in browser storage.

An optional **Presentation direction** controls tone and emphasis. The shared instruction asks for a short, attributed update that preserves uncertainty and unfinished work.

Confirm the processing/usage notice and save. Saving makes **Create studio update** available in the studio; it does **not** start a model call. Each press sends up to eight recent visible agent messages, capped at 3,000 characters each, to the selected method. No user messages, hidden reasoning or binary attachments are added. Visible agent text can still contain project information. The result is labeled **AI studio update**, displayed as captions and optionally played as gibberish. The original transcript remains intact. There is no automatic processing or silent fallback between methods.

Settings and keys live in server memory for the current server session. A blank key retains an existing key only for the same BYOK provider. Turning custom updates off clears the in-memory key. Restarting restores the launch configuration.

Environment configuration is also supported: `STUDIO_NARRATION_MODE=off|cli|byok`, `STUDIO_NARRATION_PROVIDER=codex|claude|openai|anthropic`, `STUDIO_NARRATION_MODEL`, `STUDIO_NARRATION_STYLE`. BYOK uses `STUDIO_NARRATION_API_KEY`; CLI requires `STUDIO_NARRATION_CLI_APPROVED=1`. Never commit keys. Unrelated general API keys are not discovered or reused.

The settings/API paths and provider responses are tested with synthetic values and mocks. No paid model call was made during this implementation.

## Sound

Gibberish is the only audio mode and is enabled by default. The speaker button mutes/unmutes it. The browser may require a first click or keypress; mute is remembered locally. There is no language-voice menu or speech-service API.

All three casts use fresh oscillator synthesis. The supplied WAV references informed aggregate frequency ratios, envelopes and timing; they are not played or looped. Each `themes/<id>/audio.json` contains parameters, not recordings.

- **Midnight:** measured news-anchor rhythm, about 106 ms between letter sounds, soft onset and restrained pitch variation.
- **Paper:** friendly, rounded fox sounds around 200–245 Hz, about 65 ms apart.
- **Pocket:** brisk beep-boop, about 47.5 ms apart. The host and even cast slots use the brighter pixel voice; odd supporting slots use the softer variant.

Sound, mouth shapes and captions share a clock. Mute leaves that clock running; pause freezes it. Switching chat or channel stops playback and clears the queue. History does not autoplay. The bounded queue has retry/skip recovery. Automated checks prove timing/routing and valid samples, not subjective sound quality.

Open `/voice-lab` to hear the current casts with a fictional conversation. It uses the same engine and does not read real chats.

## Local data and access

Codex uses read-only SQLite/JSONL; Claude uses local project and subagent JSONL. Provider-scoped identities, `lastActivityAt`, normalized events and artifact references carry agent/time/provenance. Polling every two seconds feeds SSE. This is saved-log viewing, not token streaming or proof that a process is alive.

The adapters depend on version-sensitive local storage formats. Cloud-only and remote-computer chats are not included. The transcript is capped at 200 messages and at most 100 recent descendant relationships. Uncertain relationships are not asserted as a known cast. Saved Codex groups and Claude project folders are preserved.

The server binds only to loopback. Access uses Host/Origin/Fetch-Site checks, a random HttpOnly/SameSite cookie, no-store responses and CSP. Existing agents cannot be prompted, started, stopped or approved through the viewer. Optional studio-update requests are separate and off by default. This is not a security boundary against other processes running as the same local user.

Artifact URLs use opaque IDs. Only verified, chat-linked local files are served, with type, size, location, symlink and file-change checks. Arbitrary paths, executable HTML/SVG previews and continuous screen capture are unsupported. Sensitive diff paths are withheld. A shared Git diff is never used to infer individual contributions.

Browser storage holds display preferences, not keys or chat transcripts. Normal viewing and audio stay local until custom updates are configured and requested.

## Development and verification

The project contains its build inputs. Edit `frontend/`, then run `python3 build.py`.
The build copies the local assets and modules into `static/`. It needs no npm
install, network access or files from the original design workspace. Run
`python3 package.py` to create a source-and-runtime zip in the parent directory.
On Windows, use `py -3` in place of `python3`.

Frontend responsibilities:

- `app.js` coordinates the selected chat, cast and captions.
- `stream.js` owns the source connection, reconnection and cancellation.
- `work-view.js` owns shared-file rendering and navigation.
- `controllers.js` owns loading and stale-request protection.
- `rig.js` draws the cast for both the studio and voice-lab.

`providers/schema.py` defines the common records and finalizes snapshots for
both providers. `live_feed.py` shares catalog and chat refreshes between browser
tabs. It holds at most 128 latest-value slots and no per-client event backlog.
Provider locks protect mutable readers without locking the other provider.
Warm viewers keep the last snapshot while a refresh runs; a completed refresh
wakes connected viewers. This does not make local logs a token stream.

From this directory:

```sh
python3 -m unittest discover -s tests -v
node --check static/app.js
node --check static/settings.js
node tests/test_diff.cjs
node tests/test_boot.cjs
node tests/test_stream.cjs
node tests/test_text.cjs
node tests/test_studio.cjs
node tests/test_speech.cjs
node tests/test_garble.cjs
node tests/test_paper.cjs
node tests/test_pocket.cjs
node tests/test_midnight.cjs
node tests/test_body.cjs
```

Fixtures use fictional databases/transcripts; HTTP/SSE tests bind temporary loopback ports. Screenshots labeled “demonstratie” are synthetic. The older `work/studio-hub/build-live.py` in the original workspace forwards to this project's build; the old prototypes are no longer build inputs.

Current checks cover settings consent/validation, provider-key isolation and concurrency, access guards, source parsing, artifact provenance, five-second/skip/reduced-motion loading, audio and caption behavior, plus desktop/mobile UI. Independent Product Owner, PM, Developer and Tester reviews informed the implementation; they are not human acceptance.

macOS has been tested locally. Windows/Linux installation and audio checks and the larger-presenter layout review remain pending.

## Distribution and licenses

`agents-on-air.zip` contains the frontend source, build and packaging scripts, runtime, tests and notices. It excludes local chats, screenshots, recordings, models and development environments. Historical Piper/voice-pack experiments and their licenses remain recoverably archived outside the app in the original workspace under `work/studio-legacy`.

Bundled dependencies: Marked 18.1.1 (MIT), DOMPurify 3.4.17 (Apache-2.0/MPL-2.0), Simple Icons 14.0.0 (CC0), Silkscreen font (OFL). See `licenses/`. Trademarks belong to their owners. Project code and project-created theme materials use the [MIT license](LICENSE). See [asset and dependency notices](THIRD_PARTY.md).

Channel typography is bundled locally: Lora (Midnight), Nunito (Paper), and Pixelify Sans with Silkscreen (Pocket). Their SIL Open Font License notices are in `licenses/`. Code keeps a monospace font. Recorded diffs highlight additions in green and removals in red, retain the original signs, and show line counts.

## Add a channel

Copy a theme folder into `themes/`, run `python3 build.py`, and refresh. Each pack owns its images, colors, typography settings and synthesized audio profiles. Remove or disable a pack and rebuild to remove it. New casts use one of the three existing animation rigs; arbitrary skeletons and recorded-audio packs are not supported. See [Theme packs](THEMES.md) for the format and examples.
