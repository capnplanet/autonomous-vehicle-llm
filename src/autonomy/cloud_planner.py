from .models import Action, ActionType, MissionPlan


class CloudPlanner:
    def build_plan(self, goal: str, vehicle_id: str) -> MissionPlan:
        goal_key = goal.strip().lower()
        if "patrol" in goal_key:
            actions = [
                Action(type=ActionType.ARM),
                Action(type=ActionType.MOVE_TO, x=20, y=20, speed_mps=4),
                Action(type=ActionType.MOVE_TO, x=-20, y=20, speed_mps=4),
                Action(type=ActionType.MOVE_TO, x=-20, y=-20, speed_mps=4),
                Action(type=ActionType.MOVE_TO, x=20, y=-20, speed_mps=4),
                Action(type=ActionType.RETURN_TO_HOME),
                Action(type=ActionType.DISARM),
            ]
        else:
            actions = [
                Action(type=ActionType.ARM),
                Action(type=ActionType.MOVE_TO, x=10, y=0, speed_mps=3),
                Action(type=ActionType.RETURN_TO_HOME),
                Action(type=ActionType.DISARM),
            ]
        return MissionPlan(goal=goal, vehicle_id=vehicle_id, actions=actions)
