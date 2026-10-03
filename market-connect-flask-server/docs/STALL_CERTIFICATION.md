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
   one to three proof documents. PDF, JPG, and PNG files are accepted up to 5 MB
   each. A private HTTPS evidence link can be supplied instead of or in addition
   to uploaded files.
3. Configure availability while the application is pending.
4. Wait for an operator to approve or reject the application.

Evidence files, evidence links, and review notes are private. They must not be
copied into public stall descriptions, logs, screenshots, support tickets, or
API responses.

Uploaded documents are validated by extension and file signature, encrypted
with AES-GCM, and stored in PostgreSQL rather than Render's ephemeral web-service
filesystem. The encryption key is derived from `SECRET_KEY`, so do not rotate
that variable while documents exist unless the documents are re-encrypted as
part of the rotation. Database backups and `SECRET_KEY` must be protected
separately.

## Operator Review

### Create an admin account

Admin access is a separate database flag and cannot be selected during public
registration or role activation. The user must sign in normally at least once,
then a trusted operator grants access from `market-connect-flask-server/` using
the username shown on that user's profile:

```bash
python -m flask --app app set-admin USERNAME --enable
```

Open `/admin/certifications/` while signed in as that account. Revoke access
immediately when it is no longer required:

```bash
python -m flask --app app set-admin USERNAME --disable
```

The web admin area lists certification cases, downloads encrypted evidence as
attachments, and records the reviewing admin on approve/reject decisions. A
rejection always requires an actionable note. Non-admin accounts receive HTTP
403 and anonymous visitors are sent to login.

### CLI fallback

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

## Current Limitations

- File signatures are checked, but the MVP does not run an antivirus or content
  disarm scanner. Admins must use a managed device and must not enable macros,
  scripts, or external links in downloaded documents.
- PostgreSQL byte storage is suitable only for the current small MVP limits. At
  higher volume, move ciphertext to private object storage with a KMS-managed
  key while keeping metadata and audit state in PostgreSQL.
- A formal retention/deletion schedule and privacy incident process are still
  required before production-scale collection of identity or property records.
- Document downloads are forced as attachments with no-store headers, but staff
  remain responsible for protecting any local copies they create.
