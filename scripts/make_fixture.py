"""Generate the project's original diagnostic artwork; no downloaded assets."""

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def create_fixture(path):
    width, height = 600, 760
    image = Image.new("RGB", (width, height), "#faf8f2")
    yy, xx = np.mgrid[:height, :width]
    # Tilted ribbons test long contours, smooth shading and narrow negative space.
    for center, shift in [(230, 0), (395, 56)]:
        distance = np.sqrt(((xx - center - .22 * (yy - 340)) / 125) ** 2 + ((yy - 335 - shift) / 245) ** 2)
        mask = (distance < 1) & (distance > .68)
        color = np.stack((35 + xx * .12, 130 + yy * .12, 143 + yy * .08), axis=2).clip(0, 255).astype(np.uint8)
        pixels = np.array(image)
        pixels[mask] = color[mask]
        image = Image.fromarray(pixels)
    # A shaded sphere exercises per-region least-squares gradients.
    radius = np.sqrt((xx - 226) ** 2 + (yy - 432) ** 2)
    mask = radius < 105
    light = np.clip(1 - np.sqrt(((xx - 190) / 210) ** 2 + ((yy - 390) / 210) ** 2), 0, 1)
    color = np.stack((196 + 59 * light, 54 + 120 * light, 68 + 79 * light), axis=2).clip(0, 255).astype(np.uint8)
    pixels = np.array(image)
    pixels[mask] = color[mask]
    image = Image.fromarray(pixels)
    draw = ImageDraw.Draw(image)
    # Small ink marks must survive conservative region merging.
    for offset in range(0, 150, 10):
        draw.line((75 + offset, 612, 100 + offset, 650), fill="#233c47", width=2)
    draw.ellipse((424, 560, 492, 628), fill="#233c47")
    draw.ellipse((440, 576, 476, 612), fill="#faf8f2")
    for x in (82, 102, 122, 142):
        draw.ellipse((x, 94, x + 7, 101), fill="#233c47")
    draw.line((80, 76, 518, 76), fill="#b4c7bf", width=1)
    draw.line((80, 690, 518, 690), fill="#b4c7bf", width=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path, nargs="?", default=Path("docs/contour-study.png"))
    create_fixture(parser.parse_args().output)
