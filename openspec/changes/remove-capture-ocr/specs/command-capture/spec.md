## REMOVED Requirements

### Requirement: Expose screenshot OCR

**Reason**: OCR is being removed from the Houbridge public command surface so Capture remains focused on Houdini image/video production.

**Migration**: Replace `houbridge capture ocr IMAGE` with a direct `image-ocr IMAGE` invocation. When the image originates from Houdini, first create it with the appropriate Houbridge capture command and then pass that file to `image-ocr`.
