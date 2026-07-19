# Interstitium

An owner for the post-discharge results that fall through the cracks.

A patient is discharged from the ED on an empiric antibiotic with a urine culture
still pending. Two days later the culture returns: the organism is resistant to
the drug she went home with. She has no PCP. The result lands in a queue nobody
owns, and she finishes a course of an antibiotic that was never going to work.

That is one loop. The same thing happens to an amended radiology report, a
high-risk patient who leaves against advice, a symptom that never resolved, and —
worst of all — a specimen that never reached the laboratory, which produces no
result for anyone to miss.

This repo is the runtime for an agent that owns those loops: that screens **every**
discharge for them, that cannot drop one it does not recognise, and that knows
when **not** to act.

**Live demo: https://annhuii.github.io/interstitium-demo/**

```
pip install -e ".[dev]"
python -m interstitium --registry   # route signals across every workflow
python -m interstitium              # the urine-culture loop in detail
pytest                              # 105 tests
```

## This is not a set of condition-specific bots

The unit of work is not a diagnosis. It is **an unresolved item at discharge** —
and every discharged patient is screened for those, not just the ones matching a
condition someone thought to write a workflow for.

Three things make that a property of the code rather than a claim in a readme:

1. **Intake runs on every discharge.** `discharge_open_loop_screen` asks one
   condition-agnostic question: does this encounter leave anything unresolved
   that nobody owns? Pending results, empiric therapy started, no downstream
   owner, left AMA. An ankle sprain with nothing pending is *closed* — which is
   itself a decision, gated on facts, not a silent skip.

2. **No signal is ever unowned.** `route` sends anything the specialists do not
   claim to `UnclassifiedLoopWorkflow`, which has no clinical opinion and cannot
   act — it can only attach a human owner. A pathology addendum, a device alert,
   a service integrated last week: none of them vanish. The unmodelled case
   degrades to a person rather than to silence. `test_no_signal_is_ever_unowned`
   is the assertion.

3. **Absence of a signal is itself a signal.** See below.

The specialised workflows are how a loop gets *closed* well. The runtime is what
guarantees every loop is *seen*.

| trigger | workflow | what makes it different |
|---|---|---|
| discharge event | `discharge_open_loop_screen` | screens **every** discharge — decides whether any loop exists at all |
| discharge event | `high_risk_ama` | clock runs in **hours**; escalation target may be EMS, not a chat message |
| result event | `pending_culture_empiric_therapy` | the reference case, fully worked out |
| result event | `radiology_report_changed` | triggered by a **diff** between reads, not a value; closed clinician-to-clinician |
| **non**-event | `result_never_returned` | fires when an expected result *fails* to arrive |
| elapsed time | `post_discharge_symptom_check` | no external event at all — "is the trajectory what we expected" |
| anything else | `unclassified_open_loop` | owner of last resort; escalates, never acts |

## The result that never came back

Every other workflow is triggered by something happening. This one is triggered
by something **not** happening — the expected turnaround elapsed and no result
ever arrived.

That inverts the failure mode. A resistant culture at least produces a result
somebody could in principle read. A specimen that never reached the lab produces
nothing: no queue holds it, no inbox displays it, and there is nothing for a
human to miss noticing. It is invisible rather than merely unnoticed.

"No result" has several causes with opposite correct responses, and they are not
distinguishable without asking the laboratory:

| what the lab says | what it actually means | response |
|---|---|---|
| never received / lost in transit | no result is ever coming | recollect — patient must return |
| rejected (haemolysed, insufficient) | someone was told, nobody acted | recollect + notify ordering clinician |
| **resulted, but not delivered** | the answer exists in the LIS and never reached the chart | attach it, raise the interface fault |
| still in progress | genuinely not ready | monitor, keep the loop open |
| anything unrecognised | unknown is not benign | escalate |

The third row is the one worth pointing at. The laboratory believes it did its
job, the ordering system shows nothing pending, and the result is sitting in a
system nobody is looking at. Treating "no result in the chart" as "no result
produced" is how that gets buried permanently.

Note also that this workflow's facts come from the **laboratory**, not the
patient (`fact_source = FactSource.LABORATORY`), so an unreachable patient does
not block the diagnosis. Getting that wrong would have the runtime refuse to
query a lab for want of a phone number it never needed.

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
(`policy.py`, `formulary.py`). The others are thin — enough to prove the
interface holds under genuinely different trigger shapes, not enough to run on a
patient. That is deliberate: several half-built workflows would prove less than
one real one plus an architecture that demonstrably takes the rest.

What is *not* thin is the guarantee that no loop goes unowned. That holds
regardless of how many workflows exist, which is what makes this applicable to a
whole department rather than to the conditions someone got round to modelling.

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

