"""Builds the video source for an operator camera from its configuration entry."""

from typing import Union

from mission_control.core.config import CameraSourceConfig
from mission_control.core.logger import get_logger
from mission_control.video.source import (
    BaseVideoSource,
    FallbackVideoSource,
    OfflineVideoSource,
    OpenCVVideoSource,
    RealSenseVideoSource,
    TestPatternVideoSource,
)

logger = get_logger("video_factory")

SOURCE_SYNTHETIC = "synthetic"
SOURCE_REALSENSE = "realsense"
SOURCE_OPENCV = "opencv"
SOURCE_NONE = "none"


def _synthetic(camera_name: str, config: CameraSourceConfig) -> TestPatternVideoSource:
    return TestPatternVideoSource(
        width=config.width,
        height=config.height,
        target_fps=max(1, config.fps),
        camera_name=camera_name,
    )


def _opencv_uri(url: str) -> Union[str, int]:
    """A purely numeric URL is a local device index (e.g. "0" for the first webcam)."""
    return int(url) if url.isdigit() else url


def create_camera_source(camera_name: str, config: CameraSourceConfig) -> BaseVideoSource:
    """Returns the source for one camera ("FRONT" / "REAR").

    Nothing is opened here and no SDK is imported: a missing RealSense SDK or an
    absent device is only discovered when the stream is started, where it either
    falls back to the synthetic pattern (if configured) or is reported as an error.
    """
    offline = OfflineVideoSource(f"{camera_name} CAMERA OFFLINE")
    source_type = (config.type or SOURCE_NONE).strip().lower()

    if source_type == SOURCE_SYNTHETIC:
        return _synthetic(camera_name, config)

    if source_type == SOURCE_REALSENSE:
        source: BaseVideoSource = RealSenseVideoSource(
            width=config.width, height=config.height, fps=config.fps, serial=config.serial
        )
        primary_name = "D456"
    elif source_type == SOURCE_OPENCV:
        if not config.url.strip():
            logger.warning(f"{camera_name} camera: type 'opencv' needs a url; camera is OFFLINE.")
            return offline
        source = OpenCVVideoSource(_opencv_uri(config.url.strip()))
        primary_name = f"{camera_name} CAMERA"
    else:
        if source_type != SOURCE_NONE:
            logger.warning(
                f"{camera_name} camera: unknown source type '{config.type}'; camera is OFFLINE."
            )
        return offline

    if config.fallback_to_synthetic:
        return FallbackVideoSource(source, _synthetic(camera_name, config), primary_name)
    return source
