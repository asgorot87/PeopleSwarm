import random
from enum import Enum, auto
from typing import List, Optional, Tuple
from PyQt6.QtCore import QPointF, QRectF
from dataclasses import dataclass
import math


class CustomerState(Enum):
    WALKING = auto()  # идёт к цели
    SHOPPING = auto()  # выбирает товар
    IN_QUEUE = auto()  # стоит в очереди
    PAYING = auto()  # обслуживается на кассе
    LEAVING = auto()  # идёт к выходу
    FINISHED = auto()  # завершил покупки


class BehaviorType(Enum):
    IMPULSIVE = auto()  # импульсивный (Nudge Theory)
    TARGETED = auto()  # целевой (короткий маршрут)
    EXPLORER = auto()  # исследователь (периметр, "island effect")
    FAMILY = auto()  # семейный (медленно, хаотично)
    BUDGET = auto()  # бюджетный (цена/скидки)


class BudgetLevel(Enum):
    LOW = auto()  # скидка ≥30%
    MEDIUM = auto()  # скидка ≥10%
    HIGH = auto()  # без ограничений


@dataclass
class AgentDimensions:
    """Физические размеры агентов разных типов"""
    width: float  # ширина в мм
    length: float  # длина в мм

    @staticmethod
    def get_dimensions(behavior: BehaviorType) -> 'AgentDimensions':
        if behavior == BehaviorType.FAMILY:
            return AgentDimensions(1200, 1500)  # ~4 человека
        elif behavior in [BehaviorType.IMPULSIVE, BehaviorType.TARGETED]:
            return AgentDimensions(450, 300)  # одиночка
        else:
            return AgentDimensions(900, 600)  # пара


class StoreZone:
    """
    Зона магазина:
      - name: идентификатор
      - rect: QRectF области
      - attractiveness: >1.0 — акции/скидки
      - category: для TARGETED
    """

    def __init__(
            self,
            name: str,
            rect: QRectF,
            attractiveness: float = 1.0,
            category: Optional[str] = None
    ):
        self.name = name
        self.rect = rect
        self.attractiveness = attractiveness
        self.category = category
        self.queue_length = 0
        self.max_queue_length = 5
        self.queue_spacing = 900  # 900мм между людьми в очереди

    @property
    def center(self) -> QPointF:
        return self.rect.center()

    def get_queue_position(self, pos: int, agent_dims: AgentDimensions, scale: float) -> QPointF:
        """Возвращает позицию в очереди с учетом размеров агента"""
        center = self.rect.center()
        spacing = (self.queue_spacing + agent_dims.length) / scale
        return center + QPointF(-spacing * pos, 0)

    def can_join_queue(self) -> bool:
        return self.queue_length < self.max_queue_length

    def join_queue(self) -> int:
        if self.can_join_queue():
            self.queue_length += 1
            return self.queue_length
        return -1


class CustomerGroup:
    """
    Группа (пара, семья):
      - members: агенты
      - cohesion: [0..1] — плотность группы
      - dimensions: физические размеры группы
    """

    def __init__(self, members: List["Agent"], cohesion: float = 0.5):
        self.members = members
        self.cohesion = cohesion
        self.leader = members[0] if members else None
        self.dimensions = AgentDimensions.get_dimensions(self.leader.behavior)
        for m in members:
            m.group = self


