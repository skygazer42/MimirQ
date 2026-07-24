# SAML SSO

MimirQ now supports a production-oriented SAML 2.0 ACS flow that terminates in the same app JWT/session model used by password login.

## Current Flow

1. The IdP POSTs a `SAMLResponse` to `POST /api/saml/acs`.
2. The Next.js ACS route acts as the browser-facing bridge and forwards the raw assertion to `POST /api/v1/auth/saml/exchange`.
3. The backend validates the assertion and issues a normal MimirQ `AuthResponse`.
4. The frontend redirects to `/auth/saml/callback`, which stores the session via `setAuthSession(...)` and returns the user to the requested path.

This keeps browser-facing SAML ingress on the web origin while preserving the backend as the only component that maps identities and signs MimirQ JWTs.

## Security Checks

The backend exchange rejects the response unless all of the following pass:

- XML signature verification against the configured IdP X.509 certificate
- Issuer match
- Audience match
- Response destination match
- Subject confirmation recipient match
- `NotBefore` / `NotOnOrAfter` window validation with bounded clock skew
- Replay protection on assertion ID / response ID
- Existing local MimirQ account resolution from `email` or `NameID`

## Configuration

`SAML_ENABLED=true` turns on the Next.js ACS/metadata routes.

Backend configuration is driven by `SAML_PROVIDERS_JSON`:

```json
[
  {
    "id": "default",
    "issuer": "https://idp.example.com",
    "audience": "https://app.example.com/api/saml/metadata",
    "acs_url": "https://app.example.com/api/saml/acs",
    "idp_cert_pem": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----",
    "email_attribute": "email",
    "groups_attribute": "groups"
  }
]
```

Supporting controls:

- `SAML_ALLOWED_CLOCK_SKEW_SEC` default `60`
- `SAML_REPLAY_TTL_SEC` default `300`
- `SAML_REPLAY_REDIS_ENABLED` default `false`; required in production when providers are configured

SP metadata controls (optional, enterprise IdP compatibility):

- `SAML_SP_CERT_PEM`: X.509 certificate advertised in SP metadata `<KeyDescriptor use="signing">`
- `SAML_SP_PRIVATE_KEY_PEM`: private key used to sign SP metadata (required when signing is enabled)
- `SAML_SP_METADATA_SIGNED=true`: sign the generated metadata (safe default: `false`)

When `SAML_REPLAY_REDIS_ENABLED=true`, replay protection uses Redis via `REDIS_URL` and rejects exchanges with `503` if Redis is unavailable. Production deployments with `SAML_PROVIDERS_JSON` configured require both settings, including Kubernetes deployments where multiple pods cannot be inferred from `UVICORN_WORKERS`. The in-process TTL cache is retained only for non-production, single-process development.

## Identity Mapping

The backend does not create local users from SAML in this slice.

- First choice: resolve the configured email attribute, typically `email`
- Fallback: resolve `NameID`
- Email-like identifiers map through `UserService.get_by_email(...)`
- Non-email identifiers fall back to `UserService.get_by_username(...)`

If no active local user matches, the exchange fails with `403`.

## Tenant and Group Claims

When the matched user has a current tenant, the issued app JWT includes that tenant claim through the normal `create_access_token(...)` path.

If the SAML assertion includes the configured groups attribute, the backend also embeds those groups into the app JWT. That allows the existing JWT-based group sync hooks to keep working on subsequent authenticated requests.

## What This Slice Does Not Do

- SP-initiated SAML login UI
- Multi-step enterprise admin configuration screens
- Automatic local user creation
- Signed AuthnRequests (AuthnRequest signing)
- Full external identity linking tables

Those can be layered on later without changing the core “backend validates assertion and signs app JWT” model.
