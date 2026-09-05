"""Build a single-file HTML+SVG illustration from traced rings.

This is the SVG variant of render.py: every visible mark is an SVG <path>
(fill colors or linearGradient / even-odd holes), embedded inline in one HTML
file with no external assets. The tracing pipeline (regions, contours,
gradient fitting) is shared with the CSS emitter.
"""

import html
import math

import cv2
import numpy as np

from .geometry import bridge_rings, component_rings, hex_color, number
from .quality import Rasterizer
from .regions import label_components


def color_order(labels, palette):
    return sorted(np.unique(labels), key=lambda i: (-float(palette[i] @ np.array([.2126, .7152, .0722])), int(i)))


def same_as_matte(rgb, background):
    return int(np.abs(rgb.astype(np.int16) - background).max()) <= 3


def paint_for_region(reference, mask, x, y, width, height, gradients):
    """Return (css_paint, svg_gradient_key). css_paint drives offline scoring;
    svg_gradient_key (or None for solid) feeds the SVG gradients in <defs>.

    The key is a tuple tagged by kind: ``(0, start, end, x1, y1, x2, y2)`` for a
    linear gradient, (1, center, edge, cx, cy, r) for a radial gradient.
    """
    ys, xs = np.nonzero(mask)
    samples = reference[y + ys, x + xs].astype(float)
    solid = hex_color(samples.mean(axis=0))
    if not gradients or len(xs) < 45 or min(width, height) < 5:
        return solid, None
    if len(xs) > 6000:
        step = math.ceil(len(xs) / 6000)
        xs, ys, samples = xs[::step], ys[::step], samples[::step]
    design = np.column_stack((xs + .5 - width / 2, ys + .5 - height / 2, np.ones(len(xs))))
    coeff, _, _, _ = np.linalg.lstsq(design, samples, rcond=None)
    axes, _, _ = np.linalg.svd(coeff[:2], full_matrices=False)
    direction = axes[:, 0]
    slope = direction @ coeff[:2]
    length = abs(direction[0]) * width + abs(direction[1]) * height
    low, high = np.percentile(samples, (3, 97), axis=0)
    start = np.clip(coeff[2] - slope * length / 2, low, high)
    end = np.clip(coeff[2] + slope * length / 2, low, high)
    if np.max(np.abs(end - start)) < 3:
        return solid, None
    cx = x + width / 2.0
    cy = y + height / 2.0
    x1, y1 = cx - direction[0] * length / 2, cy - direction[1] * length / 2
    x2, y2 = cx + direction[0] * length / 2, cy + direction[1] * length / 2
    # userSpaceOnUse gradient line in absolute pixel coordinates.
    key = (0, hex_color(start), hex_color(end), round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1))
    css = f"linear-gradient({number(math.degrees(math.atan2(direction[0], -direction[1])) % 360, 1)}deg,{key[1]},{key[2]})"
    return css, key


def radial_for_region(reference, mask, x, y, width, height):
    """Detect a roundish, radially shaded blob and return a radial gradient key.

    Used for soft circular highlights (blush, glows) in the Astra style.
    """
    if min(width, height) < 6 or not (0.5 <= width / height <= 2.0):
        return None
    ys, xs = np.nonzero(mask)
    if len(xs) < 50 or len(xs) > 40000:
        return None
    samples = reference[y + ys, x + xs].astype(float)
    dx = xs + .5 - width / 2.0
    dy = ys + .5 - height / 2.0
    dist = np.sqrt(dx * dx + dy * dy)
    rmax = float(max(np.hypot(width / 2.0, height / 2.0), 1e-9))
    inner = dist <= rmax * 0.45
    outer = dist >= rmax * 0.9
    if inner.sum() < 4 or outer.sum() < 4:
        return None
    center = samples[inner].mean(axis=0)
    edge = samples[outer].mean(axis=0)
    if np.max(np.abs(center - edge)) < 3:
        return None
    return (1, hex_color(center), hex_color(edge),
            round(x + width / 2.0, 1), round(y + height / 2.0, 1), round(rmax, 1))


