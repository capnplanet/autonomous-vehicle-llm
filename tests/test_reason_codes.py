from __future__ import annotations

from autonomy.reason_codes import extract_policy_reason_codes, to_policy_reason_code


def test_reason_code_maps_known_reason_text():
    assert to_policy_reason_code("battery below motion threshold") == "battery_below_motion_threshold"


def test_reason_code_slugifies_unknown_reason_text():
    assert to_policy_reason_code("Some New Reason!") == "some_new_reason"


def test_extract_policy_reason_codes_from_events():
    events = [
        "exec:arm",
        "policy_block:adapter_speed_limit",
        "fallback:return_to_home",
        "policy_block:cannot disarm away from home",
    ]

    codes = extract_policy_reason_codes(events)

    assert codes == [
        "adapter_speed_limit",
        "cannot_disarm_away_from_home",
    ]
