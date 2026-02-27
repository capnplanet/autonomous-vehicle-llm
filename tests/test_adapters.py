from autonomy.models import VehicleDomain
from autonomy.vehicle_adapter import AerialVehicleAdapter, GroundVehicleAdapter, MarineVehicleAdapter


def test_adapter_capability_profiles():
    ground = GroundVehicleAdapter().capability_profile
    aerial = AerialVehicleAdapter().capability_profile
    marine = MarineVehicleAdapter().capability_profile

    assert ground.domain == VehicleDomain.GROUND
    assert aerial.domain == VehicleDomain.AERIAL
    assert marine.domain == VehicleDomain.MARINE
    assert aerial.max_speed_mps > ground.max_speed_mps > marine.max_speed_mps
