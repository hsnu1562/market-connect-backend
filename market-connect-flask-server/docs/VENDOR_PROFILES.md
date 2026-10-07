# Vendor Profiles And Booking Requirements

## Identity Layers

SPACIS keeps three concerns separate:

- `AuthIdentity` proves which Google account authenticated. Google `sub`, not
  email or display name, is the stable identity key.
- `User` is the account, session owner, role holder, and reputation owner.
- `VendorProfile` is the Vendor / 攤商 brand shown in the marketplace.

The MVP relationship is `User 1 -> 0..1 VendorProfile`. A database uniqueness
constraint on `vendor_profile.user_id` enforces one brand per account. A future
multi-brand design can replace that constraint without moving brand fields out
of `User`, because the profile is already a separate table.

Provider / 供應方 organization profiles, staff memberships, invitations, and
team permissions are not part of this phase. Provider-owned stalls continue to
reference `user.id`.

## Progressive Onboarding

Google login creates or resolves the account and immediately returns to the
requested page. The user can browse listings, search, and open role dashboards
without completing personal or brand forms.

The first booking attempt checks `user.vendor_profile`. If absent, the browser
is redirected to `/vendor/profile/` with a validated local `next` URL. Saving
the minimum brand profile returns to the booking page. The service and JSON API
repeat the profile check so bypassing the browser page cannot create a booking.

The personal sheet at `/account/profile/` is optional. Birthday is not shown or
validated. The nullable historical `user.birth_date` column remains so existing
values are preserved and deployments avoid a destructive migration.

## Vendor Fields

Public fields:

- brand name and primary category;
- brand description;
- validated JPG, PNG, or WebP profile image up to 4 MB;
- Instagram, Facebook, and website URLs.

Private fields:

- contact name, phone, and optional email;
- food registration number.

The food registration input is shown only for the `food` category. The service
performs safe length and single-line validation but does not claim regulatory
verification. Switching to another category clears the value.

Product/stall image galleries are deferred. This phase reuses the existing safe
stall-image validator for one profile/logo image instead of introducing a new
media subsystem.

## Booking Requirement Snapshot

`BookingRequirements` stores electricity, gas, equipment, and vehicle-plate
needs for one QR-code booking group. Every slot-level `Booking` row in that
group points to the same snapshot. Editing the Vendor profile later does not
change historical operational requirements.

Existing bookings are preserved with `requirements_id = NULL`. The UI labels
those records as historical bookings without recorded requirements.

## Authorization Boundary

Public Vendor HTML and `GET /api/v1/vendors/<profile_id>` explicitly expose
only public brand fields. They never include private contact details, food
registration data, vehicle plates, or booking requirements.

Private booking details are returned only after server-side authorization for:

- the Vendor account that owns every booking row in the QR-code group;
- the Provider account that owns every booked stall in the group;
- an account with the separately granted admin flag.

The Provider history query is constrained to stalls owned by the signed-in
Provider before rendering private Vendor details.

## Legacy Internal Names

The database, decorators, route paths, session behavior, and many Python
variable names intentionally retain `Tenant` and `Landlord`. These are stable
internal compatibility identifiers. User-facing pages use Vendor / 攤商 and
Provider / 供應方. Renaming internal roles requires a separate, coordinated API
and data migration and is not justified by this presentation-only change.
