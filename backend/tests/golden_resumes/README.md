# Golden-set résumé harness

This directory holds **10 synthetic labeled résumés** and a runner (`golden_run.py`) that
answers Founder Directive #8's parse-quality question:

> Target ≥95% field accuracy. If below, report honestly — do NOT tune the checker to pass.

## Contract

Each fixture is a pair:

| file | purpose |
|---|---|
| `resume_NN.docx` | the input we send to the LLM (real DOCX built by the fixture builder) |
| `resume_NN.expected.json` | the labeled ground truth |

`expected.json` schema:

```json
{
  "name": "Aditi Rao",
  "emails": ["aditi.rao.testuser@example.com"],
  "phones": ["+1-555-0100"],
  "locations": [{"city": "Boston", "state": "MA"}],
  "links": [{"kind": "linkedin", "url": "linkedin.com/in/aditi-rao-testuser"}],
  "education": [
    {"institution": "MIT", "degree": "MS"},
    {"institution": "IIT Bombay", "degree": "BTech"}
  ],
  "employment": [
    {"company": "Rivian", "role": "Battery Systems Engineer"},
    {"company": "Zoox", "role": "Battery Test Intern"}
  ],
  "skills": ["MATLAB", "Simulink", "Python"],
  "certifications": []
}
```

The runner scores **field accuracy** = correctly-matched fields / total labeled fields, aggregated
across the 10 fixtures. A field matches when the LLM emits at least one claim of the corresponding
`type` whose value contains the labeled substring (case-insensitive). This is deliberately
generous: parsers vary in normalization; we're grading *did you find this fact*, not *did you
format it my way*.

## Running

```
cd /app/backend
python3 -m tests.golden_resumes.golden_run           # prints report
python3 -m tests.golden_resumes.golden_run --json    # machine-readable
```

The runner writes the report to `/app/backend/tests/golden_resumes/last_report.json` for
downstream inspection.

## Non-goals

- We do NOT try to score dates or metric values yet (LLMs will normalize these differently).
- We do NOT allow the checker to be tuned to make the score look better. If the accuracy drops
  below 95%, the fix is in the extractor / prompt, not the checker.
