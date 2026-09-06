# -*- coding: utf-8 -*-
"""FreeCAD GUI runner for exporting the default drawing."""
import os

import FreeCAD as App

from step2Draft import generate_drawing_from_step

try:
    from PySide6 import QtCore
except ImportError:
    from PySide2 import QtCore

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sample_dir = os.path.join(repo_root, 'sample')


def export_default():
    try:
        generate_drawing_from_step(
            os.path.join(sample_dir, 'complex.step'),
            pdf_output_path=os.path.join(sample_dir, 'output.pdf'),
            fcstd_output_path=os.path.join(sample_dir, 'output.FCStd'),
            views=['front', 'top', 'right'],
        )
    finally:
        QtCore.QCoreApplication.quit()


QtCore.QTimer.singleShot(2000, export_default)
