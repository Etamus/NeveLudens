from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageChops, ImageFilter, ImageStat


@dataclass
class PerceptionState:
    step: int
    mean_luma: float
    contrast: float
    motion: float
    edge_density: float
    dark_ratio: float
    bright_ratio: float
    is_dark: bool
    is_low_motion: bool
    likely_loading: bool
    likely_static_screen: bool
    likely_menu_or_overlay: bool


class PerceptionAnalyzer:
    """Fast visual state extractor that does not alter the frame sent to the model."""

    def __init__(
        self,
        low_motion_threshold: float = 0.35,
        dark_luma_threshold: float = 8.0,
        loading_edge_threshold: float = 2.5,
    ):
        self.low_motion_threshold = low_motion_threshold
        self.dark_luma_threshold = dark_luma_threshold
        self.loading_edge_threshold = loading_edge_threshold
        self.previous_sample = None

    def analyze(self, image: Image.Image, step: int) -> PerceptionState:
        sample = image.convert("L").resize((64, 64), Image.Resampling.BILINEAR)
        stat = ImageStat.Stat(sample)
        mean_luma = float(stat.mean[0])
        contrast = float(stat.stddev[0])

        if self.previous_sample is None:
            motion = 255.0
        else:
            diff = ImageChops.difference(sample, self.previous_sample)
            motion = float(ImageStat.Stat(diff).mean[0])

        edges = sample.filter(ImageFilter.FIND_EDGES)
        edge_density = float(ImageStat.Stat(edges).mean[0])

        hist = sample.histogram()
        total = sum(hist) or 1
        dark_ratio = sum(hist[:12]) / total
        bright_ratio = sum(hist[245:]) / total

        is_dark = mean_luma <= self.dark_luma_threshold or dark_ratio > 0.92
        is_low_motion = motion <= self.low_motion_threshold
        likely_loading = is_dark and edge_density <= self.loading_edge_threshold
        likely_static_screen = is_low_motion and contrast > 3.0
        likely_menu_or_overlay = is_low_motion and edge_density > 5.0 and contrast > 18.0

        self.previous_sample = sample

        return PerceptionState(
            step=step,
            mean_luma=mean_luma,
            contrast=contrast,
            motion=motion,
            edge_density=edge_density,
            dark_ratio=dark_ratio,
            bright_ratio=bright_ratio,
            is_dark=is_dark,
            is_low_motion=is_low_motion,
            likely_loading=likely_loading,
            likely_static_screen=likely_static_screen,
            likely_menu_or_overlay=likely_menu_or_overlay,
        )
