import uuid
import random
from PyQt6.QtCore import QPointF
from behavior import Agent, BehaviorType, BudgetLevel


class AgentType:
    # Типы групп агентов и их размеры
    INDIVIDUAL = 'одинокий'
    PAIR = 'пара'
    FAMILY = 'семья'

    SIZES = {
        INDIVIDUAL: 1,
        PAIR: 2,
        FAMILY: 3
    }


class AgentGroup:
    """
    Класс для создания группы агентов (одинокий, пара, семья).
    Внутри каждой группы лидер перемещается по маршруту, а остальные следуют за ним.
    """

    def __init__(self, group_type, start_pos, target_zones, cash_zones, exit_points, scale=1.0, speed=1.0):
        self.group_type = group_type
        self.group_id = uuid.uuid4().hex
        self.members = []
        self.speed = speed

        size = AgentType.SIZES.get(group_type, 1)

        # Поведение группы
        if group_type == AgentType.INDIVIDUAL:
            behavior = random.choice([
                BehaviorType.IMPULSIVE,
                BehaviorType.TARGETED,
                BehaviorType.EXPLORER,
                BehaviorType.BUDGET
            ])
        else:
            behavior = BehaviorType.FAMILY

        # Бюджет случайный
        budget = random.choice(list(BudgetLevel))

        # Создаём агентов
        for role in range(size):
            agent = Agent(
                start_pos=start_pos,
                store_zones=target_zones.copy(),
                cash_zones=cash_zones.copy(),
                exit_points=exit_points,
                behavior=behavior,
                budget=budget,
                scale=scale,
                speed=speed
            )
            agent.group_id = self.group_id
            agent.group_type = group_type
            agent.role = role  # 0 — лидер, 1..n — последователи
            self.members.append(agent)

    def update(self):
        """
        Обновляем положение агентов:
        - лидер (role=0) движется по своему алгоритму.
        - последователи повторяют путь лидера с задержкой.
        """
        if not self.members:
            return

        leader = self.members[0]
        leader.move_towards_target(self.members)

        for i in range(1, len(self.members)):
            prev = self.members[i - 1]
            cur = self.members[i]
            direction = prev.position - cur.position
            distance = (direction.x() ** 2 + direction.y() ** 2) ** 0.5
            if distance > 0:
                step = min(self.speed, distance)
                cur.position += QPointF(direction.x() / distance * step,
                                        direction.y() / distance * step)
            else:
                cur.position = QPointF(prev.position)


def generate_agent_groups(total_agents, distribution, entrances, product_zones, cash_zones, exit_points, scale=1.0,
                          speed=1.0):
    """
    Фабрика для создания списка групп агентов.

    :param total_agents: общее число агентов
    :param distribution: словарь с распределением по типам
    :param entrances: список точек входа (QPointF)
    :param product_zones: список зон товаров (StoreZone)
    :param cash_zones: список зон касс (StoreZone)
    :param exit_points: список точек выхода (QPointF)
    :param scale: масштаб
    :param speed: базовая скорость
    :return: список AgentGroup
    """
    groups = []
    used_agents = 0
    for group_type, pct in distribution.items():
        size = AgentType.SIZES.get(group_type, 1)
        count = int(total_agents * pct // size)
        for _ in range(count):
            start = random.choice(entrances)
            group = AgentGroup(group_type, start, product_zones, cash_zones, exit_points, scale, speed)
            groups.append(group)
            used_agents += size

    # Остаток — одиночки
    remaining = total_agents - used_agents
    for _ in range(remaining):
        start = random.choice(entrances)
        group = AgentGroup(AgentType.INDIVIDUAL, start, product_zones, cash_zones, exit_points, scale, speed)
        groups.append(group)

    return groups
