# Test Credentials — OpportunityOS (Phase 1)

> Read by testing agents and fork runs. Keep in sync with `domains/seeds/seeder.py`.

**Preview base URL:** `https://lynk-preview-2.preview.emergentagent.com`

---

## User Zero (real seed candidate — NOT a sample)
- **Email:** `ujjwal@opportunityos.dev`
- **Password:** `Passport!Test0`
- **Role:** `user`
- **Persona:** Ujjwal Singla — Phoenix, AZ — automotive systems engineer
- **Passport state:** all 16 seeded claims start `status:"pending"`, `user_approved:false`, `verification_level:0`. Work-authorization claim is `sealed` (owner sees real value; admin/support see the masked `•••• (sealed)` placeholder).

_Note for testers:_ Phase 2 does NOT auto-approve any of User Zero's seeded claims. You must approve at least one `identity` claim AND one `education` or `employment` claim before `/api/v1/passport/activate` will succeed. User Zero has both types available in the pending pile.

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
BASE="https://lynk-preview-2.preview.emergentagent.com"
curl -s -X POST "$BASE/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"email":"ujjwal@opportunityos.dev","password":"Passport!Test0"}'
```
