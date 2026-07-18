# Interstitium

An owner for the post-discharge results that fall through the cracks.

A patient is discharged from the ED on an empiric antibiotic with a urine culture
still pending. Two days later the culture returns: the organism is resistant to
the drug she went home with. She has no PCP. The result lands in a queue nobody
owns, and she finishes a course of an antibiotic that was never going to work.

This repo is the decision engine for an agent that owns that loop — and, more
importantly, that knows when **not** to act on it.

```
pip install -e ".[dev]"
python -m interstitium --registry   # route signals across all five workflows
python -m interstitium              # the urine-culture loop in detail
pytest                              # 79 tests
```

## Five workflows, one runtime

A post-discharge loop is not one shape. These are three:

| trigger | workflow | what makes it different |
|---|---|---|
| discharge event | `discharge_open_loop_screen` | screens *every* discharge — decides whether any loop exists at all |
| discharge event | `high_risk_ama` | clock runs in **hours**; escalation target may be EMS, not a chat message |
| result event | `pending_culture_empiric_therapy` | the reference case, fully worked out |
| result event | `radiology_report_changed` | triggered by a **diff** between reads, not a value; closed clinician-to-clinician |
| elapsed time | `post_discharge_symptom_check` | no external event at all — just "is the trajectory what we expected" |

A workflow declares three things: when it fires, what it must know before it may
act, and how it decides. Everything else is enforced by `runtime.py` for all of
them — which is the entire point. **Adding a sixth workflow means adding it to
`REGISTRY`, and it inherits the safety properties rather than reimplementing
them.**

```python
class Workflow(ABC):
    def triggered_by(self, encounter, signal) -> bool
    def required_facts(self) -> Tuple[str, ...]      # gate on these
    def decide(self, ctx) -> Decision
    def escalation_summary(self, ctx) -> str         # goes through the PHI scan
```

The guards can only ever move a decision *away* from autonomous action. No guard
upgrades one, so no combination of them can invent permission the workflow did
not propose:

- an autonomous action is impossible while any required fact is unknown
- a workflow needing the patient cannot act without a **verified** contact point
- a workflow that cannot establish its facts inside its window **hands off**
  rather than waiting

That last one is a liveness property, and it is the one worth pointing at:
`MONITOR` and `GATHER_FACTS` are always safe to return, so a loop could sit in
either forever and never surface. The gather window is what stops "safe" from
becoming "silent".

```
$ python -m interstitium --registry

--- AMI patient left AMA -> two owners, immediate
    high_risk_ama       gather_facts         urgent outbound call: symptoms + willingness to return

--- AMI AMA, unreachable for 3h -> hands off rather than waiting
    high_risk_ama       escalate_clinician   handing off: gather window elapsed
```

The tests in `test_registry_invariants.py` are parametrised over `REGISTRY`, so
those properties are asserted for every workflow — including ones not written
yet. One of them drops each required fact in turn and asserts that
complete-minus-one is never treated as complete.

**Honest scope:** only the urine-culture workflow has real clinical depth
(`policy.py`, `formulary.py`). The other four are thin — enough to prove the
interface holds under genuinely different shapes, not enough to run. That is
deliberate: five half-built workflows would prove less than two real ones and an
architecture that takes the rest.

## The workflow this changes

| | today | with an owner |
|---|---|---|
| Culture returns resistant | lands in an unowned queue | triggers a watch on the encounter |
| Patient contact | address on file, often stale | verified reachable **before** discharge |
| Symptom check | none until she re-presents | safety screen before any therapy change |
| Therapy switch | on her next ED visit, or never | same day, by susceptibility |
| Systemic features | discovered at readmission | escalated to the treating physician |

## Design: escalation is the default

Every gate in `policy.decide` can only **remove** the option to prescribe. There
is no path where missing information produces a prescription.

```python
SymptomScreen()                 # nothing asked yet
  .fever_or_chills  -> True     # defaults are the worst case, not the benign one
  .has_red_flags    -> True
  .suspected_site   -> Site.UNKNOWN  # treated as upper tract
```

An unanswered screen escalates. An unconfirmed allergy list escalates. An agent
absent from the susceptibility panel is *not* assumed susceptible. No available
oral agent escalates rather than falling back to something close enough.

