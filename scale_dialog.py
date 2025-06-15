from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox


class ScaleDialog(QDialog):
    def __init__(self, pixel_length):
        super().__init__()
        self.setWindowTitle("Задать масштаб")
        self.pixel_length = pixel_length
        self.real_length = None

        layout = QVBoxLayout()

        label = QLabel(f"Укажите реальную длину отрезка в миллиметрах\n(длина в пикселях: {self.pixel_length:.2f})")
        layout.addWidget(label)

        self.input = QLineEdit()
        layout.addWidget(self.input)

        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self.validate_and_accept)
        layout.addWidget(btn_ok)

        self.setLayout(layout)

    def validate_and_accept(self):
        try:
            self.real_length = float(self.input.text().replace(",", "."))
            if self.real_length <= 0:
                raise ValueError("Длина должна быть больше нуля!")
            self.accept()
        except ValueError as e:
            QMessageBox.critical(self, "Ошибка ввода", str(e))
