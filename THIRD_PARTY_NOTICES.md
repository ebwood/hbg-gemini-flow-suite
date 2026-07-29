# Third-party notices

Gemini Flow Suite combines original integration code with upstream open-source projects and one build-time binary dependency.

## Gemini-API

- Project: <https://github.com/HanaokaYuzu/Gemini-API>
- License: GNU Affero General Public License v3.0
- Location: `vendor/Gemini-API/`
- Role: reverse-engineered Gemini Web client, media response parsing and downloads

The vendored source retains its upstream `LICENSE`. Because this repository directly includes and integrates that AGPL-3.0 code, Gemini Flow Suite is distributed under AGPL-3.0.

## gflow-cli

- Project: <https://github.com/ffroliva/gflow-cli>
- License: MIT
- Pinned version: `0.43.0`
- Role: Flow browser automation and image/video commands

The package is installed during the Docker build. Its installed distribution includes the MIT license text.

## remove-ai-watermarks

- Project: <https://github.com/wiltodelta/remove-ai-watermarks>
- License: Apache License 2.0
- Pinned version: `0.19.0`
- Role: optional visible-image-mark detection/inpainting and metadata processing

The package is installed during the Docker build.

## VeoWatermarkRemover

- Project: <https://github.com/allenk/VeoWatermarkRemover>
- Pinned release: `v0.6.4-demo`
- Pinned artifact: `GeminiWatermarkTool-Linux-x64-Video.zip`
- Role: optional visible video mark processing

The Dockerfile downloads the release artifact and verifies its SHA-256 checksum. As of 2026-07-29, the upstream GitHub repository does not advertise an SPDX license. The binary is not stored in this Git repository. Review upstream terms before publishing or redistributing a built container image.

## Platform names

Google, Gemini, Flow and Veo are trademarks of their respective owners. Their names are used only to describe compatibility. This project is unofficial and is not affiliated with, sponsored by or endorsed by Google.
