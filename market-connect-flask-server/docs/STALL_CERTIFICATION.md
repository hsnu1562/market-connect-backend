# Stall Certification Operations

## Security Boundary

Creating an account or submitting a form does not certify a provider. Every
stall starts as non-public and remains unavailable for booking until a trusted
operator manually approves its certification.

The application enforces this status in all public discovery pages, public API
responses, direct booking pages, and booking creation. Existing bookings remain
available for payment and history if a certification is later rejected.

After migration, pre-existing stalls intentionally have no certification and
therefore disappear from public discovery. Their owners must submit evidence
from the provider management page; do not bulk-approve legacy records without
reviewing them.

## Provider Flow

1. Create the stall and address record.
2. Submit legal/contact information, relationship to the space, proof type, and
   an HTTPS evidence link.
3. Configure availability while the application is pending.
4. Wait for an operator to approve or reject the application.

Evidence links and review notes are private. They must not be copied into public
stall descriptions, logs, screenshots, support tickets, or API responses.

## Operator Review

Run commands from `market-connect-flask-server/` with the intended
`DATABASE_URL` loaded. On Render, use a trusted Shell session.

List pending applications without exposing complete evidence URLs:

```bash
python -m flask --app app list-stall-certifications
```

Inspect one application privately:

```bash
python -m flask --app app show-stall-certification STALL_ID
```

Approve only after independently confirming the applicant and their authority
to rent the exact listed space:

```bash
python -m flask --app app review-stall-certification STALL_ID \
  --decision approve \
  --reviewer "OPERATOR_REFERENCE" \
  --note "Authority and location confirmed"
```

Reject unclear or invalid evidence with an actionable note:

```bash
python -m flask --app app review-stall-certification STALL_ID \
  --decision reject \
  --reviewer "OPERATOR_REFERENCE" \
  --note "Please provide a signed authorization from the venue owner"
```

## Review Checklist

- Applicant identity or organization matches the submitted evidence.
- Address and stall description match the evidence.
- The applicant owns the space or has explicit authority to sublet/manage it.
- Authorization covers the proposed rental dates and commercial use.
- Contact details can be independently confirmed.
- Documents show no obvious alteration or conflicting names/addresses.

Approval reduces risk but is not a permanent guarantee. Revoke approval with a
rejection decision if rights expire, ownership changes, or fraud is reported.

## Current Limitation

The MVP stores a private evidence link rather than uploading identity/property
documents to the application. Before accepting direct uploads, add encrypted
object storage, malware scanning, strict staff access controls, retention and
deletion rules, and a documented privacy incident process.
