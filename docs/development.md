# Development

[Back to the overview](../README.md) · [Theme packs](../THEMES.md)

For everyday use, download `agents-on-air.zip` from [Releases](https://github.com/marcel-tuinstra/agents-on-air/releases). To work on the code, use this repository. Python runs the backend and build; Node.js runs the frontend tests.

Clone the repository, then start the included runtime:

```sh
git clone https://github.com/marcel-tuinstra/agents-on-air.git
cd agents-on-air
python3 start_studio.py
```

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

Fixtures use fictional databases and transcripts. HTTP/SSE tests bind temporary loopback ports. The screenshots in `docs/media/` show the real interface with fictional chats; they contain no personal chat data.

CI runs the build, tests and packaging on macOS, Linux and Windows. Check [the current results](https://github.com/marcel-tuinstra/agents-on-air/actions/workflows/checks.yml) before making platform-support claims. Browser audio and visual checks still need a human check on the target platform.

## Release package

Run `python3 package.py` after building to check the ZIP before publishing. CI also keeps the tested ZIP as an `agents-on-air` workflow artifact.

To publish, merge the verified changes into `main`, then push a version tag such as `v0.1.0` on that commit. The **Release** workflow runs the shared checks on macOS, Linux and Windows. After all three pass, it publishes the tested `agents-on-air.zip` to [GitHub Releases](https://github.com/marcel-tuinstra/agents-on-air/releases). A failed check prevents publication. GitHub's workflow artifact is a build download; the ZIP attached to the release is the user download.

The release includes the ready-to-run app, source, tests and documentation. Users extract it and start the launcher; they do not need to build the frontend. GitHub's generated **Source code** archives are separate from this release asset.

The packager uses an explicit list of source directories. Keep personal chats, credentials, recordings, model downloads and development environments outside that list. Documentation images must use fictional data. Check the archive contents before publishing.
