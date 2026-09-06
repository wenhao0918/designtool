# -*- coding: utf-8 -*-
"""GUI runner for deepseek_s2D.py PDF export."""
import os

import FreeCAD as App
from PySide6 import QtCore

from deepseek_s2D import generate_drawing_from_step

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sample_dir = os.path.join(repo_root, 'sample')


def run_export():
    try:
        generate_drawing_from_step(
            os.path.join(sample_dir, 'complex.step'),
            pdf_output_path=os.path.join(sample_dir, 'output_GB.pdf'),
            fcstd_output_path=os.path.join(sample_dir, 'output_GB.FCStd'),
        )
    finally:
        QtCore.QCoreApplication.quit()


QtCore.QTimer.singleShot(2000, run_export)
