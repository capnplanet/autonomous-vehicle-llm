from autonomy.models import Action, ActionType
from autonomy.vehicle_adapter import AerialVehicleAdapter, GroundVehicleAdapter, MarineVehicleAdapter


def test_adapter_profiles_exposed():
    ground = GroundVehicleAdapter()
    aerial = AerialVehicleAdapter()
    marine = MarineVehicleAdapter()

    assert ground.capability_profile.max_speed_mps == 7.0
    assert aerial.capability_profile.max_speed_mps == 15.0
    assert marine.capability_profile.max_speed_mps == 5.0


def test_adapter_supports_rth_default():
    adapter = GroundVehicleAdapter()
    assert adapter.supports(Action(type=ActionType.RETURN_TO_HOME))
