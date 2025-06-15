import sys
import json
import random
from datetime import datetime
import logging
import faulthandler
import math
from typing import List, Optional

faulthandler.enable()

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QGraphicsView, QGraphicsScene,
    QPushButton, QWidget, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsLineItem, QDockWidget, QMessageBox, QSpinBox, QLabel,
    QTimeEdit, QFormLayout, QInputDialog, QVBoxLayout, QTabWidget,
    QTableWidget, QTableWidgetItem, QHBoxLayout, QGroupBox
)
from PyQt6.QtGui import (
    QPixmap, QPen, QColor, QCursor, QPainter, QTransform,
    QPainterPath, QBrush
)
from PyQt6.QtCore import Qt, QRectF, QPointF, QEvent, QTimer, QTime

from scale_dialog import ScaleDialog
from behavior import (
    Agent, StoreZone, BehaviorType, BudgetLevel,
    AgentDimensions, CustomerState
)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='peopleswarm.log'
)
logger = logging.getLogger(__name__)


class AgentVisual(QGraphicsRectItem):
    """Визуальное представление агента с учетом размеров"""

    def __init__(self, agent: Agent):
        super().__init__()
        self.agent = agent

        # Настраиваем отображение в зависимости от типа
        if agent.behavior == BehaviorType.FAMILY:
            color = QColor(255, 100, 100)  # красноватый
        elif agent.behavior == BehaviorType.IMPULSIVE:
            color = QColor(100, 255, 100)  # зеленоватый
        else:
            color = QColor(100, 100, 255)  # синеватый

        self.setBrush(QBrush(color))
        self.setPen(QPen(Qt.GlobalColor.black))
        self.update_position()

    def update_position(self):
        """Обновляет положение и поворот визуального представления"""
        rect = self.agent.get_collision_rect()
        self.setRect(rect)

        # Поворачиваем в соответствии с направлением движения
        if not self.agent.finished:
            angle = math.atan2(
                self.agent.heading.y(),
                self.agent.heading.x()
            ) * 180 / math.pi

            transform = QTransform()
            transform.translate(rect.center().x(), rect.center().y())
            transform.rotate(angle)
            transform.translate(-rect.center().x(), -rect.center().y())
            self.setTransform(transform)


class ZoneDrawer(QGraphicsRectItem):
    def __init__(self, x, y, w, h, zone_type: str):
        super().__init__(x, y, w, h)
        self.zone_type = zone_type
        self.category: str | None = None
        self.attractiveness: float = 1.0
        self.visits: int = 0
        self.zone_number: int | None = None
        self.current_customers = 0

        color_map = {
            'стена': QColor(0, 0, 0, 180),
            'товары': QColor(0, 255, 0, 100),
            'касса': QColor(255, 165, 0, 150),
            'вход/выход': QColor(0, 0, 255, 120),
            'масштаб': QColor(255, 0, 255, 180)
        }
        self.setBrush(color_map.get(zone_type, QColor(255, 0, 0, 100)))
        self.setPen(QPen(Qt.GlobalColor.black, 2, Qt.PenStyle.DashLine))

    def increment_customers(self):
        self.current_customers += 1
        self.update_visual()

    def decrement_customers(self):
        self.current_customers = max(0, self.current_customers - 1)
        self.update_visual()

    def increment_visits(self):
        self.visits += 1
        self.update_visual()

    def update_visual(self):
        """Обновляет визуальное отображение в зависимости от загруженности"""
        if self.zone_type == 'касса':
            # Меняем прозрачность в зависимости от количества людей
            alpha = min(255, 150 + self.current_customers * 20)
            color = QColor(255, 165, 0, alpha)
            self.setBrush(color)
        elif self.zone_type == 'товары':
            # Меняем прозрачность в зависимости от посещений
            alpha = min(255, 100 + self.visits * 10)
            self.setBrush(QColor(0, 255, 0, alpha))


class StatsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Общая статистика
        general_group = QGroupBox("Общая статистика")
        general_layout = QVBoxLayout()

        self.stats_table = QTableWidget(5, 2)
        self.stats_table.setHorizontalHeaderLabels(['Метрика', 'Значение'])
        self.stats_table.setItem(0, 0, QTableWidgetItem('Всего посетителей'))
        self.stats_table.setItem(1, 0, QTableWidgetItem('Текущих посетителей'))
        self.stats_table.setItem(2, 0, QTableWidgetItem('Среднее время визита'))
        self.stats_table.setItem(3, 0, QTableWidgetItem('Популярная зона'))
        self.stats_table.setItem(4, 0, QTableWidgetItem('Загруженность касс'))

        general_layout.addWidget(self.stats_table)
        general_group.setLayout(general_layout)

        # Статистика по кассам
        cash_group = QGroupBox("Статистика касс")
        cash_layout = QVBoxLayout()
        self.cash_table = QTableWidget(0, 3)
        self.cash_table.setHorizontalHeaderLabels([
            'Номер кассы',
            'Текущая очередь',
            'Всего обслужено'
        ])
        cash_layout.addWidget(self.cash_table)
        cash_group.setLayout(cash_layout)

        layout.addWidget(general_group)
        layout.addWidget(cash_group)
        self.setLayout(layout)

    def update_stats(self, stats: dict):
        # Обновляем общую статистику
        self.stats_table.setItem(0, 1, QTableWidgetItem(str(stats['total_visitors'])))
        self.stats_table.setItem(1, 1, QTableWidgetItem(str(stats['current_visitors'])))
        self.stats_table.setItem(2, 1, QTableWidgetItem(
            f"{stats['avg_visit_time']:.1f} сек"
        ))

        if stats['popular_zones']:
            most_popular = max(stats['popular_zones'].items(), key=lambda x: x[1])
            self.stats_table.setItem(3, 1, QTableWidgetItem(
                f"{most_popular[0]} ({most_popular[1]} посещений)"
            ))

        # Обновляем статистику касс
        self.cash_table.setRowCount(len(stats['cash_stats']))
        for i, cash in enumerate(stats['cash_stats']):
            self.cash_table.setItem(i, 0, QTableWidgetItem(str(cash['number'])))
            self.cash_table.setItem(i, 1, QTableWidgetItem(str(cash['queue'])))
            self.cash_table.setItem(i, 2, QTableWidgetItem(str(cash['served'])))


class PeopleSwarmEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PeopleSwarm — Симуляция покупателей")
        self.setGeometry(100, 100, 1400, 900)

        # Создаем центральный виджет с вкладками
        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)

        # Вкладка симуляции
        self.sim_widget = QWidget()
        self.setup_simulation_tab()
        self.tab_widget.addTab(self.sim_widget, "Симуляция")

        # Вкладка статистики
        self.stats_widget = StatsWidget()
        self.tab_widget.addTab(self.stats_widget, "Статистика")

        # Сцена и вид
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.sim_widget.layout().addWidget(self.view)

        # Основные параметры
        self.image_item: QGraphicsPixmapItem | None = None
        self.current_zone_type = 'стена'
        self.delete_mode = False
        self.drawing = False
        self.start_pos = QPointF()
        self.temp_item = None
        self.scale_factor = 1.0
        self.real_scale = None  # мм/пиксель

        # Параметры симуляции
        self.sim_time = 0
        self.open_sec = 32400  # 9:00
        self.close_sec = 75600  # 21:00
        self.prime_start = 43200  # 12:00
        self.prime_end = 50400  # 14:00
        self.prime_mul = 2
        self.speed_mul = 1

        # Агенты и статистика
        self.agents: List[Agent] = []
        self.agent_visuals: List[AgentVisual] = []
        self.stats = {
            'total_visitors': 0,
            'current_visitors': 0,
            'avg_visit_time': 0.0,
            'popular_zones': {},
            'cash_stats': []
        }

        # Таймеры
        self.setup_timers()

        # Путь последнего сохранения
        self.last_save_path = None

        # Точки входа/выхода
        self.entry_exit_points: List[QPointF] = []

        # Настройка интерфейса
        self.init_ui()

        logger.info("PeopleSwarmEditor initialized")

    def setup_simulation_tab(self):
        layout = QVBoxLayout()
        self.sim_widget.setLayout(layout)

    def setup_timers(self):
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_loop)

        self.spawn_timer = QTimer(self)
        self.spawn_timer.timeout.connect(self.spawn_agent)

        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.update_statistics)
        self.stats_timer.start(1000)

    def init_ui(self):
        tools_dock = QDockWidget("Инструменты", self)
        tools_widget = QWidget()
        form = QFormLayout()

        # 1. Управление файлами
        file_group = QGroupBox("Файлы")
        file_layout = QVBoxLayout()

        btn_load_image = QPushButton("Загрузить изображение")
        btn_load_image.clicked.connect(self.load_image)
        btn_save = QPushButton("Сохранить разметку")
        btn_save.clicked.connect(self.save_zones)
        btn_load_layout = QPushButton("Загрузить разметку")
        btn_load_layout.clicked.connect(self.load_zones)

        file_layout.addWidget(btn_load_image)
        file_layout.addWidget(btn_save)
        file_layout.addWidget(btn_load_layout)
        file_group.setLayout(file_layout)
        form.addRow(file_group)

        # 2. Инструменты рисования
        draw_group = QGroupBox("Рисование")
        draw_layout = QVBoxLayout()

        for zone in ['стена', 'товары', 'касса', 'вход/выход', 'масштаб']:
            btn = QPushButton(f"Рисовать: {zone}")
            btn.clicked.connect(lambda checked, z=zone: self.set_zone_type(z))
            draw_layout.addWidget(btn)

        btn_del = QPushButton("Удалить объект")
        btn_del.clicked.connect(self.enable_delete_mode)
        draw_layout.addWidget(btn_del)

        draw_group.setLayout(draw_layout)
        form.addRow(draw_group)

        # 3. Параметры времени
        time_group = QGroupBox("Время работы")
        time_layout = QFormLayout()

        self.time_label = QLabel("00:00:00")
        self.time_open = QTimeEdit(QTime(9, 0))
        self.time_close = QTimeEdit(QTime(21, 0))
        self.time_prime_start = QTimeEdit(QTime(12, 0))
        self.time_prime_end = QTimeEdit(QTime(14, 0))

        time_layout.addRow("Текущее время:", self.time_label)
        time_layout.addRow("Открытие:", self.time_open)
        time_layout.addRow("Закрытие:", self.time_close)
        time_layout.addRow("Прайм с:", self.time_prime_start)
        time_layout.addRow("Прайм до:", self.time_prime_end)

        time_group.setLayout(time_layout)
        form.addRow(time_group)

        # 4. Параметры симуляции
        sim_group = QGroupBox("Параметры симуляции")
        sim_layout = QFormLayout()

        self.spin_prime_mul = QSpinBox()
        self.spin_prime_mul.setRange(1, 5)
        self.spin_prime_mul.setValue(2)

        self.clients_per_hour_spin = QSpinBox()
        self.clients_per_hour_spin.setRange(1, 1000)
        self.clients_per_hour_spin.setValue(60)

        self.spin_speed = QSpinBox()
        self.spin_speed.setRange(1, 10)
        self.spin_speed.setValue(1)

        sim_layout.addRow("Множитель прайм:", self.spin_prime_mul)
        sim_layout.addRow("Клиентов/час:", self.clients_per_hour_spin)
        sim_layout.addRow("Ускорение ×:", self.spin_speed)

        sim_group.setLayout(sim_layout)
        form.addRow(sim_group)

        # 5. Управление симуляцией
        control_group = QGroupBox("Управление")
        control_layout = QVBoxLayout()

        btn_sim = QPushButton("Запустить симуляцию")
        btn_sim.clicked.connect(self.start_simulation)

        self.btn_pause = QPushButton("Пауза")
        self.btn_pause.setCheckable(True)
        self.btn_pause.clicked.connect(self.toggle_pause)

        self.btn_stop = QPushButton("Остановить")
        self.btn_stop.clicked.connect(self.stop_simulation)

        control_layout.addWidget(btn_sim)
        control_layout.addWidget(self.btn_pause)
        control_layout.addWidget(self.btn_stop)

        control_group.setLayout(control_layout)
        form.addRow(control_group)

        tools_widget.setLayout(form)
        tools_dock.setWidget(tools_widget)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, tools_dock)

        # Мышь
        self.view.viewport().installEventFilter(self)
        self.view.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    def toggle_pause(self, checked):
        if checked:
            self.update_timer.stop()
            self.spawn_timer.stop()
            self.btn_pause.setText("Продолжить")
        else:
            self.update_timer.start()
            self.spawn_timer.start()
            self.btn_pause.setText("Пауза")

    def stop_simulation(self):
        self.update_timer.stop()
        self.spawn_timer.stop()

        # Очищаем агентов
        for visual in self.agent_visuals:
            self.scene.removeItem(visual)
        self.agents.clear()
        self.agent_visuals.clear()

        # Сбрасываем время и статистику
        self.sim_time = self.open_sec
        self.time_label.setText("09:00:00")
        self.stats = {
            'total_visitors': 0,
            'current_visitors': 0,
            'avg_visit_time': 0.0,
            'popular_zones': {},
            'cash_stats': []
        }

        # Сбрасываем состояние касс
        for item in self.scene.items():
            if isinstance(item, ZoneDrawer) and item.zone_type == 'касса':
                item.current_customers = 0
                item.visits = 0
                item.update_visual()

        # Сбрасываем кнопку паузы
        self.btn_pause.setChecked(False)
        self.btn_pause.setText("Пауза")

        logger.info("Simulation stopped")

    def update_statistics(self):
        if not self.update_timer.isActive():
            return

        # Обновляем статистику по посетителям
        self.stats['current_visitors'] = len([a for a in self.agents if not a.finished])

        # Обновляем статистику по кассам
        self.stats['cash_stats'] = []
        for item in self.scene.items():
            if isinstance(item, ZoneDrawer) and item.zone_type == 'касса':
                self.stats['cash_stats'].append({
                    'number': item.zone_number,
                    'queue': item.current_customers,
                    'served': item.visits
                })

        # Обновляем отображение статистики
        self.stats_widget.update_stats(self.stats)

        # Логируем каждую минуту
        if int(self.sim_time) % 60 == 0:
            logger.info(
                f"Stats: visitors={self.stats['current_visitors']}, "
                f"total={self.stats['total_visitors']}"
            )

    def spawn_agent(self):
        current_time = QTime(0, 0).addSecs(int(self.sim_time))
        if current_time < self.time_open.time() or current_time > self.time_close.time():
            logger.info(f"Store closed at {current_time.toString('HH:mm:ss')}")
            self.spawn_timer.stop()
            return

        mult = (
            self.prime_mul
            if (self.prime_start <= self.sim_time <= self.prime_end)
            else 1
        )

        for _ in range(mult):
            if not self.entry_exit_points:
                return

            # Получаем все необходимые зоны
            prod_zones: List[StoreZone] = []
            cash_zones: List[StoreZone] = []

            for item in self.scene.items():
                if isinstance(item, ZoneDrawer):
                    if item.zone_type == 'товары':
                        prod_zones.append(StoreZone(
                            name=item.zone_type,
                            rect=item.rect(),
                            attractiveness=item.attractiveness,
                            category=item.category
                        ))
                    elif item.zone_type == 'касса':
                        cash_zones.append(StoreZone(
                            name=item.zone_type,
                            rect=item.rect(),
                            attractiveness=item.attractiveness,
                            category=None
                        ))

            if not (prod_zones and cash_zones):
                return

            # Создаем нового агента
            behavior = random.choice(list(BehaviorType))
            budget = random.choice(list(BudgetLevel))

            start = random.choice(self.entry_exit_points)
            ag = Agent(
                start_pos=start,
                store_zones=prod_zones,
                cash_zones=cash_zones,
                exit_points=self.entry_exit_points,
                behavior=behavior,
                budget=budget,
                scale=self.real_scale or 1.0,
                speed=1.0 * self.speed_mul
            )
            self.agents.append(ag)

            # Создаем визуальное представление
            visual = AgentVisual(ag)
            self.scene.addItem(visual)
            self.agent_visuals.append(visual)

            # Обновляем статистику
            self.stats['total_visitors'] += 1

            logger.debug(
                f"Spawned agent: behavior={behavior.name}, "
                f"budget={budget.name}, speed={self.speed_mul}"
            )

        self.sim_time += self.spawn_timer.interval() / 1000

    def update_loop(self):
        delta_time = self.update_timer.interval() / 1000 * self.speed_mul
        self.sim_time += delta_time

        # Обновляем время
        current_time = QTime(0, 0).addSecs(int(self.sim_time))
        self.time_label.setText(current_time.toString("HH:mm:ss"))

        # Обновляем агентов
        for agent, visual in zip(self.agents, self.agent_visuals):
            if not agent.finished:
                agent.move_towards_target(self.agents, delta_time)
                visual.update_position()

                # Проверяем, находится ли агент в зоне
                for item in self.scene.items():
                    if isinstance(item, ZoneDrawer) and \
                       item.rect().contains(agent.position):
                        if item.zone_type == 'касса' and \
                           agent.state == CustomerState.IN_QUEUE:
                            item.increment_customers()
                        self.stats['popular_zones'][
                            f"{item.zone_type}"
                            f"{f' ({item.category})' if item.category else ''}"
                        ] = self.stats['popular_zones'].get(
                            f"{item.zone_type}"
                            f"{f' ({item.category})' if item.category else ''}",
                            0
                        ) + 1
                        item.increment_visits()

    def load_zones(self):
        fname, _ = QFileDialog.getOpenFileName(
            self, "Загрузить разметку", "", "JSON (*.json)"
        )
        if not fname:
            return

        try:
            with open(fname, 'r') as f:
                zones = json.load(f)

            # Очищаем существующие зоны
            for item in self.scene.items():
                if isinstance(item, ZoneDrawer):
                    self.scene.removeItem(item)

            self.entry_exit_points.clear()

            # Создаем новые зоны
            for zone in zones:
                drawer = ZoneDrawer(
                    zone['x'], zone['y'],
                    zone['width'], zone['height'],
                    zone['type']
                )
                drawer.category = zone.get('category')
                drawer.attractiveness = zone.get('attractiveness', 1.0)
                drawer.zone_number = zone.get('zone_number')
                self.scene.addItem(drawer)

                if zone['type'] == 'вход/выход':
                    self.entry_exit_points.append(drawer.rect().center())

            logger.info(f"Loaded {len(zones)} zones from {fname}")
            QMessageBox.information(
                self, "Загрузка", f"Загружено {len(zones)} зон"
            )
        except Exception as e:
            logger.error(f"Error loading zones: {e}")
            QMessageBox.critical(
                self, "Ошибка", f"Не удалось загрузить разметку: {str(e)}"
            )

    def save_zones(self):
        zones = []
        for item in self.scene.items():
            if isinstance(item, ZoneDrawer) and item.zone_type != 'масштаб':
                r = item.rect()
                data = {
                    'x': r.x(),
                    'y': r.y(),
                    'width': r.width(),
                    'height': r.height(),
                    'type': item.zone_type,
                    'category': item.category,
                    'attractiveness': item.attractiveness,
                    'zone_number': item.zone_number
                }
                if self.real_scale is not None:
                    data['real_width_mm'] = r.width() * self.real_scale
                    data['real_height_mm'] = r.height() * self.real_scale
                zones.append(data)

        if not zones:
            QMessageBox.warning(self, "Внимание", "Нет зон для сохранения")
            return

        fname = self.last_save_path
        if not fname:
            fname, _ = QFileDialog.getSaveFileName(
                self, "Сохранить как", "layout.json", "JSON (*.json)"
            )

        if fname:
            try:
                with open(fname, 'w') as f:
                    json.dump(zones, f, indent=2)
                self.last_save_path = fname
                logger.info(f"Saved {len(zones)} zones to {fname}")
                QMessageBox.information(
                    self, "Сохранение", f"Сохранено {len(zones)} зон"
                )
            except Exception as e:
                logger.error(f"Error saving zones: {e}")
                QMessageBox.critical(
                    self, "Ошибка", f"Не удалось сохранить: {str(e)}"
                )

    def start_simulation(self):
        # Проверяем наличие необходимых зон
        entry_exits = [item for item in self.scene.items()
                       if isinstance(item, ZoneDrawer) and
                       item.zone_type == 'вход/выход']
        if not entry_exits:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Необходимо добавить хотя бы одну зону входа/выхода"
            )
            return

        # Проверяем наличие касс
        cash_zones = [item for item in self.scene.items()
                      if isinstance(item, ZoneDrawer) and
                      item.zone_type == 'касса']
        if not cash_zones:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Необходимо добавить хотя бы одну кассу"
            )
            return

        # Проверяем наличие товарных зон
        product_zones = [item for item in self.scene.items()
                         if isinstance(item, ZoneDrawer) and
                         item.zone_type == 'товары']
        if not product_zones:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Необходимо добавить хотя бы одну зону товаров"
            )
            return

        # Проверяем установлен ли масштаб
        if self.real_scale is None:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Необходимо установить масштаб с помощью инструмента 'масштаб'"
            )
            return

        # Сбрасываем текущую симуляцию
        if self.spawn_timer.isActive():
            self.spawn_timer.stop()
        if self.update_timer.isActive():
            self.update_timer.stop()

        for visual in self.agent_visuals:
            self.scene.removeItem(visual)

        self.agents.clear()
        self.agent_visuals.clear()
        self.entry_exit_points = [item.rect().center() for item in entry_exits]

        # Сбрасываем статистику
        self.stats = {
            'total_visitors': 0,
            'current_visitors': 0,
            'avg_visit_time': 0.0,
            'popular_zones': {},
            'cash_stats': []
        }

        # Сбрасываем состояние касс
        for item in self.scene.items():
            if isinstance(item, ZoneDrawer):
                item.current_customers = 0
                item.visits = 0
                item.update_visual()

        # Настраиваем временные параметры
        o = self.time_open.time()
        self.open_sec = o.hour() * 3600 + o.minute() * 60

        c = self.time_close.time()
        self.close_sec = c.hour() * 3600 + c.minute() * 60

        ps = self.time_prime_start.time()
        self.prime_start = ps.hour() * 3600 + ps.minute() * 60

        pe = self.time_prime_end.time()
        self.prime_end = pe.hour() * 3600 + pe.minute() * 60

        self.prime_mul = self.spin_prime_mul.value()
        self.speed_mul = self.spin_speed.value()

        # Настраиваем интервал появления клиентов
        cph = self.clients_per_hour_spin.value()
        base_int = int(3600000 / cph)
        spawn_int = int(base_int / self.speed_mul)

        logger.info(
            f"Starting simulation: {cph} clients/hour, "
            f"spawn_interval={spawn_int}ms, scale={self.real_scale}mm/px"
        )

        # Запускаем таймеры
        self.sim_time = self.open_sec
        self.spawn_timer.start(spawn_int)
        self.update_timer.start(30)

        # Сбрасываем кнопку паузы
        self.btn_pause.setChecked(False)
        self.btn_pause.setText("Пауза")

    def set_zone_type(self, zone: str):
        self.current_zone_type = zone
        self.delete_mode = False
        logger.info(f"Drawing mode set to: {zone}")

    def enable_delete_mode(self):
        self.delete_mode = True
        logger.info("Delete mode enabled")

    def load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выбери изображение",
            "",
            "Images (*.png *.jpg *.bmp)"
        )
        if not path:
            return

        pix = QPixmap(path)
        if pix.isNull():
            logger.error(f"Failed to load image: {path}")
            QMessageBox.critical(
                self,
                "Ошибка",
                "Не удалось загрузить изображение"
            )
            return

        if self.image_item:
            self.scene.removeItem(self.image_item)

        self.image_item = QGraphicsPixmapItem(pix)
        self.scene.addItem(self.image_item)
        self.view.fitInView(
            self.image_item,
            Qt.AspectRatioMode.KeepAspectRatio
        )
        logger.info(f"Loaded image: {path}")

    def eventFilter(self, source, event):
        # Обработка удаления зон
        if (
                self.delete_mode and
                event.type() == QEvent.Type.MouseButtonPress and
                event.button() == Qt.MouseButton.LeftButton
        ):
            pt = self.view.mapToScene(event.position().toPoint())
            for it in self.scene.items(pt):
                if isinstance(it, ZoneDrawer):
                    if it.zone_type == 'вход/выход':
                        try:
                            self.entry_exit_points.remove(it.rect().center())
                        except ValueError:
                            pass
                    self.scene.removeItem(it)
                    logger.info(f"Deleted zone: {it.zone_type}")
                    break
            return True

        # Обработка рисования зон
        if (
                event.type() == QEvent.Type.MouseButtonPress and
                event.button() == Qt.MouseButton.LeftButton
        ):
            self.drawing = True
            self.start_pos = self.view.mapToScene(event.position().toPoint())

            if self.current_zone_type == 'масштаб':
                self.temp_item = QGraphicsLineItem()
                pen = QPen(Qt.GlobalColor.magenta, 2, Qt.PenStyle.DashLine)
                self.temp_item.setPen(pen)
            else:
                self.temp_item = ZoneDrawer(0, 0, 0, 0, self.current_zone_type)

            self.scene.addItem(self.temp_item)
            return True

        if event.type() == QEvent.Type.MouseMove and self.drawing:
            pos = self.view.mapToScene(event.position().toPoint())
            if (
                    self.current_zone_type == 'масштаб' and
                    isinstance(self.temp_item, QGraphicsLineItem)
            ):
                self.temp_item.setLine(
                    self.start_pos.x(), self.start_pos.y(),
                    pos.x(), pos.y()
                )
            elif isinstance(self.temp_item, ZoneDrawer):
                self.temp_item.setRect(QRectF(self.start_pos, pos).normalized())
            return True

        if (
                event.type() == QEvent.Type.MouseButtonRelease and
                event.button() == Qt.MouseButton.LeftButton
        ):
            self.drawing = False
            if (
                    self.current_zone_type == 'масштаб' and
                    isinstance(self.temp_item, QGraphicsLineItem)
            ):
                line = self.temp_item.line()
                dx, dy = line.x2() - line.x1(), line.y2() - line.y1()
                pix = (dx * dx + dy * dy) ** 0.5
                self.scene.removeItem(self.temp_item)
                self.temp_item = None

                dlg = ScaleDialog(pix)
                if dlg.exec():
                    self.real_scale = dlg.real_length / pix
                    QMessageBox.information(
                        self,
                        "Масштаб",
                        f"1 пиксель = {self.real_scale:.1f} мм"
                    )
                    logger.info(f"Scale set: {self.real_scale:.1f} mm/px")

            elif isinstance(self.temp_item, ZoneDrawer):
                if self.temp_item.zone_type == 'товары':
                    cat, okc = QInputDialog.getText(
                        self,
                        "Категория товара",
                        "Введите категорию (напр., \"молоко\"):"
                    )
                    if okc and cat:
                        self.temp_item.category = cat
                    att, oka = QInputDialog.getDouble(
                        self,
                        "Привлекательность",
                        "Введите коэффициент привлекательности:",
                        1.0, 0.0, 10.0, 2
                    )
                    if oka:
                        self.temp_item.attractiveness = att
                elif self.temp_item.zone_type == 'касса':
                    num, ok = QInputDialog.getInt(
                        self,
                        "Номер кассы",
                        "Введите номер кассы:",
                        1, 1, 100
                    )
                    if ok:
                        self.temp_item.zone_number = num
                elif self.temp_item.zone_type == 'вход/выход':
                    self.entry_exit_points.append(self.temp_item.rect().center())
                else:
                    self.temp_item.category = None
                    self.temp_item.attractiveness = 1.0

                logger.info(
                    f"Added zone: {self.temp_item.zone_type}, "
                    f"category={self.temp_item.category}, "
                    f"attr={self.temp_item.attractiveness}"
                )
                self.temp_item = None
            return True

        # Обработка масштабирования
        if event.type() == QEvent.Type.Wheel:
            fac = 1.1 if event.angleDelta().y() > 0 else 0.9
            self.scale_factor *= fac
            self.view.resetTransform()
            self.view.scale(self.scale_factor, self.scale_factor)
            return True

        return super().eventFilter(source, event)


if __name__ == '__main__':
    try:
        app = QApplication(sys.argv)
        editor = PeopleSwarmEditor()
        editor.show()
        sys.exit(app.exec())
    except Exception as e:
        logger.critical(f"Application crashed: {e}", exc_info=True)
        raise