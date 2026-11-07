"""Camera geometry for skills that locate things in images: rays through pixels,
their meeting with a plane or each other, projections of world points, pose and rotation
matrices (OpenCV convention, camera_to_world 4x4, intrinsics 3x3). Imports numpy;
nothing else of its own."""

import math

import numpy as np

from harness_perception.clients import Mask


def pose_matrix(pose):
    import numpy as np

    x, y, z, w, i, j, k = (float(v) for v in pose)
    norm = math.sqrt(w * w + i * i + j * j + k * k)
    w, i, j, k = w / norm, i / norm, j / norm, k / norm
    matrix = np.eye(4)
    matrix[:3, :3] = [[1 - 2 * (j * j + k * k), 2 * (i * j - w * k), 2 * (i * k + w * j)],
                      [2 * (i * j + w * k), 1 - 2 * (i * i + k * k), 2 * (j * k - w * i)],
                      [2 * (i * k - w * j), 2 * (j * k + w * i), 1 - 2 * (i * i + j * j)]]
    matrix[:3, 3] = [x, y, z]
    return matrix


def matrix_quaternion(rotation):
    """wxyz quaternion (w >= 0) of a 3x3 rotation matrix."""
    r = rotation
    trace = r[0][0] + r[1][1] + r[2][2]
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        q = [0.25 * s, (r[2][1] - r[1][2]) / s, (r[0][2] - r[2][0]) / s, (r[1][0] - r[0][1]) / s]
    elif r[0][0] > r[1][1] and r[0][0] > r[2][2]:
        s = math.sqrt(1.0 + r[0][0] - r[1][1] - r[2][2]) * 2
        q = [(r[2][1] - r[1][2]) / s, 0.25 * s, (r[0][1] + r[1][0]) / s, (r[0][2] + r[2][0]) / s]
    elif r[1][1] > r[2][2]:
        s = math.sqrt(1.0 + r[1][1] - r[0][0] - r[2][2]) * 2
        q = [(r[0][2] - r[2][0]) / s, (r[0][1] + r[1][0]) / s, 0.25 * s, (r[1][2] + r[2][1]) / s]
    else:
        s = math.sqrt(1.0 + r[2][2] - r[0][0] - r[1][1]) * 2
        q = [(r[1][0] - r[0][1]) / s, (r[0][2] + r[2][0]) / s, (r[1][2] + r[2][1]) / s, 0.25 * s]
    if q[0] < 0:
        q = [-v for v in q]
    return [float(v) for v in q]


def at_border(mask):
    """Whether a mask touches the image border (the object may extend beyond it)."""
    array = mask.array
    return bool(array[0].any() or array[-1].any() or array[:, 0].any() or array[:, -1].any())


def project(observation, camera, points):
    """World points (N x 3) -> pixel coordinates (N x 2) and depth along the camera axis."""
    points = np.atleast_2d(np.asarray(points, dtype=float))
    transform = observation.camera_to_world[camera]
    rotation, origin = transform[:3, :3], transform[:3, 3]
    in_camera = (points - origin) @ rotation
    depth = in_camera[:, 2]
    pixels = (observation.intrinsics[camera] @ (in_camera / depth[:, None]).T).T[:, :2]
    return pixels, depth


def pixel_ray(observation, camera, u, v):
    """Unit ray (origin, direction) in the world frame through pixel (u, v)."""
    transform = observation.camera_to_world[camera]
    direction_camera = np.linalg.solve(observation.intrinsics[camera], np.array([u, v, 1.0]))
    direction = transform[:3, :3] @ direction_camera
    return transform[:3, 3].copy(), direction / np.linalg.norm(direction)


def pixel_to_plane(observation, camera, u, v, z):
    """Intersect the ray through (u, v) with the horizontal plane at height z."""
    origin, direction = pixel_ray(observation, camera, u, v)
    if abs(direction[2]) < 1e-9:
        return None
    distance = (z - origin[2]) / direction[2]
    return None if distance <= 0 else origin + distance * direction


def triangulate(observation, pixels):
    """Least-squares 3D point from {camera: (u, v)} seen in two or more cameras."""
    if len(pixels) < 2:
        raise ValueError("triangulate needs pixels from at least two cameras")
    a = np.zeros((3, 3))
    b = np.zeros(3)
    for camera, (u, v) in pixels.items():
        origin, direction = pixel_ray(observation, camera, u, v)
        projector = np.eye(3) - np.outer(direction, direction)
        a += projector
        b += projector @ origin
    return np.linalg.solve(a, b)


def mask_to_plane(observation, camera, mask, z, step=4):
    """World points where the rays through the mask's pixels meet the plane at height z."""
    if not isinstance(mask, Mask):
        raise TypeError(f"mask must be a Mask from segment_text, got {type(mask).__name__}; "
                        "segment_text returns [] when nothing matches: check the list before indexing "
                        "and try a more descriptive prompt (e.g. 'white bowl' or a plural such as 'bowls')")
    points = [pixel_to_plane(observation, camera, u, v, z) for u, v in mask.pixels(step)]
    points = [p for p in points if p is not None]
    return np.array(points) if points else np.zeros((0, 3))
