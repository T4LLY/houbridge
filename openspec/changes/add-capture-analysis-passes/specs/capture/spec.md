## ADDED Requirements

### Requirement: Render non-beauty analysis passes through one shared viewport-camera boundary

Capture SHALL treat `depth`, `grid`, `normal`, `object-id`, and `curvature` as non-beauty render passes that can be driven by either the existing viewport composition path or the existing supported-camera composition path. Viewport and camera SHALL share the same analysis renderer implementations rather than owning duplicate pass implementations.

Beauty SHALL continue to use the existing Beauty capture path. Window capture and turntable SHALL remain outside the analysis-rendering path in this change.

The analysis renderer SHALL consume the view/projection state established by the selected temporary capture viewer. Viewport capture SHALL therefore keep the existing active/directed view semantics, while camera capture SHALL keep the existing OBJ Camera / Camera SOP framing and camera-resolution semantics.

#### Scenario: Viewport normal pass uses viewport composition
- **WHEN** a Normal pass is requested from the active viewport
- **THEN** the analysis renderer uses the temporary viewport's effective view/projection state
- **AND** the user's live Scene Viewer is not reoriented

#### Scenario: Camera depth pass uses camera composition
- **WHEN** a Depth pass is requested through a supported camera
- **THEN** the analysis renderer uses that camera's effective view/projection state
- **AND** the camera is not reframed

#### Scenario: Beauty bypasses the analysis renderer
- **WHEN** the effective pass is Beauty
- **THEN** Capture follows the existing Beauty image path and public behavior

#### Scenario: Turntable remains outside this change
- **WHEN** turntable capture is requested
- **THEN** it continues to use its existing Beauty frame path
- **AND** no analysis renderer is selected by this change

### Requirement: Filter analysis geometry without changing composition or Houdini scene state

For non-beauty passes, omitted model filtering SHALL make all currently displayed geometry eligible. When model paths are supplied, Capture SHALL include only currently displayed geometry owned by the exact selected OBJ objects. Model selection SHALL filter render contribution only and SHALL NOT alter viewport/camera composition, display flags, render flags, current frame, or object visibility state.

Directed viewport capture SHALL retain its existing framing behavior over all currently displayed geometry/objects before analysis filtering is applied. Active viewport capture SHALL preserve its source composition. Camera capture SHALL preserve camera composition.

Analysis geometry SHALL be read from the currently displayed Houdini geometry/cache at the current frame. Capture SHALL NOT implement filtering by adding temporary SOPs, Attribute Wrangles, replacement geometry, temporary cameras, or scene nodes.

#### Scenario: Model filter is omitted
- **WHEN** a non-beauty capture is requested without model paths
- **THEN** all currently displayed geometry may contribute to the analysis image

#### Scenario: Model filter selects two objects
- **WHEN** two valid OBJ model paths are supplied
- **THEN** only displayed geometry owned by those objects contributes to the analysis image
- **AND** other visible objects do not contribute

#### Scenario: Directed capture has a model filter
- **WHEN** a directed viewport analysis capture supplies model paths
- **THEN** the temporary viewport still uses the existing frame-all-displayed-geometry composition rule
- **AND** model filtering is applied only to analysis rendering

#### Scenario: Camera capture has a model filter
- **WHEN** a camera analysis capture supplies model paths
- **THEN** the camera composition is preserved
- **AND** model filtering is applied only to analysis rendering

### Requirement: Produce the specified Depth and Grid analysis images

Depth SHALL render eligible displayed geometry to a private depth attachment, derive valid geometry depth using the active capture projection, linearize that depth, and normalize the captured valid geometry range into a preview image. Pixels outside eligible geometry SHALL be black. The published artifact SHALL be PNG only; Capture SHALL NOT publish a linear-depth EXR.

Grid SHALL use the same eligible geometry depth and world-space unprojection basis and SHALL overlay world-space grid planes on model surfaces. Grid spacing SHALL be the positive finite `unit` supplied by the command contract. Grid axis colors SHALL be X=red, Y=green, and Z=blue. The validated probe line-width and antialiasing behavior SHALL be preserved rather than replaced by a new public line-width option.

#### Scenario: Capture Depth
- **WHEN** a Depth analysis pass succeeds
- **THEN** valid geometry depth is linearized and mapped into the PNG preview
- **AND** background pixels are black
- **AND** no EXR artifact is published

#### Scenario: Capture Grid
- **WHEN** a Grid analysis pass succeeds with unit `1.0`
- **THEN** the PNG contains world-space grid spacing of one unit on eligible model surfaces
- **AND** X, Y, and Z grid responses are red, green, and blue respectively

### Requirement: Produce Normal through shared displayed polygon geometry

Normal SHALL use the displayed geometry direct path represented conceptually as `DM_GeoDetail -> displayed GU_Detail -> GT polygon mesh -> RV_Geometry -> direct draw`. It SHALL encode view-space normal components from `[-1, 1]` into RGB `[0, 1]` and SHALL render background pixels black.

Existing point normals SHALL be used when available. If renderer-side fallback normals are needed, they SHALL exist only in transient render data and SHALL NOT add or modify Houdini scene attributes.