def ring_path_d(rings, digits=2, smooth=False):
    """Encode rings as one even-odd SVG path d string; each ring is a subpath.

    When ``smooth`` is set each ring is rounded with a closed Catmull-Rom spline
    converted to cubic Beziers, giving the hand-drawn look of the Astra pieces.
    """
    subpaths = []
    vertices = 0
    for ring in rings:
        vertices += len(ring)
        if smooth and len(ring) >= 4:
            subpaths.append(catmull_d(ring, digits))
        else:
            coords = " ".join(f"{number(v, digits)} {number(u, digits)}" for v, u in ring)
            subpaths.append("M" + coords + "Z")
    return "".join(subpaths), vertices


def catmull_d(ring, digits=2):
    """Closed Catmull-Rom spline through ring points as cubic Bezier commands."""
    pts = np.asarray(ring, float)
    n = len(pts)
    parts = []
    for i in range(n):
        p0 = pts[(i - 1) % n]
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        p3 = pts[(i + 2) % n]
        c1 = p1 + (p2 - p0) / 6.0
        c2 = p2 - (p3 - p1) / 6.0
        if i == 0:
            parts.append(f"M{number(p1[0], digits)} {number(p1[1], digits)}")
        parts.append(f"C{number(c1[0], digits)} {number(c1[1], digits)} "
                     f"{number(c2[0], digits)} {number(c2[1], digits)} "
                     f"{number(p2[0], digits)} {number(p2[1], digits)}")
    parts.append("Z")
    return "".join(parts)


