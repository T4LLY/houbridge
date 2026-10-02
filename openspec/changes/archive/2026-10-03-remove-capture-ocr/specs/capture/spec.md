## REMOVED Requirements

### Requirement: Extract OCR text and compact bounding boxes

**Reason**: General-purpose image OCR is outside Houbridge's Houdini capture responsibility and is owned by the standalone `image-ocr` tool.

**Migration**: Capture the required Houdini image with Houbridge, then invoke `image-ocr IMAGE` separately and use `jq` for any text, bounding-box, or confidence filtering.

### Requirement: Keep OCR runtime quiet and cache models predictably

**Reason**: Houbridge no longer owns or initializes an OCR runtime after the OCR feature is removed.

**Migration**: OCR runtime output and model-cache behavior are the responsibility of the standalone `image-ocr` tool.

### Requirement: Use the defined OCR engine profile

**Reason**: OCR engine selection is no longer part of Houbridge after embedded OCR is removed.

**Migration**: Use the OCR engine profile defined by the standalone `image-ocr` project.

### Requirement: Route oversized OCR results through the common Output Policy

**Reason**: Houbridge no longer produces OCR results, so there is no OCR payload to route through Houbridge Output Policy.

**Migration**: Process `image-ocr` JSON directly with command-line tools such as `jq`; Houbridge Output Policy does not apply to external OCR output.
