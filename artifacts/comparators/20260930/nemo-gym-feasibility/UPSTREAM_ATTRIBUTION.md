# Attribution

The probe exercises unmodified code from NVIDIA NeMo Gym, revision [`82e1834ccf2dd578af26a1abc686c15e17569594`](https://github.com/NVIDIA-NeMo/Gym/commit/82e1834ccf2dd578af26a1abc686c15e17569594).

Upstream files bear: Copyright (c) 2025–2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. SPDX-License-Identifier: Apache-2.0. A verbatim copy of the pinned project's license is included as `UPSTREAM_LICENSE.txt`.

The resource component is [`example_session_state_mgmt`](https://github.com/NVIDIA-NeMo/Gym/tree/82e1834ccf2dd578af26a1abc686c15e17569594/resources_servers/example_session_state_mgmt). Its example synthetic task input is reproduced in `local-trajectory-01/materialized-input.json` with explicitly recorded generation settings. The probe calls the shipped sanity test and uses the shipped resource server, simple agent, and vllm_model adapter without editing their source. The small local harness scripts are probe code, not upstream implementation files. No upstream source tree or dependency wheels are included in the promotion manifest.

Dependencies retain their own licenses; `source-and-dependencies.json` records installed distribution license metadata without asserting a complete legal review. Nemotron model weights retain their separate license, are not bundled, and were already present locally. The local model's license-text hash is recorded in `model-manifest.json`.
