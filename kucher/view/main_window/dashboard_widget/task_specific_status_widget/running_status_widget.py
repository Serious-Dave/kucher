#
# Copyright (C) 2018 Zubax Robotics OU
#
# This file is part of Kucher.
# Kucher is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
# Kucher is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along with Kucher.
# If not, see <http://www.gnu.org/licenses/>.
#
# Author: Pavel Kirienko <pavel.kirienko@zubax.com>
#

import math
import typing
from .base import StatusWidgetBase
from PyQt5.QtWidgets import QWidget, QLabel, QGridLayout, QFrame
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt
from view.device_model_representation import GeneralStatusView, TaskSpecificStatusReport
from view.utils import lay_out_vertically, lay_out_horizontally
from view.widgets.value_display_widget import ValueDisplayWidget
from view.widgets.flag_display_widget import FlagDisplayWidget


class Widget(StatusWidgetBase):
    # noinspection PyArgumentList
    def __init__(self, parent: QWidget):
        super(Widget, self).__init__(parent)

        self._stall_count_display =\
            self._make_display('Stall count',
                               'Number of times the rotor stalled since task activation')

        self._estimated_active_power_display =\
            self._make_display('Active power',
                               'For well-balanced systems, the estimated active power equals the DC power')

        self._demand_factor_display = \
            self._make_display('Demand factor',
                               'Percent of the maximum rated power output')

        self._mechanical_rpm_display = \
            self._make_display('Mechanical RPM',
                               'Mechanical revolutions per minute')

        self._current_frequency_display = \
            self._make_display('Current frequency',
                               'Phase current/voltage frequency')

        self._dq_display = _DQDisplayWidget(self)

        flags_box = QFrame(self)
        flags_box.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)

        self._reverse_flag_display = \
            FlagDisplayWidget(flags_box,
                              FlagDisplayWidget.StateDefinition('Forward rotation', 'jog-forward'),
                              FlagDisplayWidget.StateDefinition('Reverse rotation', 'jog-reverse'))

        self._spinup_flag_display = \
            FlagDisplayWidget(flags_box,
                              FlagDisplayWidget.StateDefinition('Started', 'ok-strong'),
                              FlagDisplayWidget.StateDefinition('Starting...', 'warning'))

        self._saturation_flag_display = \
            FlagDisplayWidget(flags_box,
                              FlagDisplayWidget.StateDefinition('Not saturated', 'ok-strong'),
                              FlagDisplayWidget.StateDefinition('Control saturation', 'control-saturation'))

        flags_box.setLayout(lay_out_horizontally(
            (self._reverse_flag_display, 1),
            (self._spinup_flag_display, 1),
            (self._saturation_flag_display, 1),
        ))
        flags_box.layout().setContentsMargins(0, 0, 0, 0)

        self.setLayout(
            lay_out_horizontally(
                lay_out_vertically(
                    lay_out_horizontally(
                        self._mechanical_rpm_display,
                        self._current_frequency_display,
                        self._demand_factor_display,
                        self._estimated_active_power_display,
                        self._stall_count_display,
                    ),
                    flags_box,
                    (None, 1),
                ),
                lay_out_vertically(
                    self._dq_display,
                    (None, 1)
                ),
            )
        )

    def reset(self):
        num_reset = 0
        for ch in self.findChildren(ValueDisplayWidget):
            num_reset += 1
            ch.reset()

        for ch in self.findChildren(FlagDisplayWidget):
            num_reset += 1
            ch.reset()

        assert num_reset > 7        # Simple paranoid check that PyQt is working as I expect it to

        self._dq_display.reset()

    def on_general_status_update(self, timestamp: float, s: GeneralStatusView):
        tssr = self._get_task_specific_status_report(TaskSpecificStatusReport.Running, s)

        self._stall_count_display.set(f'{tssr.stall_count}')

        self._estimated_active_power_display.set(f'{tssr.estimated_active_power:.0f} W')

        self._demand_factor_display.set(f'{tssr.demand_factor * 100.0:.0f}%')

        self._mechanical_rpm_display.set(
            f'{_angular_velocity_to_rpm(tssr.mechanical_angular_velocity):.0f} RPM')

        self._current_frequency_display.set(
            f'{_angular_velocity_to_frequency(tssr.electrical_angular_velocity):.1f} Hz')

        self._dq_display.set(tssr.u_dq,
                             tssr.i_dq)

        self._reverse_flag_display.set(tssr.rotation_reversed)
        self._spinup_flag_display.set(tssr.spinup_in_progress)
        self._saturation_flag_display.set(tssr.controller_saturated)

    def _make_display(self, title: str, tooltip: str) -> ValueDisplayWidget:
        return ValueDisplayWidget(self,
                                  title=title,
                                  tooltip=tooltip)


class _DQDisplayWidget(QWidget):
    # noinspection PyArgumentList
    def __init__(self, parent: QWidget):
        super(_DQDisplayWidget, self).__init__(parent)

        self._ud = _make_value_display_label(self)
        self._uq = _make_value_display_label(self)
        self._id = _make_value_display_label(self)
        self._iq = _make_value_display_label(self)

        self._ud.setToolTip('Direct axis voltage')
        self._uq.setToolTip('Quadrature axis voltage')
        self._id.setToolTip('Direct axis current')
        self._iq.setToolTip('Quadrature axis current')

        layout = QGridLayout(self)

        def sign(text: str, right=False) -> QLabel:
            w = QLabel(text, self)
            if right:
                w.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
            else:
                w.setAlignment(Qt.AlignCenter)

            return w

        # 0  1  2
        # 1 Ud Id
        # 2 Uq Iq
        layout.addWidget(sign('   Voltage   '), 0, 1)
        layout.addWidget(sign('   Current   '), 0, 2)
        layout.addWidget(sign('D', True), 1, 0)
        layout.addWidget(sign('Q', True), 2, 0)

        layout.addWidget(self._ud, 1, 1)
        layout.addWidget(self._uq, 2, 1)
        layout.addWidget(self._id, 1, 2)
        layout.addWidget(self._iq, 2, 2)

        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

    def set(self,
            u_dq: typing.Tuple[float, float],
            i_dq: typing.Tuple[float, float]):
        def fmt(x: float) -> str:
            return f'{x:.1f}'

        self._ud.setText(fmt(u_dq[0]))
        self._uq.setText(fmt(u_dq[1]))
        self._id.setText(fmt(i_dq[0]))
        self._iq.setText(fmt(i_dq[1]))

    def reset(self):
        for w in (self._ud, self._uq, self._id, self._iq):
            w.setText('0')


_2PI = math.pi * 2


def _angular_velocity_to_rpm(radian_per_sec) -> float:
    return radian_per_sec * (60.0 / _2PI)


def _angular_velocity_to_frequency(radian_per_sec) -> float:
    return radian_per_sec / _2PI


def _make_value_display_label(parent: QWidget) -> QLabel:
    w = QLabel(parent)
    w.setAlignment(Qt.AlignCenter)

    font = QFont()
    font.setBold(True)
    w.setFont(font)

    return w