def mask_svg_path(mask, epsilon, min_area, digits=2):
    """Trace a boolean mask into an even-odd SVG path d (canvas-space pixels)."""
    contours, _ = cv2.findContours(np.pad(mask, 1), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    rings = []
    for contour in contours:
        if abs(cv2.contourArea(contour)) < min_area:
            continue
        points = cv2.approxPolyDP(contour, epsilon, True)[:, 0, :].astype(float) - 1
        if len(points) >= 3:
            rings.append(points)
    if not rings:
        return "", 0
    d, vertices = ring_path_d(rings, digits)
    return d, vertices


def path_attr(value, digits=2):
    return number(value, digits)


class BudgetExceeded(ValueError):
    def __init__(self, byte_count):
        super().__init__("HTML exceeds --max-output-mb; reduce --max-width/--colors, raise the limit, or use --fit.")
        self.byte_count = byte_count


class SvgContourRenderer:
    def __init__(self, reference, background, epsilon, gradients, max_bytes, score=False, smooth=False, radial=True):
        self.reference = reference
        self.height, self.width = reference.shape[:2]
        self.background = np.array(background)
        self.epsilon = epsilon
        self.gradients = gradients
        self.max_bytes = max_bytes
        self.smooth = smooth
        self.radial = radial
        self.byte_count = 0
        self.gradient_ids = {}
        self.gradient_defs = []
        self.raster = Rasterizer((self.width, self.height), background) if score else None
        self.stats = {"shapes": 0, "gradient_fills": 0, "polygon_vertices": 0,
                      "interior_holes": 0, "underpainting_shapes": 0}

    def account(self, text):
        self.byte_count += len(text.encode("utf-8"))
        if self.byte_count > self.max_bytes:
            raise BudgetExceeded(self.byte_count)
        return text

    def gradient_ref(self, key):
        if key not in self.gradient_ids:
            gid = f"g{len(self.gradient_ids)}"
            self.gradient_ids[key] = gid
            if key[0] == 1:
                _, center, edge, cx, cy, radius = key
                grad = (f'<radialGradient id="{gid}" gradientUnits="userSpaceOnUse" '
                        f'cx="{path_attr(cx)}" cy="{path_attr(cy)}" r="{path_attr(radius)}">'
                        f'<stop offset="0" stop-color="{center}"/><stop offset="1" stop-color="{edge}"/>'
                        f'</radialGradient>')
            else:
                _, start, end, x1, y1, x2, y2 = key
                grad = (f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" '
                        f'x1="{path_attr(x1)}" y1="{path_attr(y1)}" x2="{path_attr(x2)}" y2="{path_attr(y2)}">'
                        f'<stop offset="0" stop-color="{start}"/><stop offset="1" stop-color="{end}"/>'
                        f'</linearGradient>')
            self.gradient_defs.append(grad)
        return self.gradient_ids[key]

    def shape(self, rings, css_paint, svg_fill):
        """Emit one SVG path. svg_fill is a hex color or a url(#gN) reference."""
        if not rings:
            return ""
        d, vertices = ring_path_d(rings, smooth=self.smooth)
        fill = svg_fill
        element = f'<path d="{d}" fill="{fill}" fill-rule="evenodd"/>'
        self.stats["shapes"] += 1
        self.stats["polygon_vertices"] += vertices
        if self.raster is not None:
            all_points = np.concatenate(rings)
            origin = all_points.min(axis=0)
            size = all_points.max(axis=0) - origin
            if np.any(size <= 0):
                return ""
            self.raster.fill_rings(bridge_rings(rings), origin, size, css_paint)
        return self.account(element)

    def foreground(self, labels, palette, progress):
        groups = []
        ids, colors_by_component, areas, boxes, centers = label_components(labels)
        components_of = {}
        for component in range(1, len(colors_by_component)):
            components_of.setdefault(int(colors_by_component[component]), []).append(component)
        order = color_order(labels, palette)
        for position, color in enumerate(order):
            rgb = palette[color]
            if same_as_matte(rgb, self.background):
                continue
            color_parts = []
            small_groups = {}
            for component in components_of.get(int(color), ()):
                x, y, width, height = map(int, boxes[component])
                area = int(areas[component])
                mask = (ids[y:y + height, x:x + width] == component).astype(np.uint8)
                if area >= 24:
                    if self.radial:
                        grad = radial_for_region(self.reference, mask, x, y, width, height)
                        if grad is not None:
                            css_paint, grad = hex_color(rgb), grad
                        else:
                            css_paint, grad = paint_for_region(self.reference, mask, x, y, width, height, self.gradients)
                    else:
                        css_paint, grad = paint_for_region(self.reference, mask, x, y, width, height, self.gradients)
                else:
                    css_paint, grad = hex_color(rgb), None
                for rings in component_rings(mask, x, y, area, self.epsilon):
                    self.stats["interior_holes"] += len(rings) - 1
                    if area < 24:
                        key = tuple((centers[component] // 160).astype(int))
                        small_groups.setdefault(key, []).extend(rings)
                    else:
                        svg_fill = f"url(#{self.gradient_ref(grad)})" if grad else css_paint
                        element = self.shape(rings, css_paint, svg_fill)
                        if element:
                            color_parts.append(element)
                            self.stats["gradient_fills"] += int(bool(grad))
            for rings in small_groups.values():
                element = self.shape(rings, hex_color(rgb), hex_color(rgb))
                if element:
                    color_parts.append(element)
            if color_parts:
                tag = hex_color(rgb)
                parts = f'<g id="s{position}" data-color="{tag}">' + "".join(color_parts) + "</g>"
                groups.append(parts)
            if position % 32 == 0:
                progress(f"Trace {position + 1}/{len(order)} colors: {self.stats['shapes']} shapes")
        return "\n".join(groups)

    def underpainting(self):
        if min(self.width, self.height) < 8:
            return ""
        difference = np.abs(self.reference.astype(np.int16) - self.background).max(axis=2)
        silhouette = cv2.medianBlur((difference > 9).astype(np.uint8), 3)
        silhouette = cv2.erode(silhouette, np.ones((5, 5), np.uint8))
        clip_d, vertices = mask_svg_path(silhouette, .5, 8)
        if not clip_d:
            return ""
        self.stats["polygon_vertices"] += vertices
        scale = min(1, 516 / self.width, 1 / 3)
        small = cv2.resize(self.reference, (max(2, round(self.width * scale)), max(2, round(self.height * scale))), interpolation=cv2.INTER_AREA)
        small = cv2.medianBlur(small, 3)
        from .regions import quantize
        labels, palette = quantize(small, 48)
        paths = []
        for color in color_order(labels, palette):
            rgb = palette[color]
            if same_as_matte(rgb, self.background):
                continue
            mask = cv2.dilate((labels == color).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
            d, count = mask_svg_path(mask, .26, 1)
            if d:
                paths.append(f'<path d="{d}" fill="{hex_color(rgb)}"/>')
                if self.raster is not None:
                    full = cv2.resize(mask, (self.width, self.height), interpolation=cv2.INTER_NEAREST)
                    self.raster.fill_mask(full > 0, 0, 0, hex_color(rgb))
                self.stats["polygon_vertices"] += count
                self.stats["shapes"] += 1
                self.stats["underpainting_shapes"] += 1
        if not paths:
            return ""
        group = (f'<g id="underpainting" clip-path="url(#under)">' + "".join(paths) + "</g>")
        return self.account(f'<clipPath id="under"><path d="{clip_d}"/></clipPath>') + "\n" + group


def collect_defs(renderer):
    return "\n".join(renderer.gradient_defs)


def render_svg_document(reference, labels, palette, original_size, *, background, title,
                        epsilon, gradients, underpainting, max_bytes, progress, score=False,
                        smooth=False, radial=True):
    renderer = SvgContourRenderer(reference, background, epsilon, gradients, max_bytes, score,
                                  smooth=smooth, radial=radial)
    foundation = renderer.underpainting() if underpainting else ""
    shapes = renderer.foreground(labels, palette, progress)
    width, height = original_size
    matte = hex_color(background)
    label = html.escape(title, quote=True)
    defs = collect_defs(renderer)
    # The clipPath def referenced by the underpainting group must live in <defs>.
    defs_block = defs
    if foundation:
        # Extract the clipPath element from the foundation for placement in defs.
        import re
        m = re.search(r"<clipPath[^>]*>.*?</clipPath>", foundation, re.S)
        if m:
            defs_block = (defs + "\n" + m.group(0)).strip()
            found = m.group(0)
            foundation = foundation.replace(found + "\n", "").replace(found, "")
    document = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; script-src 'none'; connect-src 'none'; font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
<title>{label}</title>
<style>
html,body{{margin:0;min-height:100%;background:{matte}}}
.illustration{{display:block;width:min(100%,{renderer.width}px);height:auto;margin:0 auto;background:{matte};contain:layout paint}}
@media print{{@page{{margin:0}}.illustration{{width:100%;print-color-adjust:exact;-webkit-print-color-adjust:exact}}}}
</style>
</head>
<body>
<!-- Offline contour tracing. Every visible mark is an inline SVG path. -->
<main class="illustration" role="img" aria-label="{label}">
<svg viewBox="0 0 {renderer.width} {renderer.height}" xmlns="http://www.w3.org/2000/svg" width="100%" preserveAspectRatio="xMidYMid meet" role="presentation" aria-hidden="true">
<defs>
{defs_block}
</defs>
{foundation}
{shapes}
</svg>
</main>
</body>
</html>
'''
    if len(document.encode("utf-8")) > max_bytes:
        raise BudgetExceeded(len(document.encode("utf-8")))
    if renderer.raster is not None:
        detail, thumbnail = renderer.raster.errors(reference)
        renderer.stats["similarity"] = {"mae": detail, "mae_thumbnail": thumbnail}
    return document, renderer.stats
