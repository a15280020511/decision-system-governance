# Issue and Artifact Retention Policy

Version: 2026-08-05

## Purpose

This policy separates short-lived execution evidence from long-lived governance records. It does not create a hidden database or cross-task memory ledger.

## Governance Issues

Governance Issues are the durable task index and must retain:

- original canonical request;
- governance Task ID and route;
- child Issue URL;
- final trusted status or reconciliation status;
- explicit model/API/compute call counts when present.

Completed, failed, rejected and duplicate governance Issues remain closed rather than deleted. User-authored edits after completion are not authoritative; trusted bot comments remain the evidence source.

## Child Issues

Child Issues close automatically after a trusted terminal:

- success: `completed`;
- failure, blocked, degraded or rejected: `not_planned`.

They are not deleted because governance receipts link to them. Open terminal child Issues are treated as stale locks and reclaimed by the child reclaimer.

## Workflow Artifacts

Current workflow retention values remain route-specific and bounded. Test and health evidence may use shorter retention than production evidence.

Before an Artifact expires, a result requiring long-term institutional verification must be copied to an explicitly approved durable archive. The archive must preserve:

- Artifact ID and original URL;
- Artifact digest;
- workflow run ID;
- repository and commit SHA;
- Task ID;
- acquisition timestamp;
- archive object digest.

No automatic durable archive is enabled by this policy. Storage credentials and destinations require a separate reviewed design.

## Health and retry audits

Health artifacts and GitHub HTTP retry audit JSONL files retain no Token values or response bodies. They may retain repository names, API paths, HTTP status, retry reason, delay and timestamps.

The single `[health] Governance Control Plane` Issue is created only on failure. A later passing health run comments the recovery and closes that Issue. Repeated failures reuse the same Issue.

## Privacy and secrets

Issues and Artifacts must not contain:

- API keys, PATs, passwords or authorization headers;
- private keys or refresh tokens;
- unapproved personal data;
- raw environment dumps;
- workflow debug traces containing secrets.

A leaked secret requires immediate revocation and a scoped evidence review. Deleting the Issue is not a substitute for revocation.

## Operational boundary

GitHub Artifact expiration is platform behavior. The governance system must not claim indefinite evidence retention until an approved durable archive is implemented and tested.