class Agent:
    """
    Агент-покупатель со сложной логикой:
      • S-O-R (utility-based выбор)
      • Right-turn bias (правило правой руки)
      • Nudge (импульсивные отклонения)
      • Social Force (избегание столкновений)
      • Разные стратегии (BehaviorType)
      • Фильтр по бюджету (BudgetLevel)
    """
    _id_counter = 0

    def __init__(
            self,
            start_pos: QPointF,
            store_zones: List[StoreZone],
            cash_zones: List[StoreZone],
            exit_points: List[QPointF],
            behavior: BehaviorType = BehaviorType.TARGETED,
            budget: BudgetLevel = BudgetLevel.MEDIUM,
            scale: float = 1.0,  # мм/пиксель
            speed: float = 1.0
    ):
        # ID
        self.id = Agent._id_counter
        Agent._id_counter += 1

        # Физические параметры
        self.position = QPointF(start_pos)
        self.dimensions = AgentDimensions.get_dimensions(behavior)
        self.scale = scale
        self.real_speed = 1000.0  # базовая скорость ~3.6 км/ч
        self.speed = speed

        # Корректируем скорость в зависимости от типа
        if behavior == BehaviorType.FAMILY:
            self.speed *= 0.7  # семьи двигаются медленнее

        # Направление движения
        self.heading = QPointF(1, 0)
        self.desired_heading = QPointF(1, 0)

        # Поведение и бюджет
        self.behavior = behavior
        self.budget = budget

        # Зоны и точки выхода
        self.all_zones = store_zones[:]
        self.unvisited_zones = store_zones[:]
        self.cash_zones = cash_zones[:]
        self.exit_points = exit_points

        # Состояние
        self.state = CustomerState.WALKING
        self.destination: Optional[QPointF] = None
        self.shopping_time = 0
        self.payment_time = 0
        self.min_shopping_time = 5
        self.max_shopping_time = 30
        self.service_time = random.uniform(30, 120)

        # Очередь
        self.current_cash_zone = None
        self.queue_position = None

        # Параметры S-O-R и Nudge
        self.reward_sensitivity = random.uniform(0.2, 1.0)
        self.cost_sensitivity = random.uniform(0.2, 1.0)
        self.imagery_vividness = random.uniform(0.2, 1.0)
        self.anticipatory_emotion_weight = random.uniform(0.2, 1.0)
        self.impulse_prob = random.uniform(0.0, 0.5)

        # Правило правой руки
        self.entry_heading = QPointF(1, 0)
        self._first_move = True

        # Группа (None для одиночек)
        self.group: Optional[CustomerGroup] = None

        # Сохранение посещённых зон
        self.visited_zones: List[StoreZone] = []

        # Выбираем первую цель
        self._choose_next_target()

    @property
    def finished(self) -> bool:
        return self.state == CustomerState.FINISHED

    def get_collision_rect(self) -> QRectF:
        """Возвращает прямоугольник коллизии в пикселях"""
        width = self.dimensions.width / self.scale
        length = self.dimensions.length / self.scale

        # Поворачиваем прямоугольник в соответствии с направлением движения
        angle = math.atan2(self.heading.y(), self.heading.x())

        # Центр прямоугольника
        cx, cy = self.position.x(), self.position.y()

        # Углы повернутого прямоугольника
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)

        hw = width / 2
        hl = length / 2

        points = [
            QPointF(cx + hw * cos_a - hl * sin_a, cy + hw * sin_a + hl * cos_a),
            QPointF(cx - hw * cos_a - hl * sin_a, cy - hw * sin_a + hl * cos_a),
            QPointF(cx - hw * cos_a + hl * sin_a, cy - hw * sin_a - hl * cos_a),
            QPointF(cx + hw * cos_a + hl * sin_a, cy + hw * sin_a - hl * cos_a)
        ]

        # Возвращаем ограничивающий прямоугольник
        xs = [p.x() for p in points]
        ys = [p.y() for p in points]
        return QRectF(
            min(xs), min(ys),
            max(xs) - min(xs),
            max(ys) - min(ys)
        )

    def distance_to(self, p: QPointF) -> float:
        dx = p.x() - self.position.x()
        dy = p.y() - self.position.y()
        return (dx * dx + dy * dy) ** 0.5

    def _check_collision(self, other: 'Agent') -> bool:
        """Проверяет коллизию с другим агентом"""
        if other is self or other.finished:
            return False
        return self.get_collision_rect().intersects(other.get_collision_rect())

    def _avoid_collisions(self, others: List["Agent"]) -> QPointF:
        """Social Force Model с учетом размеров агентов"""
        v = QPointF(0, 0)
        my_rect = self.get_collision_rect()

        for other in others:
            if other is self or other.finished:
                continue

            other_rect = other.get_collision_rect()
            if not my_rect.intersects(other_rect.adjusted(-50, -50, 50, 50)):
                continue

            # Вектор от центра другого агента к нашему
            dx = self.position.x() - other.position.x()
            dy = self.position.y() - other.position.y()
            d2 = dx * dx + dy * dy

            if d2 > 0:
                # Сила отталкивания зависит от размеров обоих агентов
                min_dist = (self.dimensions.width + other.dimensions.width) / (2 * self.scale)
                d = d2 ** 0.5

                if d < min_dist:
                    # Сильное отталкивание при близком контакте
                    f = 2.0 * (min_dist - d) / d
                    v += QPointF(dx * f, dy * f)
                else:
                    # Плавное отталкивание на расстоянии
                    f = 0.5 * math.exp(-(d - min_dist) / min_dist)
                    v += QPointF(dx * f, dy * f)

        return v

    def _zones_to_right(self, zones: List[StoreZone]) -> List[StoreZone]:
        """Правило правой руки: выбираем зоны справа от entry_heading."""
        right = []
        for z in zones:
            vec = z.center - self.position
            cross = self.entry_heading.x() * vec.y() - self.entry_heading.y() * vec.x()
            if cross < 0:
                right.append(z)
        return right

    def _utility(self, z: StoreZone) -> float:
        """S-O-R функция полезности для BUDGET и IMPULSIVE."""
        return (
                self.reward_sensitivity * z.attractiveness
                + self.anticipatory_emotion_weight * self.imagery_vividness
                - self.cost_sensitivity / max(z.attractiveness, 0.1)
        )

    def _weighted_choice(self, zones: List[StoreZone]) -> StoreZone:
        """Выбор зоны на основе весов, зависящих от поведения."""
        weights: List[float] = []
        for z in zones:
            if self.behavior == BehaviorType.EXPLORER:
                w = z.attractiveness
            elif self.behavior == BehaviorType.TARGETED:
                dist = self.distance_to(z.center)
                w = 1.0 / (1.0 + dist)
            elif self.behavior == BehaviorType.BUDGET:
                w = max(0.0, self._utility(z))
            elif self.behavior == BehaviorType.IMPULSIVE:
                base = self._utility(z)
                w = (base if random.random() < self.impulse_prob else 1.0) + random.random()
            else:  # FAMILY
                w = 0.5 + random.random() * 0.5
            weights.append(max(w, 0.0))

        total = sum(weights)
        if total <= 0:
            return random.choice(zones)
        r = random.uniform(0, total)
        for z, w in zip(zones, weights):
            r -= w
            if r <= 0:
                return z
        return zones[-1]

    def _choose_next_target(self):
        """Выбор следующей цели с учетом состояний"""
        if self.state == CustomerState.LEAVING:
            nearest_exit = min(self.exit_points, key=lambda p: self.distance_to(p))
            self.destination = nearest_exit
            return

        if not self.unvisited_zones and self.cash_zones:
            available_cash = [cz for cz in self.cash_zones if cz.can_join_queue()]
            if available_cash:
                cash = min(available_cash,
                           key=lambda cz: (cz.queue_length, self.distance_to(cz.center)))
                self.current_cash_zone = cash
                self.queue_position = cash.join_queue()
                if self.queue_position > 0:
                    self.destination = cash.get_queue_position(
                        self.queue_position,
                        self.dimensions,
                        self.scale
                    )
                    self.state = CustomerState.IN_QUEUE
                    return

        if self.unvisited_zones:
            zones = self.unvisited_zones

            if self._first_move:
                rz = self._zones_to_right(zones)
                if rz:
                    zones = rz
                self._first_move = False

            if self.budget == BudgetLevel.LOW:
                f = [z for z in zones if z.attractiveness >= 1.3]
                if f: zones = f
            elif self.budget == BudgetLevel.MEDIUM:
                f = [z for z in zones if z.attractiveness >= 1.1]
                if f: zones = f

            z = self._weighted_choice(zones)
            self.destination = z.center
            self.visited_zones.append(z)
            self.unvisited_zones.remove(z)
            self.state = CustomerState.WALKING
            return

        self.state = CustomerState.FINISHED
        self.destination = None

    def _update_heading(self, target: QPointF, avoid: QPointF):
        """Плавное обновление направления движения"""
        if self.destination:
            dx = target.x() - self.position.x()
            dy = target.y() - self.position.y()
            length = (dx * dx + dy * dy) ** 0.5
            if length > 0:
                self.desired_heading = QPointF(dx / length, dy / length)

            # Добавляем влияние избегания коллизий
            if avoid.x() != 0 or avoid.y() != 0:
                avoid_length = (avoid.x() * avoid.x() + avoid.y() * avoid.y()) ** 0.5
                avoid_norm = QPointF(avoid.x() / avoid_length, avoid.y() / avoid_length)
                self.desired_heading += avoid_norm

                # Нормализуем результирующий вектор
                dh_length = (self.desired_heading.x() * self.desired_heading.x() +
                             self.desired_heading.y() * self.desired_heading.y()) ** 0.5
                if dh_length > 0:
                    self.desired_heading = QPointF(
                        self.desired_heading.x() / dh_length,
                        self.desired_heading.y() / dh_length
                    )

            # Плавный поворот к желаемому направлению
            turn_rate = 0.2
            self.heading = QPointF(
                self.heading.x() + (self.desired_heading.x() - self.heading.x()) * turn_rate,
                self.heading.y() + (self.desired_heading.y() - self.heading.y()) * turn_rate
            )

            # Нормализуем текущее направление
            h_length = (self.heading.x() * self.heading.x() +
                        self.heading.y() * self.heading.y()) ** 0.5
            if h_length > 0:
                self.heading = QPointF(
                    self.heading.x() / h_length,
                    self.heading.y() / h_length
                )

    def move_towards_target(self, others: List["Agent"], delta_time: float = 0.033):
        """Обновление позиции с учетом времени и коллизий"""
        if self.state == CustomerState.FINISHED:
            return

        # Обработка времени покупки
        if self.state == CustomerState.SHOPPING:
            self.shopping_time += delta_time
            if self.shopping_time >= self.min_shopping_time:
                if random.random() < delta_time / (self.max_shopping_time - self.min_shopping_time):
                    self.shopping_time = 0
                    self._choose_next_target()
            return

        # Обработка кассы
        if self.state == CustomerState.PAYING:
            self.payment_time += delta_time
            if self.payment_time >= self.service_time:
                self.payment_time = 0
                self.state = CustomerState.LEAVING
                if self.current_cash_zone:
                    self.current_cash_zone.queue_length -= 1
                    self.current_cash_zone = None
                self._choose_next_target()
            return

        # Обработка очереди
        if self.state == CustomerState.IN_QUEUE:
            if not self.current_cash_zone:
                return

            queue = [ag for ag in others
                     if ag.current_cash_zone == self.current_cash_zone and
                     ag.state == CustomerState.IN_QUEUE]
            queue.sort(key=lambda ag: ag.queue_position)

            if queue and queue[0] == self:
                self.state = CustomerState.PAYING
                return

            # Обновляем позицию в очереди
            if self.queue_position:
                target = self.current_cash_zone.get_queue_position(
                    self.queue_position,
                    self.dimensions,
                    self.scale
                )
                if self.distance_to(target) > self.speed * delta_time:
                    avoid = self._avoid_collisions(others)
                    self._update_heading(target, avoid)
                    self.position += QPointF(
                        self.heading.x() * self.speed * delta_time,
                        self.heading.y() * self.speed * delta_time
                    )
            return

        # Достигли цели?
        if self.destination and self.distance_to(self.destination) <= self.speed * delta_time:
            self.position = QPointF(self.destination)

            if self.state == CustomerState.WALKING:
                if not self.cash_zones:
                    if self.destination in self.exit_points:
                        self.state = CustomerState.FINISHED
                        return
                else:
                    self.state = CustomerState.SHOPPING
                    return

            elif self.state == CustomerState.LEAVING:
                if self.destination in self.exit_points:
                    self.state = CustomerState.FINISHED
                return

            self._choose_next_target()
            return

        # Движение к цели с учетом коллизий
        if self.destination:
            avoid = self._avoid_collisions(others)
            self._update_heading(self.destination, avoid)

            # Применяем скорость с учетом масштаба и времени
            step = self.real_speed * self.scale * self.speed * delta_time
            self.position += QPointF(
                self.heading.x() * step,
                self.heading.y() * step
            )