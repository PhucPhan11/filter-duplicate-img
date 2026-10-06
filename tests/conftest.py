import random
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw


def make_picture(seed: int, size: tuple[int, int] = (640, 480)) -> Image.Image:
    """A deterministic picture with enough large-scale structure for a stable pHash."""
    rng = random.Random(seed)
    image = Image.new("RGB", size, tuple(rng.randrange(256) for _ in range(3)))
    draw = ImageDraw.Draw(image)
    for _ in range(12):
        x0, y0 = rng.randrange(size[0]), rng.randrange(size[1])
        x1, y1 = x0 + rng.randrange(60, 300), y0 + rng.randrange(60, 300)
        colour = tuple(rng.randrange(256) for _ in range(3))
        if rng.random() < 0.5:
            draw.rectangle((x0, y0, x1, y1), fill=colour)
        else:
            draw.ellipse((x0, y0, x1, y1), fill=colour)
    return image


@pytest.fixture
def library(tmp_path: Path) -> dict[str, Path]:
    """A folder holding one picture in several forms, plus an unrelated picture."""
    root = tmp_path / "library"
    (root / "sub").mkdir(parents=True)
    base = make_picture(1)

    paths = {
        "base": root / "base.png",
        "copy": root / "sub" / "copy.png",
        "resized": root / "resized.png",
        "jpeg": root / "recompressed.jpg",
        "rotated": root / "sub" / "rotated.jpg",
        "other": root / "other.png",
        "broken": root / "broken.jpg",
        "text": root / "notes.txt",
    }
    base.save(paths["base"])
    shutil.copy2(paths["base"], paths["copy"])
    base.resize((320, 240), Image.Resampling.LANCZOS).save(paths["resized"])
    base.save(paths["jpeg"], quality=60)
    # Stored sideways, with an EXIF tag saying how to turn it upright again.
    exif = Image.Exif()
    exif[0x0112] = 6
    base.transpose(Image.Transpose.ROTATE_90).save(paths["rotated"], quality=90, exif=exif)
    make_picture(2).save(paths["other"])
    paths["broken"].write_bytes(b"this is not a jpeg")
    paths["text"].write_text("not an image")
    paths["root"] = root
    return paths
