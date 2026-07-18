"""Run a scenario and print the resulting event trace.

    python -m interstitium              # all three
    python -m interstitium --case red_flag
"""

import argparse

from . import engine, scenarios

CASES = {
    "clear": ("screen negative -- agent switches therapy", scenarios.SCREEN_CLEAR),
    "red_flag": ("fever + flank pain -- agent escalates", scenarios.SCREEN_RED_FLAG),
    "unanswered": ("patient unreachable -- agent escalates", scenarios.SCREEN_UNANSWERED),
}


def run_case(name: str) -> engine.LoopResult:
    label, screen = CASES[name]
    result = engine.run(
        patient=scenarios.PATIENT,
        culture=scenarios.CULTURE,
        screen=screen,
        current_agent=scenarios.EMPIRIC_AGENT,
    )

    print("\n=== {} : {} ===".format(name, label))
    print(result.render())
    d = result.decision
    if d:
        print("--> disposition: {}{}".format(
            d.disposition.value,
            "  agent: {} {}".format(d.agent, d.dosing) if d.agent else "",
        ))
    print("--> follow_up_item.status: {}".format(result.item.status.value))
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Interstitium follow-up loop")
    ap.add_argument("--case", choices=sorted(CASES), help="run a single case")
    args = ap.parse_args()

    for name in ([args.case] if args.case else sorted(CASES)):
        run_case(name)
    print()


if __name__ == "__main__":
    main()