The clinically load-bearing rule is site eligibility, encoded as data in
`formulary.py`: nitrofurantoin and fosfomycin concentrate in urine and do not
reach therapeutic tissue levels in the kidney. They treat cystitis and would
undertreat pyelonephritis. So the moment the screen reports fever or flank pain,
the suspected site becomes upper tract, the oral candidate list becomes empty,
and the agent cannot prescribe even though the culture says `S`.

```
$ python -m interstitium --case red_flag
REASONING   red flags present (fever or chills, flank or back pain); suspected
            upper-tract or systemic involvement
REASONING   oral urinary-concentrating agents would undertreat; physician
            assessment required
ESCALATION  Halting autonomous prescribing. Paging Dr. Lim.
```

## The page carries no identifiers

The escalation goes over a general-purpose chat channel, so it must survive being
screenshotted, forwarded, or read on a lock screen. `phi.compose` builds the
message and **refuses to return one that fails its own scan** — a leak raises
`PHILeakError` rather than logging a warning someone reads later.

> Follow-up on your ED patient from Sat 2pm — the music teacher, jazz trio,
> first-time UTI, sent home on cipro. Culture is *E. coli*, ESBL,
> ciprofloxacin-resistant, and she's now reporting fever + flank pain. Possible
> pyelonephritis. Please review in EHR: [link]

No name, no MRN, no DOB, no phone number. The memorable social detail is
deliberate: it is how a clinician who saw thirty patients that shift actually
re-recognises this one, and it identifies her to *him* without identifying her to
anyone else. The actual PHI lives behind the authenticated link.

## Five bugs the tests caught

Worth recording, because each one is the kind that survives a demo:

1. **The scanner blocked a clean message.** Substring matching meant the surname
   "Tan" matched inside "resis**tan**t", so every correct page was rejected as a
   PHI leak. Now word-boundary matched, with identifier *numbers* still matched
   inside digit runs so `mrn4471029` cannot smuggle one past.

2. **A 1% antibiogram edge overrode guideline first-line.** Sorting candidates by
   local susceptibility picked fosfomycin (97%) over nitrofurantoin (96%) — noise
   silently outranking guidance built on tolerability and collateral resistance.
   Now ranked by `FIRST_LINE_ORDER`, with the antibiogram as tiebreak only.

3. **An unreachable patient was paged as symptomatic.** The screen defaults every
   red flag to `True` so silence never reads as "no fever" — correct internally,
   but the escalation repeated those defaults outward as *"she's now reporting
   fever + flank pain"* when nobody had reached her. Absence of information is
   now stated as absence of information.

4. **A loop could monitor forever.** `MONITOR` is always permitted, so the
   symptom workflow could return it indefinitely: never acting, never escalating,
   never surfacing. Safe on every individual call and a silent failure over time.
   The gather-window check now runs *before* the always-permitted shortcut.

5. **Unknown treated as a value, three times over.** Two unretrieved radiology
   reads compared equal and proposed closing the loop; an unasked AMA patient was
   described to a clinician as having "declined to return"; an unanswered symptom
   check reported "symptoms persist". The runtime blocked the unsafe *actions*,
   but the workflows should not have proposed them or described them that way.

## Layout

```
src/interstitium/
  runtime.py     Workflow protocol, the guards, routing -- the general layer
  workflows/     the five: intake, ama, culture, radiology, symptoms
  models.py      encounter objects; SymptomScreen defaults to worst case
  formulary.py   agent site-eligibility, local antibiogram, pharmacy stock
  policy.py      UTI clinical gates: switch therapy, or escalate
  phi.py         escalation message builder + identifier scan
  engine.py      the culture loop's narrated trace (what the demo UI renders)
  scenarios.py   the demo encounter, as data
tests/           79 tests; registry-wide invariants in test_registry_invariants.py
demo/index.html  the pitch UI
```

## Scope

Synthetic patient, no real PHI, not a medical device. Susceptibility data,
antibiogram, and pharmacy stock are hard-coded rather than pulled from a lab
feed; there is no EHR integration, no telephony, and no persistence. The parts
that are real are the decision gates, the PHI scan, and the tests over both.

MIT licensed.