The displayed-geometry conversion layer SHALL be shared with Object ID and Curvature rather than copied into three independent renderer implementations.

#### Scenario: Capture Normal
- **WHEN** a Normal analysis pass succeeds
- **THEN** eligible displayed polygon geometry is encoded with view-space normals in RGB
- **AND** no temporary Normal SOP or persistent normal attribute is created

#### Scenario: Displayed geometry lacks point normals
- **WHEN** renderer-side normal generation is required
- **THEN** fallback normals are generated only in transient render data
- **AND** the Houdini geometry/scene remains unchanged

### Requirement: Produce flat per-object Object ID images

Object ID SHALL use the shared displayed polygon geometry layer. Every eligible OBJ object in one capture SHALL receive one flat color distinct enough to separate objects in that capture. Lighting, material shading, gradients, and Beauty viewport shading SHALL NOT contribute. Pixels outside eligible geometry SHALL be black.

This change SHALL NOT promise that one object's color remains identical across separate invocations; the contractual use is segmentation within the produced image.

#### Scenario: Capture multiple Object IDs
- **WHEN** an Object ID pass contains multiple eligible OBJ objects
- **THEN** each object is rendered as a flat segment color
- **AND** lighting and material variation do not alter a segment's color

#### Scenario: Unselected object is visible in the source viewer
- **WHEN** model filtering excludes one otherwise visible object
- **THEN** that object contributes no Object ID pixels

### Requirement: Produce signed Curvature analysis images

Curvature SHALL use the shared displayed polygon geometry layer and use world-space positions, point normals, and vertex-neighborhood relationships to compute the validated signed curvature approximation for AI/VLM shape interpretation. It SHALL NOT claim exact differential-geometry curvature measurement.

At effective scale `1.0`, the validated automatic normalization SHALL be used unchanged. A scale above `1.0` SHALL strengthen the mapped response and a scale below `1.0` SHALL weaken it.

With `rg`, convex response SHALL map to red, concave response SHALL map to green, flat response SHALL map to black, and blue SHALL remain zero. With `gray`, flat response SHALL map to black and increasing curvature magnitude SHALL map toward white. Pixels outside eligible geometry SHALL be black.

#### Scenario: Capture signed RG curvature
- **WHEN** Curvature uses colormap `rg`
- **THEN** convex and concave responses are separated into red and green channels
- **AND** flat response is black

#### Scenario: Capture grayscale curvature magnitude
- **WHEN** Curvature uses colormap `gray`
- **THEN** signed direction is not encoded by hue
- **AND** larger curvature magnitude maps toward white

#### Scenario: Strengthen curvature response
- **WHEN** Curvature uses a scale greater than `1.0`
- **THEN** the mapped curvature response is stronger than the same automatically normalized capture at scale `1.0`

### Requirement: Keep analysis capture read-only and non-disruptive

Analysis capture SHALL be read-only with respect to the user's Houdini scene and live viewer. It SHALL NOT create temporary or persistent Houdini scene nodes, temporary cameras, SOPs, or wrangles; SHALL NOT change display/render flags; and SHALL NOT leave changes in the user's Scene Viewer.

Analysis capture SHALL run without opening MPlay or a render window. Native build/helper processes on Windows SHALL run without a visible console window while preserving diagnostics needed for structured failure reporting.

If the required SceneHook cannot be triggered from the existing cloned Scene Viewer/flipbook path without creating scene nodes, implementation SHALL stop at that compatibility gate and the specification SHALL be revised before continuing.

#### Scenario: Analysis capture succeeds
- **WHEN** any non-beauty pass completes
- **THEN** no scene node, flag, or user-viewer mutation remains or was required for the capture
- **AND** no MPlay, render window, or visible helper console is opened

#### Scenario: Node-free SceneHook triggering is unavailable
- **WHEN** the native integration cannot obtain the required callback without creating a Houdini scene node
- **THEN** implementation does not silently create a temporary ROP or other node
- **AND** the incompatibility is resolved through a specification change before later render-pass phases proceed

### Requirement: Publish analysis output through the existing viewport and camera artifact contracts

Each successful analysis capture SHALL publish one completed PNG per requested viewport view or one completed PNG for camera capture through the existing Capture temporary-artifact boundary. It SHALL use the existing viewport/camera screenshot kind, retention, sequence allocation, scale/clamp behavior, and public success schema.

Analysis intermediates, native build files, depth buffers, and EXR files SHALL NOT be exposed as successful public artifacts.

#### Scenario: One viewport analysis image succeeds
- **WHEN** one viewport analysis image is complete
- **THEN** it is published with the existing viewport screenshot kind and returned through the existing single-path JSON schema

#### Scenario: Several directed viewport analysis images succeed
- **WHEN** several directed analysis images are complete
- **THEN** each is published independently through the existing completed-artifact boundary
- **AND** the public result uses the existing ordered `captures` array

#### Scenario: Camera analysis image succeeds
- **WHEN** one camera analysis image is complete
- **THEN** it is published with the existing camera screenshot kind and returned through the existing single-path JSON schema

#### Scenario: Analysis image production fails
- **WHEN** a native/pass failure occurs before a valid PNG is complete
- **THEN** no incomplete analysis PNG or intermediate artifact is advertised as successful