## Six bugs the tests caught

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

5. **A signal nobody modelled was silently dropped.** `route` returned an empty
   list for an unrecognised signal type, so it disappeared with no owner and no
   trace -- the exact failure mode the product exists to prevent, reproduced
   inside the product. Now every signal routes to a fallback that escalates.

6. **Unknown treated as a value, three times over.** Two unretrieved radiology
   reads compared equal and proposed closing the loop; an unasked AMA patient was
   described to a clinician as having "declined to return"; an unanswered symptom
   check reported "symptoms persist". The runtime blocked the unsafe *actions*,
   but the workflows should not have proposed them or described them that way.

## Layout

```
src/interstitium/
  runtime.py     Workflow protocol, the guards, routing -- the general layer
  workflows/     intake, ama, culture, lab_integrity, radiology, symptoms, fallback
  models.py      encounter objects; SymptomScreen defaults to worst case
  formulary.py   agent site-eligibility, local antibiogram, pharmacy stock
  policy.py      UTI clinical gates: switch therapy, or escalate
  phi.py         escalation message builder + identifier scan
  engine.py      the culture loop's narrated trace (what the demo UI renders)
  scenarios.py   the demo encounter, as data
tests/           105 tests; registry-wide invariants in test_registry_invariants.py
docs/index.html  the pitch UI (served at the Pages link above)
```

## Regulatory posture

Most of this is solvable with known patterns. Naming them matters more than
having solved them, because the failure mode for a project like this is not
"the regulation is impossible" — it is "nobody thought about it until after the
architecture was fixed."

**Is this a medical device?** Autonomous antibiotic-switching invites FDA
Clinical Decision Support scrutiny, and the design answers it structurally
rather than rhetorically. The agent operates under a named physician's standing
authorization — captured at discharge, when they assign follow-up ownership. It
escalates anything systemic to a human. Every action is logged with a timestamp
and a reason. The intended position is a workflow tool executing a physician's
plan, not an autonomous diagnostician.

The honest qualifier: standing authorization does not by itself keep software
outside device regulation. The Cures Act CDS exemption generally contemplates a
clinician who can independently review the basis for a recommendation *before*
it takes effect — software that acts without that review sits outside it. The
defensible configuration is therefore **agent recommends, physician approves**
for any therapy change, with full autonomy reserved for the surrounding work:
contacting patients, chasing results, diagnosing why a result never arrived,
and preparing the decision. This is why `[Both]` is the safe default at
discharge and `[Agent]` is the demo setting. The escalation branch is not a
safety feature bolted on — it is the part that defines the regulatory envelope.

**HIPAA across settings** — ED, pharmacy, patient's phone, Teams. Each hop is a
known quantity: BAAs with every vendor, PHI encrypted in transit and at rest,
and above all the **minimum-necessary** principle. The physician page
demonstrates that principle literally rather than claiming it: no name, no MRN,
no DOB, no phone number in the message, with real PHI reachable only behind the
authenticated EHR link. `phi.compose` refuses to emit a message that fails its
own scan, so minimum-necessary is enforced at send time by code, not by policy
documentation. That is a deliberate design choice and worth saying out loud.

**Outbound patient contact (TCPA).** Automated calls and texts need the
patient's prior express consent, and the triage step is where it is captured —
the same step that verifies reachability. Two qualifiers worth being straight
about: verifying that a number receives a message is not the same act as
obtaining consent to be contacted by an automated system, so the consent has to
be captured explicitly rather than inferred from delivery; and while
treatment-related healthcare messages have narrower TCPA exposure than
marketing, "narrower" is not "none."

**Prescribing authority.** The therapy change rides on the treating physician's
authority and licence, not the agent's. The closest existing analogue is a nurse
executing a callback protocol under standing orders — though that is an analogy
about *shape*, not a legal equivalence, since standing-order authority is
state-specific and attaches to a licensed human. The load-bearing requirement is
that a licensed prescriber remains the issuer of record for every prescription,
with the agent preparing and transmitting rather than authorising.

**Where this argument is weakest**, said plainly so it does not have to be
discovered in Q&A: the moment the agent transmits a prescription without a
human reviewing that specific decision is the most exposed point in the whole
design. Everything else here — owning results, chasing labs, screening, paging
a physician, closing loops — is materially easier to defend.

## Scope

Synthetic patient, no real PHI, not a medical device. Susceptibility data,
antibiogram, and pharmacy stock are hard-coded rather than pulled from a lab
feed; there is no EHR integration, no telephony, and no persistence. The parts
that are real are the decision gates, the PHI scan, and the tests over both.

MIT licensed.
