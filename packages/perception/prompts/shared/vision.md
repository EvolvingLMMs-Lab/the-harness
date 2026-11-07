Generic vision (`vision`): perception that knows nothing about this game or app; you learn
what its pictures mean. A frame is an RGB array, a screenshot, or None for the screen now;
boxes are window pixels [x0, y0, x1, y1].

- `vision.diff(a, b)`: what changed between two frames: {changed, magnitude, box, regions
  [{box, pixels, mean}], shift [dx, dy], explained (the share of the change the shift
  accounts for), grid}. Press a key or move the mouse
  between two frames to learn what it does: a camera turn shows as a shift, a menu or a
  counter as a region.
<!-- if: vision_service -->
- `vision.ocr(frame=None, region=None)`: text lines [{text, box, score}], top to bottom.
- `vision.detect(frame=None, labels=[...], threshold=0.3)`: boxes of the things plain
  words name ("tree trunk", "door", "health bar"): [{label, box, score}], best first.
- `vision.depth(frame=None, stride=2)`: an estimate of each pixel's distance in metres at
  1/stride of the frame's size (depth[y // stride, x // stride]); rough, best as a ranking.
- `vision.segment(frame=None, point_or_box, background=())`: masks of the thing under a
  pixel, pixels or a box, best first (.array, .box, .score, .area, .centroid).
- `vision.train(name, samples, epochs=30)`: when detect and segment are not good enough
  for something you need often, label frames from practice (samples: {"frame", "masks":
  {label: bool array}} or {"frame", "boxes": [{label, box}]}, 50 or more) and train a small
  model of this game's pictures; it goes to the library as a skill `name(frame=None)` ->
  {label: {pixels, box}} through the same checks as any skill. `vision.predict(name,
  frame)` uses it at once.

Each call takes a tenth to a few tenths of a second; the first of a kind loads its model.
<!-- end -->
