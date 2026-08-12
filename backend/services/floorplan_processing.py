"""
services/floorplan_processing.py — parses an uploaded floor-plan scan package
(the zip produced on-device by FloorPlanScanRecorder.kt) into structured stats.

This is deliberately scoped as parsing/diagnostics, not geometry reconstruction:
there is no real reconstruction algorithm to validate yet, so this module exists
to let a real scan be sanity-checked (frame count, pose spread, depth-value
ranges) before any reconstruction code is built on top of it.

Checked against a real device-captured scan (S21 Ultra, 2026-08-12, 50 frames):
  - pose is written as flat {tx,ty,tz,qx,qy,qz,qw} fields, NOT a
    {translation:[x,y,z]} array — the original assumption was wrong and has
    been corrected below (summarize() reads tx/ty/tz directly).
  - the DEPTH16 bit convention (low 13 bits = depth in mm, top 3 bits =
    confidence) looks consistent with real output: frames with raw values
    under 8191 decode to a sane 1.9-4.7m indoor range, and ~28% of frames in
    the sample had raw values above 8191 (confidence bits set), matching the
    documented format rather than contradicting it.
  - the first couple of frames in a scan can have all-zero depth (sensor not
    yet warmed up) — this is real, expected behavior, not a parse bug.
"""

import io
import json
import struct
import zipfile
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DepthFrameStats:
    width: int
    height: int
    row_stride: int
    raw_min: int
    raw_max: int
    raw_mean: float
    depth_mm_min: int
    depth_mm_max: int
    depth_mm_mean: float


@dataclass
class FrameInfo:
    index: int
    timestamp_ms: Optional[int]
    pose: Optional[dict]
    depth: Optional[DepthFrameStats]


@dataclass
class ParsedScan:
    scan_id: Optional[str]
    frame_count: int
    frames: list = field(default_factory=list)
    intrinsics: Optional[dict] = None
    warnings: list = field(default_factory=list)


def parse_depth_bytes(raw: bytes, width: int, height: int, row_stride: int) -> DepthFrameStats:
    """
    Unpack a DEPTH16 buffer (little-endian uint16 per pixel, row_stride bytes
    per row, may include padding beyond width*2 bytes).
    """
    raw_min = None
    raw_max = None
    raw_sum = 0
    depth_min = None
    depth_max = None
    depth_sum = 0
    count = 0

    for y in range(height):
        row_offset = y * row_stride
        for x in range(width):
            offset = row_offset + x * 2
            if offset + 2 > len(raw):
                continue
            (value,) = struct.unpack_from('<H', raw, offset)
            depth_mm = value & 0x1FFF

            if raw_min is None or value < raw_min:
                raw_min = value
            if raw_max is None or value > raw_max:
                raw_max = value
            raw_sum += value

            if depth_min is None or depth_mm < depth_min:
                depth_min = depth_mm
            if depth_max is None or depth_mm > depth_max:
                depth_max = depth_mm
            depth_sum += depth_mm

            count += 1

    if count == 0:
        raise ValueError('No depth pixels decoded (empty or truncated buffer)')

    return DepthFrameStats(
        width=width,
        height=height,
        row_stride=row_stride,
        raw_min=raw_min,
        raw_max=raw_max,
        raw_mean=raw_sum / count,
        depth_mm_min=depth_min,
        depth_mm_max=depth_max,
        depth_mm_mean=depth_sum / count,
    )


def parse_scan_package(zip_bytes: bytes) -> ParsedScan:
    """
    Parse a scan package zip (manifest.json + optional intrinsics.json +
    depth/*.bin files) into a ParsedScan. Raises ValueError if manifest.json
    is missing or unparsable.
    """
    warnings = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())

        if 'manifest.json' not in names:
            raise ValueError('manifest.json not found in scan package')

        manifest = json.loads(zf.read('manifest.json'))

        intrinsics = None
        if 'intrinsics.json' in names:
            try:
                intrinsics = json.loads(zf.read('intrinsics.json'))
            except (json.JSONDecodeError, ValueError):
                warnings.append('intrinsics.json present but unparsable')

        manifest_frames = manifest.get('frames', [])
        declared_count = manifest.get('frameCount')
        if declared_count is not None and declared_count != len(manifest_frames):
            warnings.append(
                f"manifest frameCount ({declared_count}) does not match "
                f"actual frame entries ({len(manifest_frames)})"
            )

        frames = []
        for idx, entry in enumerate(manifest_frames):
            depth_stats = None
            depth_file = entry.get('depthFile')
            if depth_file:
                if depth_file not in names:
                    warnings.append(f"frame {idx}: depthFile '{depth_file}' referenced but missing from zip")
                else:
                    depth_width = entry.get('depthWidth')
                    depth_height = entry.get('depthHeight')
                    depth_row_stride = entry.get('depthRowStride')
                    if not (depth_width and depth_height and depth_row_stride):
                        warnings.append(f"frame {idx}: depth dimensions missing, skipping depth parse")
                    else:
                        try:
                            depth_stats = parse_depth_bytes(
                                zf.read(depth_file), depth_width, depth_height, depth_row_stride
                            )
                        except ValueError as e:
                            warnings.append(f"frame {idx}: depth parse failed ({e})")

            frames.append(FrameInfo(
                index=idx,
                timestamp_ms=entry.get('timestampMs'),
                pose=entry.get('pose'),
                depth=depth_stats,
            ))

        return ParsedScan(
            scan_id=manifest.get('scanId'),
            frame_count=len(frames),
            frames=frames,
            intrinsics=intrinsics,
            warnings=warnings,
        )


def summarize(parsed: ParsedScan) -> dict:
    """Aggregate a ParsedScan into a concise API-response-friendly dict."""
    tx_vals, ty_vals, tz_vals = [], [], []
    depth_means, depth_mins, depth_maxs = [], [], []
    frames_with_depth = 0

    for f in parsed.frames:
        pose = f.pose or {}
        # FloorPlanScanRecorder.kt writes pose as flat tx/ty/tz/qx/qy/qz/qw
        # fields (confirmed against a real captured scan), not a
        # {translation: [x,y,z]} array.
        tx, ty, tz = pose.get('tx'), pose.get('ty'), pose.get('tz')
        if tx is not None and ty is not None and tz is not None:
            tx_vals.append(tx)
            ty_vals.append(ty)
            tz_vals.append(tz)
        if f.depth is not None:
            frames_with_depth += 1
            depth_means.append(f.depth.depth_mm_mean)
            depth_mins.append(f.depth.depth_mm_min)
            depth_maxs.append(f.depth.depth_mm_max)

    pose_bounds = None
    if tx_vals:
        pose_bounds = {
            'x': {'min': min(tx_vals), 'max': max(tx_vals)},
            'y': {'min': min(ty_vals), 'max': max(ty_vals)},
            'z': {'min': min(tz_vals), 'max': max(tz_vals)},
        }

    depth_summary = None
    if depth_means:
        depth_summary = {
            'mean_mm': sum(depth_means) / len(depth_means),
            'min_mm': min(depth_mins),
            'max_mm': max(depth_maxs),
        }

    return {
        'scanId': parsed.scan_id,
        'frameCount': parsed.frame_count,
        'framesWithDepth': frames_with_depth,
        'poseBounds': pose_bounds,
        'depth': depth_summary,
        'intrinsics': parsed.intrinsics,
        'warnings': parsed.warnings,
    }
