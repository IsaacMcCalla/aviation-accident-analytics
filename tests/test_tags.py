"""nlp_narratives.py: each keyword rule matches what it should and nothing it should not.

When you add or change a rule in TAGS, add an example of each kind here.
"""
import pytest

from nlp_narratives import PATTERNS, TAGS

MATCHES = {
    "fuel_exhaustion": ["a total loss of engine power due to fuel exhaustion", "FUEL STARVATION"],
    "loss_of_control": ["the pilot's loss of control during the landing roll", "loss of aircraft control"],
    "vfr_into_imc": ["continued VFR flight into instrument meteorological conditions",
                     "VFR FLIGHT INTO IMC", "inadvertent encounter with IMC"],
    "stall": ["resulted in an aerodynamic stall", "exceeded the airplane's critical angle of attack"],
    "cfit": ["controlled flight into terrain", "failure to maintain adequate terrain clearance"],
    "maintenance": ["the mechanic's improper maintenance of the fuel selector"],
    "density_altitude": ["the high density altitude"],
    "spatial_disorientation": ["the pilot's spatial disorientation"],
    "impairment": ["the pilot's impairment by alcohol", "effects of marijuana"],
    "crosswind": ["inadequate compensation for the crosswind"],
    "engine_power_loss": ["a partial loss of engine power", "an engine failure for undetermined reasons"],
    "midair": ["a midair collision", "the mid-air collision"],
    "wire_strike": ["the helicopter struck power lines", "collided with wires"],
    "bird_strike": ["a bird strike during the initial climb", "collision with birds"],
}
NO_MATCH = {
    "fuel_exhaustion": ["fuel exhausted vapor"],
    "stall": ["the engine stalled"],   # an engine stall is not an aerodynamic stall
    "impairment": ["toxicology was negative"],
    "crosswind": ["the cross country flight"],
    "midair": ["the aircraft was in the air"],
}


def test_every_rule_has_examples():
    assert set(MATCHES) == set(TAGS)


@pytest.mark.parametrize("tag,text", [(t, x) for t, xs in MATCHES.items() for x in xs])
def test_rule_matches(tag, text):
    assert PATTERNS[tag][0].search(text)


@pytest.mark.parametrize("tag,text", [(t, x) for t, xs in NO_MATCH.items() for x in xs])
def test_rule_does_not_match(tag, text):
    assert not PATTERNS[tag][0].search(text)


def test_cause_rules_ignore_the_factual_narrative():
    # toxicology wording in factual narratives gave false impairment matches; see the module docstring
    assert PATTERNS["impairment"][1] == "cause"
    assert PATTERNS["engine_power_loss"][1] == "all"
