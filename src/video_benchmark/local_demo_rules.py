"""Deterministic review rules in an importable module, as Pixeltable UDFs require.

The small execution traces let the demo prove reuse and scoped refresh.
"""

import pixeltable as pxt
from PIL import Image

preparations: list[float] = []
reviews: list[str] = []


@pxt.udf
def mean_brightness(image: Image.Image) -> float:
    import numpy as np

    brightness = float(np.asarray(image).mean())
    preparations.append(brightness)
    return brightness


@pxt.udf
def review_result(rows: list[dict], request_id: str) -> str:
    reviews.append(request_id)
    return f'{len(rows)} frames meet the review policy'
