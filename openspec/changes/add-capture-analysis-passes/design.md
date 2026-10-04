# Design: Capture Analysis Passes

## Decision

Treat model analysis as a rendering dimension of the existing Capture commands, not as a new view-source command.

The public model is:

```text
view source / composition     render pass                 geometry filter
-------------------------     ------------------------    -------------------------
viewport active/directed  +   beauty (default)        +   all displayed geometry
camera OBJ/SOP                depth                       or repeated --model paths
                              grid
                              normal
                              object-id
                              curvature
```

`viewport` and `camera` continue to own *where and how the scene is viewed*. A shared analysis layer owns *how eligible displayed geometry is rendered*. `--model` owns only *which displayed geometry contributes to a non-beauty pass*.

## Public compatibility boundary

`beauty` remains the default. An invocation that does not use the new options must follow the pre-change path and preserve the current output exactly at the public-contract level.

The following remain unchanged:

- Scene Viewer `--pane` selection semantics,
- directed viewport selection and active-viewport composition,
- camera discovery and detail schemas,
- OBJ Camera and Camera SOP support,
- camera resolution as camera-capture source dimensions,
- `--scale` and screenshot maximum clamping,
- single-image `{"path":"..."}` output,
- multi-direction viewport `{"captures":[...]}` output,
- `viewport...png` / `camera...png` publication kinds.

No pass name is added to successful JSON. The caller already selected the pass in the command invocation.

## Analysis-pass options

`--pass` accepts exactly:

```text
beauty depth grid normal object-id curvature
```

The default is `beauty`.

Repeatable `--model` is valid only for non-beauty passes. Each value identifies an absolute OBJ node path. Omission means every currently displayed geometry object may contribute. Supplying one or more paths filters analysis rendering to displayed geometry owned by those exact OBJ objects.

Model filtering does not alter composition:

- directed viewport capture keeps the existing `frameAll()` behavior over the currently displayed scene,
- active viewport capture preserves the existing composition,
- camera capture preserves camera framing,
- filtering occurs only when the analysis image is rendered.

This separation avoids making `--model` a second view-source or camera-framing concept.

`grid` requires `--unit FLOAT`, finite and greater than zero. `--unit` is invalid for every other pass.

`curvature` accepts:

```text
--curvature-scale FLOAT             default 1.0; finite and > 0
--curvature-colormap gray|rg        default rg
```

Explicit curvature options are invalid for non-curvature passes. The defaults are internal effective values for curvature and do not make an otherwise ordinary Beauty invocation conflict.

## Presets

Beauty viewport capture keeps the existing screenshot-preset contract unchanged.

For a non-beauty viewport pass, a preset may provide only `view`. That value participates in the existing direction-selection rules, including explicit direction flags overriding preset `view`.

`shading`, `overlays`, and `attributes` describe Houdini Beauty viewport presentation and must not silently alter or be silently ignored by an analysis renderer. Their presence with a non-beauty pass is therefore a structured `capture_analysis_preset_invalid` error. `crop` remains invalid for viewport capture under the existing rule.

Camera capture still has no screenshot-preset option.

## Shared analysis boundary

Viewport and camera must not grow separate copies of the five renderers. Host orchestration should converge on one analysis request carrying at least:

```text
pass
model paths
view/projection state supplied by the selected temporary capture viewer
effective output dimensions
grid unit when applicable
curvature settings when applicable
```

The Houdini/native side should share displayed-geometry extraction and renderer implementations. In particular, Normal, Object ID, and Curvature use the validated direct displayed-geometry path:

```text
DM_GeoDetail
-> displayed GU_Detail
-> GT polygon mesh
-> RV_Geometry
-> direct draw
```

The implementation must not duplicate this conversion separately for those three passes.

## Pass semantics

### Beauty

Use the existing viewport/camera capture path unchanged.

### Depth

Render the eligible displayed geometry to a private depth attachment, linearize valid geometry depth using the active viewport projection, normalize the captured geometry range for preview, and publish only the preview PNG. Background pixels are black. No EXR is produced.

### Grid

Use the same depth/unprojection basis as Depth and draw a world-space grid on the eligible model surfaces. Axis colors are X=red, Y=green, Z=blue. `--unit` is the world-space grid spacing. The existing validated line-width/antialiasing behavior from the probe is preserved rather than redesigned by this change.

### Normal

Render displayed polygon geometry directly. Encode view-space normal components from `[-1, 1]` into RGB `[0, 1]`. Existing point normals are used when available; any fallback normal generation occurs only in transient renderer data and must not add or edit Houdini scene attributes.

### Object ID

Render each eligible OBJ object with one flat non-lighted color and a black background. Materials, lighting, and gradients do not contribute. Colors must distinguish objects within the capture; this change does not promise a persistent color identity across separate captures.

### Curvature

Use displayed polygon world-space positions, point normals, and vertex neighborhood relationships to compute the validated signed curvature approximation intended for AI/VLM shape interpretation. It is not specified as an exact differential-geometry curvature measurement.

At effective scale `1.0`, automatic normalization is used unchanged. Values above `1.0` strengthen the mapped curvature response and values below `1.0` weaken it.

`rg` maps convex response to red, concave response to green, flat response to black, and blue to zero. `gray` maps curvature magnitude from black toward white.

## Scene and UI side effects

Analysis capture is read-only with respect to the user's Houdini scene. It must not:

- create temporary or persistent scene nodes,
- create temporary cameras,
- add SOPs or wrangles,
- change display or render flags,
- change the user's live Scene Viewer state,
- open MPlay,
- open a render window,
- spawn a visible Windows console for native build/helper execution.

The existing cloned/temporary Scene Viewer approach remains allowed because it does not edit scene contents or the user's live viewer.

The probe currently has a path that uses a temporary Flipbook ROP to trigger the SceneHook. Phase 1 must first prove that the existing cloned Scene Viewer plus `scene.flipbook(...)` can trigger the required hook without creating that ROP. If it cannot, implementation must stop and this specification must be revisited rather than silently weakening the no-scene-node contract.

## Artifact boundary

Each requested pass/view produces one PNG and is published through the existing completed-artifact boundary. Analysis capture does not publish EXR intermediates or expose native build/workspace files.

The existing screenshot kind remains `viewport` or `camera`, so readable sequencing and retention behavior stay compatible.

## Turntable boundary

Turntable is deliberately not changed in this proposal. No `--pass`, `--model`, grid, or curvature options are added to `capture turntable` yet.

The internal analysis request/renderer boundary should nevertheless be independent of viewport/camera command parsing so a later OpenSpec change can feed turntable frame view/projection state into the same renderer after viewport and camera behavior is accepted in real Houdini.
