from .models import ActionType, MissionPlan


class PlanVerifier:
    def verify(self, plan: MissionPlan) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if not plan.actions:
            errors.append("plan has no actions")
            return False, errors

        if plan.actions[0].type != ActionType.ARM:
            errors.append("first action must be arm")

        if plan.actions[-1].type != ActionType.DISARM:
            errors.append("last action must be disarm")

        for idx, action in enumerate(plan.actions):
            if action.type == ActionType.MOVE_TO:
                if action.x is None or action.y is None:
                    errors.append(f"action {idx}: move_to requires x and y")
                if action.speed_mps is None or action.speed_mps <= 0:
                    errors.append(f"action {idx}: move_to requires positive speed_mps")

        return len(errors) == 0, errors
