"""Play the user's full-body walking poses without assembling limb textures."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBitmap, QPainter, QPixmap, QRegion


WALK_FRAMES = 8
WALK_FRAME_MS = 80
WALK_STRIDE = 32


def walking_frames(path):
    sheet = QPixmap(str(path))
    if sheet.isNull():
        return []
    frames = []
    bounds = []
    for index in range(WALK_FRAMES):
        column, row = index % 4, index // 4
        left, right = round(column * sheet.width() / 4), round((column + 1) * sheet.width() / 4)
        top, bottom = round(row * sheet.height() / 2), round((row + 1) * sheet.height() / 2)
        frame = sheet.copy(left, top, right - left, bottom - top)
        bounds.append(QRegion(QBitmap.fromImage(
            frame.toImage().createAlphaMask(Qt.ImageConversionFlag.ThresholdDither))).boundingRect())
        frames.append(frame)
    if any(bound.isEmpty() for bound in bounds):
        return []
    # Align the bonnet tops because the source's second row has a larger upper margin.
    height = max(bound.height() for bound in bounds) + 8
    aligned = []
    for frame, bound in zip(frames, bounds):
        canvas = QPixmap(round(sheet.width() / 4), height)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.drawPixmap(0, 4 - bound.top(), frame)
        painter.end()
        aligned.append(canvas)
    return aligned
