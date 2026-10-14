# Theme packs

Each channel lives in `themes/<id>/`. It contains its name, visual tokens, cast image, studio image and gibberish profiles. The studio and voice-lab discover the same enabled packs when you build.

## Install, remove or disable

1. Put a pack folder directly inside `themes/`.
2. Run `python3 build.py` (Windows: `py -3 build.py`).
3. Refresh the studio or voice-lab.

Remove the folder, or set `"enabled": false` in its manifest, and rebuild to remove a channel. Keep at least one enabled. Stale generated theme assets are removed during rebuilding. If a saved channel is gone, the app uses the first installed channel. Changing channels stops the current audio.

There is no runtime installer, download service or executable plugin code. Editing a pack does not alter a running page until you rebuild and refresh. Invalid packs fail validation before the build changes its output. Fix the pack or move it outside `themes/` and rebuild.

## Make a pack

Copy one of the three built-in theme folders to a new folder, for example `themes/copper-radio`. Change `id` to `copper-radio` in `theme.json`, then edit its names, colors and audio. You can retain a built-in rig while creating a different cast and set.

The ID must match the folder: lowercase letters, digits and hyphens, starting with a letter, at most 40 characters. `constructor` and `prototype` are reserved.

Files in a pack:

- `theme.json`: version 1 manifest, names, rig, imagery, portrait crop, colors, font families, license and audio filename.
- `audio.json`: synthesized voices and an 11-entry cast-slot mapping (host, five characters, five silhouettes).
- `cast.webp` / `studios.webp`: local PNG or WebP imagery. The filenames can change in the manifest.
- Optional local TTF/WOFF2 fonts and their license notices.
- `LICENSE`: the pack's redistribution license. Include any additional third-party notices.

Colors and typography use the `tokens` object. Supported keys are `--ink`, `--muted`, `--bg`, `--panel`, `--line`, `--accent`, `--onaccent`, `--sidebar-bg`, `--desk-edge`, `--font-ui`, `--font-display` and the four `--diff-*` colors in the bundled manifests. No arbitrary CSS or JavaScript runs from a pack. Optional `fonts` entries have a `family` and a direct-child `file`; set the matching font-family token as well. You can reuse the bundled font families without copying their files.

## Images and rig boundaries

`rig` is `midnight`, `paper` or `pocket`. It selects the existing face and body geometry, layering, movement and structural UI style. The pack ID is independent of the rig. `portrait` crops the normalized 256×256 host for the selector. `sceneryPosition` is a percentage selecting the scene in the background atlas.

The built-in cast images are combined atlases. They are deliberately copied unchanged into each pack to preserve approved artwork and alignment. For replacement artwork, follow the selected rig's atlas layout and facial coordinates in `frontend/rig.js`, and body cuts in `frontend/body.js`. Use the existing image as a template. `studios.webp` similarly uses the current three-scene layout; keep its alignment and desk position when replacing it.

This first pack format supports new skins/casts using those three rigs. It does **not** automatically rig an arbitrary portrait, skeleton or different atlas layout. A new anatomy/animation system needs a renderer change. Structural rig CSS remains shared; visual tokens and audio belong to the pack.

## Audio

`audio.json` contains `voices` and `slots`. Each of the eleven slots names a voice from that pack. Identical names in different packs are isolated automatically. The supplied packs retain their approved sound parameters.

Each voice sets letter interval, space duration, note duration, attack, decay, RMS level, pitch variation and sound templates. Templates provide a pitch, a mouth shape (`A`–`H` or `X`) and either harmonic weights or `[frequency ratio, gain]` partials. Optional `sentencePause` and `commaPause` set punctuation pauses. Copy an existing profile and change a few values at a time; preview it in `/voice-lab`.

Audio and mouth shapes use the same plan and clock. Values and array sizes are bounded by `theme_packs.py` to reject malformed or excessive profiles. Sound is generated per message; WAV/MP3 playback packs are not supported. Keep the result comfortably quiet and include a valid license for any contributed material.

## Verification

Run `python3 -m unittest discover -s tests -v` and the Node commands in README. Test installing a fourth pack, removing it, stale browser preferences, all eleven cast slots and both desktop and phone drawers. The built-in tests cover add/remove, invalid paths, linked assets and unchanged default voice timing.
