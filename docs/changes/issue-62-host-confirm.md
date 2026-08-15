# Issue #62 — Interactive Local host confirmation

`interactive_local` remains a same-user/same-uid trust boundary. The task-scope file and its integrity/provenance markers are not uid-separated positive authority and do not grant lifecycle permission.

`governloop setup-task-scope` keeps the existing terminal `YES` flow. Coding-agent hosts may additionally use `--host-confirm` after the user explicitly approves the exact task scope in the host interaction. The public CLI reuses the canonical task-scope validation/write/verify path and records `confirmation_transport=host_explicit_confirm_v1` as provenance.

The host-confirm path does not authorize Ready, Merge, Release, Deploy, or any other lifecycle transition. Those remain separate explicit Product Owner decisions under the existing lifecycle authority path.
