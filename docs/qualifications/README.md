# Qualifications

This directory contains qualification reports and architectural verifications for external components used in Agent-Ops.

## Component Qualifications

### LoopX State Kernel
- **Version:** `v0.4.2`
- **Commit:** `c94e188fa484fbf79a5e6190942162810861ad29`
- **Authorization Reference:** AGE-2
- **Review Verdict:** PASS
- **Report:** [loopx-v0.4.2-qualification-report.md](./loopx-v0.4.2-qualification-report.md)
- **Notes:** LoopX qualified as a purely passive read-only state kernel. The outer runner requirement for `one-action-per-wake` is explicitly delegated and is currently NOT YET IMPLEMENTED in Agent-Ops.
