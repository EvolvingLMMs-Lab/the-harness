"""What changed between two frames, with NumPy alone (no model, nothing about what they
show): the one frame difference of the harness. A program's vision.diff (skills/vision), a
game's input probe (the game package) and a robot's joint probe (the robot package) all
read an input's effect off it.

    diff(a, b, threshold=24, min_pixels=64, mask=False) -> {
        "changed"    the share of the pixels that changed
        "magnitude"  the mean change, 0-1
        "box"        [x0, y0, x1, y1] around every changed pixel (x1, y1 past it), or None
        "regions"    the connected changed areas [{"box", "pixels", "mean"}], largest first
        "shift"      [dx, dy]: how far the picture moved as a whole (b is a moved by it;
                     a view that turned right shows the world moving left: dx < 0)
        "explained"  the share of the change, inside what both frames show, the shift accounts for
        "grid"       the mean change (0-255) in a 4 x 4 grid, top row first
        "mask"       the HxW bool array of changed pixels (with mask=True)}

A pixel changed when one of its channels changed by more than `threshold`.
"""

import numpy as np

THRESHOLD = 24


def change(a, b) -> np.ndarray:
    """Each pixel's change from `a` to `b`: its largest change over the channels (int16)."""
    delta = np.abs(np.asarray(a).astype(np.int16) - np.asarray(b).astype(np.int16))
    return delta.max(axis=-1) if delta.ndim == 3 else delta


def gray(frame) -> np.ndarray:
    frame = np.asarray(frame, dtype=np.float32)
    return frame.mean(axis=2) if frame.ndim == 3 else frame


def _peaks(a, b, axis, k) -> list:
    """The `k` best shifts along `axis` (1: sideways, 0: up and down) by phase correlation."""
    a, b = a - a.mean(), b - b.mean()
    spectrum = np.fft.fft2(b) * np.conj(np.fft.fft2(a))
    spectrum /= np.abs(spectrum) + 1e-9
    response = np.abs(np.fft.ifft2(spectrum))
    profile = response.max(axis=0 if axis == 1 else 1)
    n = profile.shape[0]
    found = []
    for index in np.argsort(profile)[::-1]:
        shift = int(index - n if index > n // 2 else index)
        if all(abs(shift - other) > 1 for other in found):
            found.append(shift)
        if len(found) >= k:
            break
    return found


def shift(a, b, threshold=THRESHOLD) -> tuple:
    """The (dx, dy) that moves frame `a` onto frame `b` best, in whole pixels. Phase
    correlation of the frames' sideways and vertical gradients gives a few candidates each:
    a long edge across the picture (a horizon) is the same after any sideways shift, and
    what is drawn over the world (a bar, a counter) does not move at all, so the best peak
    alone is often no shift. The candidate that leaves the least of the change unexplained
    wins."""
    ga, gb = gray(a), gray(b)
    xs = _peaks(np.diff(ga, axis=1), np.diff(gb, axis=1), 1, 5)
    ys = _peaks(np.diff(ga, axis=0), np.diff(gb, axis=0), 0, 3)
    changed = change(a, b) > threshold
    if not changed.any():
        return (0, 0)
    best, best_error = (0, 0), float(np.abs(ga - gb)[changed].mean())
    for dx in xs:
        for dy in ys:
            if (dx, dy) == (0, 0):
                continue
            error = float(np.abs(np.roll(ga, shift=(dy, dx), axis=(0, 1)) - gb)[changed].mean())
            if error < best_error * 0.9:
                best, best_error = (dx, dy), error
    return best


def _regions(moved, delta, min_pixels, cell=8, limit=20) -> list:
    """The connected changed areas, found on a grid of cell x cell pixels (a cell counts
    when a quarter of it changed): [{"box", "pixels", "mean"}], largest first."""
    height, width = moved.shape
    rows, cols = height // cell, width // cell
    if not rows or not cols:
        return []
    grid = moved[:rows * cell, :cols * cell].reshape(rows, cell, cols, cell).mean(axis=(1, 3)) >= 0.25
    seen = np.zeros_like(grid)
    found = []
    for start in zip(*np.nonzero(grid)):
        if seen[start]:
            continue
        stack, cells = [start], []
        seen[start] = True
        while stack:
            r, c = stack.pop()
            cells.append((r, c))
            for nr, nc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if 0 <= nr < rows and 0 <= nc < cols and grid[nr, nc] and not seen[nr, nc]:
                    seen[nr, nc] = True
                    stack.append((nr, nc))
        rs, cs = [r for r, _ in cells], [c for _, c in cells]
        y0, y1, x0, x1 = min(rs) * cell, (max(rs) + 1) * cell, min(cs) * cell, (max(cs) + 1) * cell
        pixels = int(moved[y0:y1, x0:x1].sum())
        if pixels >= min_pixels:
            found.append({"box": [int(x0), int(y0), int(x1), int(y1)], "pixels": pixels,
                          "mean": round(float(delta[y0:y1, x0:x1].mean()) / 255.0, 4)})
    found.sort(key=lambda item: -item["pixels"])
    return found[:limit]


def diff(a, b, threshold=THRESHOLD, min_pixels=64, mask=False) -> dict:
    """What changed from frame `a` to frame `b` (see the module)."""
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape:
        raise ValueError(f"frames of different sizes: {a.shape} and {b.shape}")
    delta = change(a, b)
    moved = delta > threshold
    changed = float(moved.mean())
    box = None
    if moved.any():
        ys, xs = np.nonzero(moved)
        box = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
    found, explained = (0, 0), 0.0
    # The whole picture moving changes much of it; below that a shift is not worth looking for.
    if changed > 0.02:
        found = shift(a, b, threshold)
        if found != (0, 0):
            dx, dy = found
            residual = change(np.roll(a, shift=(dy, dx), axis=(0, 1)), b) > threshold
            h, w = moved.shape
            inside = np.zeros_like(moved)
            inside[max(0, dy):h + min(0, dy), max(0, dx):w + min(0, dx)] = True
            region = moved & inside
            if region.any():
                explained = max(0.0, 1.0 - float((residual & region).sum()) / float(region.sum()))
    h, w = delta.shape
    grid = [[round(float(delta[i * h // 4:(i + 1) * h // 4, j * w // 4:(j + 1) * w // 4].mean()), 1)
             for j in range(4)] for i in range(4)]
    result = {"changed": round(changed, 4), "magnitude": round(float(delta.mean()) / 255.0, 4), "box": box,
              "regions": _regions(moved, delta, min_pixels), "shift": [int(found[0]), int(found[1])],
              "explained": round(explained, 3), "grid": grid}
    if mask:
        result["mask"] = moved
    return result
