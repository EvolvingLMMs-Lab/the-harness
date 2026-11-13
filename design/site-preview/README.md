# The Harness website

The approved homepage lives in `web/`; `docs/tools/homepage.ts` copies only its active files into the documentation build's root. Run `deno task build` from `../../docs/` to build the complete site. The Sites checkout is an owner-private deployment mirror, not a development source.

The homepage uses the original product content and screenshots, LMMS Lab's logo, deep-sea navy/mist-white themes, restrained archive marks, cyan/magenta offset shadows and an animated point-cloud background. Shared layout width is responsive up to 1120px. Docs use a reading version of the palette without the background animation. The banner, tokens and cathode-ray glass come from `archive.css` and `archive-banner.js`, copied from the monorepo's `docs/brand/archive-design`. The header logo plays the lab site's load animation on the homepage and in the docs header (`logo-motion.js`, with the engine in `animation/` copied from the lab site by the same sync script).

The original four-layer figure retains its geometry. The hero has intermittent magenta LLM and independent program activity, which can overlap. Its reactive ring consists of 48 fixed dots: one bright dot advances to the adjacent dot every 60ms, with no rotation or skipped neighbours. Reduced motion and offscreen/hidden-page suspension are respected.

Both surfaces use `starlight-theme` (`light`, `dark`, or empty for system preference). Existing `harness-theme` choices migrate only when the shared key is absent. Saved preferences take precedence over old preview URL parameters. Pages resynchronize on browser history restoration and cross-tab storage events. Internal documentation links stay in the same tab.

Validation: docs type check, production build, bundle budgets; desktop/mobile reading, search, both palettes, homepage-to-docs and docs-to-home navigation, history restoration and reactive chase adjacency. No full Harness test suite. Public production deployment is separate from the private preview.

Historical anatomy experiments, card studies, screenshots, copied build output and unused assets remain local; they are not part of the build or PR.


The two demo stages use the recordings in `web/assets/demos/` and trace intervals in `web/demos.js`. The Multimodal first stage shows short clips of the key moment with no timeline (their entries have no lanes); in the Autonomous stage `web/demo-player.js` renders the lanes and synchronizes a native keyboard/touch-accessible range input to the video's media clock. The lane label column is sized to the widest rendered label, so labels never run into the plot. Only the selected recording loads; offscreen or hidden-page playback pauses. Leaving a demo returns it and its stage bar to the start, and choosing a demo plays it from the start. A recording that plays to its end hands over to the next one, also after a manual choice; seeking to the end while paused or dragging does not. Reduced motion keeps posters until explicit playback.

After the docs build, run `node demo-regression.mjs` from this directory with Playwright available (`PLAYWRIGHT_MODULE` may be an existing module URL; `CHROME_PATH` may select a local Chromium executable). The test covers pointer/touch/keyboard seek, real media/playhead synchronization, source release, ended-based switching, reduced-motion behavior, Chinese and both themes at desktop/mobile widths. Screenshots go to `DEMO_TEST_OUTPUT` when set. This is a focused UI test, not the full Harness suite.


Use `node preview.mjs 8840` for local preview. It supports HTTP byte ranges, including HEAD and partial reads, so browser video seeking works. Plain Python http.server does not implement the required range behavior. The browser regression imports this same server; set `DEMO_TEST_URL=http://127.0.0.1:8840` to check the exact running preview. Tests verify both video time and decoded-frame changes after a drag, not only input/playhead values. The figure contains only the recording and draggable timeline; no extra playback row, time readout, overlay buttons or editorial captions are rendered.
