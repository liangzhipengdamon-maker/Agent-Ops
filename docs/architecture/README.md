# Architecture Documentation

This directory contains design documents and architecture specifications for the Agent-Ops unattached control plane.

## Index

### AGE-3: Authority Mapping & Trusted Authorization Provider
- **Linear Issue:** AGE-3
- **Document Version:** Revision 4
- **Review Verdict:** PASS
- **Core Topics:**
  - Product Owner as sole authorization source
  - Trusted Authorization Provider
  - Mission Authorization Envelope
  - Step Authorization
  - Exact-SHA Derived Action Authorization
  - ACTIVE → EXECUTING → CONSUMED/FAILED recovery model
  - Mandatory risk-limit bindings
  - One-action-per-wake
  - Revocation and audit contracts
- **Open Owner Decisions:**
  - Outer Runner implementation
  - PO identity mechanism
  - Remote audit log provider
- **Explicit Constraints:**
  - **PASS does not authorize implementation or AGE-4 execution.**
- **Document Link:** [AGE-3 Authority and Mission Authorization Design](./age-3-authority-and-mission-authorization-design.md)
