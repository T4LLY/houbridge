# Add Capture Analysis Passes

## Why

Houbridge already has stable `capture viewport` and `capture camera` commands that own Scene Viewer selection, camera resolution, scaling, temporary artifacts, and public JSON output. The validated model-capture probe adds five AI/VLM-oriented renderings, but exposing those renderings through a separate `capture model` command would duplicate view-source semantics and make `--pane` and camera selection mean different things in adjacent Capture commands.

The analysis renderings should therefore be additional render passes of the existing viewport and camera capture surfaces rather than a new capture target.

## What Changes

- Add `--pass beauty|depth|grid|normal|object-id|curvature` to `capture viewport` and `capture camera`; `beauty` is the default and preserves current behavior.
- Add repeatable `--model OBJ_PATH` filtering for non-beauty passes. Omitting it means all currently displayed geometry is eligible; supplying it limits rendered analysis geometry without changing view composition or camera framing.
- Add `--unit FLOAT` for `grid`, plus `--curvature-scale FLOAT` and `--curvature-colormap gray|rg` for `curvature`.
- Keep the existing viewport/camera success JSON schemas, pane-selection rules, scaling, artifact publication, and readable filename kinds unchanged.
- Define the five analysis-pass image semantics and require them to share one internal analysis-rendering boundary across viewport and camera capture.
- Preserve scene state and suppress visible render/UI side effects during analysis capture.
- Leave turntable analysis passes outside this change. The shared renderer should remain reusable so turntable can be added as a later change after viewport/camera acceptance passes.

## Specification Impact

This change modifies the `command-capture` capability and adds analysis-rendering requirements to the `capture` capability. It does not change the `output-policy`, `temporary-artifact`, camera discovery/detail schemas, window capture, or turntable command contract.

## Scope

In scope:

- viewport analysis passes,
- OBJ model filtering for analysis output,
- camera analysis passes for currently supported OBJ Camera and Camera SOP sources,
- depth, world grid, view normal, object ID, and curvature PNGs,
- mode-specific CLI validation,
- existing viewport/camera JSON response shapes,
- no-persistent-scene-change and no-popup behavior,
- architecture that can later be reused by turntable.

Out of scope:

- `capture model` as a new public command,
- turntable `--pass`,
- analysis passes for window capture,
- Beauty model filtering,
- silhouette, world-position, or wireframe passes,
- animation/frame-range image sequences,
- EXR or other numeric depth output,
- automatic camera or scene setup.
