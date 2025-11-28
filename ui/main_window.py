from pathlib import Path
import sys
from PySide6.QtWidgets import (QMainWindow, QVBoxLayout, QHBoxLayout, 
                                QPushButton, QWidget, QFileDialog, QLabel, QSlider, QStyle)
from PySide6.QtCore import Qt, QTimer, QPoint

from ui.widgets.video_widget import VideoWidget

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EpiKodi - MVP")
        self.resize(1000, 700)
        self.setStyleSheet("background-color: #1e1e1e;")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.video_widget = VideoWidget()
        self.main_layout.addWidget(self.video_widget, stretch=1)

        self.controls_container = QWidget()
        self.controls_container.setFixedHeight(80)
        self.controls_container.setStyleSheet("background-color: #2d2d2d; color: white;")
        self.controls_layout = QVBoxLayout(self.controls_container)
        

        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.sliderPressed.connect(self.on_slider_pressed)
        self.seek_slider.sliderReleased.connect(self.on_slider_released)
        self.seek_slider.sliderMoved.connect(self.on_slider_moved)
        self.controls_layout.addWidget(self.seek_slider)

        self.buttons_layout = QHBoxLayout()
        self.controls_layout.addLayout(self.buttons_layout)

        self.btn_play = QPushButton("Lecture")
        self.btn_play.clicked.connect(self.toggle_play)
        self.buttons_layout.addWidget(self.btn_play)

        self.time_label = QLabel("00:00:00 / 00:00:00")
        self.time_label.setStyleSheet("color: #aaaaaa; margin-left: 10px; font-family: monospace;")
        self.buttons_layout.addWidget(self.time_label)
        self.buttons_layout.addStretch()
        self.btn_open = QPushButton("Open Media")
        self.btn_open.clicked.connect(self.open_file)
        self.buttons_layout.addWidget(self.btn_open)

        self.buttons_layout.addStretch()
        self.buttons_layout.addWidget(QLabel("Vol:"))
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(50)
        self.vol_slider.setFixedWidth(100)
        self.vol_slider.valueChanged.connect(self.set_volume)
        self.buttons_layout.addWidget(self.vol_slider)

        self.main_layout.addWidget(self.controls_container)

        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.update_ui)
        self.timer.start()

        self.is_user_seeking = False
    def open_file(self):
            start_dir = str(Path.home() / "Videos")
            file_path, _ = QFileDialog.getOpenFileName(self, "choose media file", start_dir)
            if file_path:
                media = self.video_widget.instance.media_new(file_path)
                self.video_widget.player.set_media(media)
                self.video_widget.player.play()
                self.btn_play.setText("Pause")

    def toggle_play(self):
        if self.video_widget.player.is_playing():
            self.video_widget.player.pause()
            self.btn_play.setText("play")
        else:
            self.video_widget.player.play()
            self.btn_play.setText("pause")

    def set_volume(self, value):
        self.video_widget.player.audio_set_volume(value)

    def update_ui(self):
            """automatic call to update the seek slider and time label"""
            if self.is_user_seeking:
                return

            length = self.video_widget.player.get_length()
            time = self.video_widget.player.get_time()

            if length > 0:
                self.seek_slider.setMaximum(length)
                self.seek_slider.setValue(time)

                s_time = self.format_time(time)
                s_length = self.format_time(length)
                self.time_label.setText(f"{s_time} / {s_length}")

    def on_slider_pressed(self):
        self.is_user_seeking = True

    def on_slider_moved(self, value):
        """slide move event: update time label only"""
        target_time = value
        s_time = self.format_time(target_time)
        length = self.video_widget.player.get_length()
        s_length = self.format_time(length)
        self.time_label.setText(f"{s_time} / {s_length}")

    def on_slider_released(self):
        """User releases the slider: jump to the chosen time."""
        target_time = self.seek_slider.value()
        self.video_widget.player.set_time(target_time)
        self.is_user_seeking = False
    
    def format_time(self, ms):
        if ms < 0:
            return "00:00:00"
        seconds = (ms // 1000) % 60
        minutes = (ms // 60000) % 60
        hours = (ms // 3600000)
        return f"{hours:02}:{minutes:02}:{seconds:02}"