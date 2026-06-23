# Midnight Radio UI Guardrails

The current station intro and blurred album-art background are protected UI.

Do not change, remove, restyle, retime, or refactor these areas unless the user explicitly asks to change the intro or blurred background:

- `#station-intro` markup in `src/api/templates/index.html`
- Station intro timing and lifecycle logic in `runStationIntro()` and `finishStationIntro()`
- `#ambilight` and `.ambilight-layer` markup in `src/api/templates/index.html`
- Blurred album backdrop rendering, crossfade, and `updateBackdrop()` behavior
- CSS rules whose purpose is to keep the album-art blur visible behind the app

Other UI work should be built around these pieces, not through them.
