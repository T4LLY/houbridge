# Tasks

## 1. Native infrastructure and side-effect gate

- [ ] 1.1 Verify the existing cloned Scene Viewer plus `scene.flipbook(...)` triggers the required DM_SceneHook without creating a Flipbook ROP or any other scene node.
- [ ] 1.2 Stop and revise OpenSpec before further implementation if node-free hook triggering is not possible.
- [x] 1.3 Add the responsibility-separated native source layout and persistent/rebuildable DSO cache keyed by Houdini build and native-source hash.
- [x] 1.4 Compile/load the native capture component without visible Windows console windows while retaining bounded stdout/stderr diagnostics and structured failures.

## 2. Shared analysis request boundary

- [x] 2.1 Add shared pass/model/grid/curvature request types and validation without placing renderer logic in `capture_cmd.py`.
- [x] 2.2 Keep Beauty on the current capture path and route only non-beauty passes through the shared analysis boundary.
- [x] 2.3 Reuse the existing artifact publisher, screenshot scale/clamp rules, pane resolver, and temporary-workspace lifecycle.

## 3. Viewport Depth and Grid

- [x] 3.1 Add viewport `depth` through the validated private depth-attachment and CPU-linearization path, publishing PNG only.
- [x] 3.2 Add viewport `grid` using world-space unprojection and the validated X/Y/Z grid rendering.
- [x] 3.3 Cover active, directed, preset-view, `--pane`, `--scale`, and repeated `--model` behavior.

## 4. Camera Depth and Grid

- [x] 4.1 Route supported OBJ Camera analysis captures through the same Depth/Grid renderers.
- [x] 4.2 Route supported Camera SOP analysis captures through the same Depth/Grid renderers.
- [x] 4.3 Preserve camera composition and camera-resolution sizing with existing scale/clamp behavior.

## 5. Shared displayed-geometry layer and Normal

- [ ] 5.1 Extract one shared `DM_GeoDetail -> GU_Detail -> GT polygon mesh -> RV_Geometry` layer.
- [ ] 5.2 Add Normal for viewport and camera using that shared layer without scene attribute mutation.

## 6. Object ID

- [ ] 6.1 Add flat per-object Object ID rendering for viewport and camera on the shared displayed-geometry layer.
- [ ] 6.2 Verify excluded/non-selected objects do not contribute to the analysis image.

## 7. Curvature

- [ ] 7.1 Add the validated signed curvature approximation for viewport and camera.
- [ ] 7.2 Add `gray` and `rg` colormaps and curvature-scale validation/mapping.

## 8. CLI, presets, errors, and regression

- [ ] 8.1 Wire the specified analysis options into existing viewport/camera CLI commands without adding `capture model`.
- [ ] 8.2 Preserve exact existing Beauty success schemas and camera list/detail behavior.
- [ ] 8.3 Add structured tests for pass values, model paths, mode-specific options, preset restrictions, and native failures.
- [ ] 8.4 Run existing Capture regressions for pane discovery, viewport, camera, window, presets, artifact publication, and turntable.
- [ ] 8.5 Check touched file sizes/responsibilities and split debt before adding more behavior if any implementation file becomes inappropriately concentrated.

## 9. Real Houdini acceptance

- [ ] 9.1 Capture all five analysis passes from a real viewport and verify image semantics and absence of unwanted objects.
- [ ] 9.2 Capture all five analysis passes from supported real cameras and verify camera framing/resolution behavior.
- [ ] 9.3 Verify no scene node/flag mutation, no MPlay/render popup, no visible helper console, no EXR publication, and no incomplete artifact publication.
- [ ] 9.4 Strictly validate and archive this OpenSpec change only after the implementation and real-Houdini gates pass.

## 10. Deferred follow-up

- [ ] 10.1 After this change is accepted, specify turntable analysis passes in a separate OpenSpec change that reuses the shared renderer rather than duplicating it.
