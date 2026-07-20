# Test Credentials — OpportunityOS (Phase 1)

> Read by testing agents and fork runs. Keep in sync with `domains/seeds/seeder.py`.

**Preview base URL:** `https://af7cc636-8506-4548-af82-a1a50aae0158.preview.emergentagent.com`

---

## User Zero (real seed candidate — NOT a sample)
- **Email:** `ujjwal@opportunityos.dev`
- **Password:** `Passport!Test0`
- **Role:** `user`
- **Persona:** Ujjwal Singla — Phoenix, AZ — automotive systems engineer
- **Passport state:** all claims `user_approved=false`, `verification_level=0`, work-authorization claim is `sealed`.

## Admin
- **Email:** `admin@opportunityos.dev`
- **Password:** `Admin!Console1`
- **Role:** `admin`

## Support
- **Email:** `support@opportunityos.dev`
- **Password:** `Support!Console1`
- **Role:** `support`

---

## Curl smoke test
```bash
BASE="https://af7cc636-8506-4548-af82-a1a50aae0158.preview.emergentagent.com"
curl -s -X POST "$BASE/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"email":"ujjwal@opportunityos.dev","password":"Passport!Test0"}'
```
