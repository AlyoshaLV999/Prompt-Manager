"""Programmatically drawn Prompt Manager application icon."""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import (
    QColor,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtCore import Qt


ICON_SIZES: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)
_CANVAS_SIZE = 128


def render_logo(size: int) -> QImage:
    """Draw and return a square application logo at ``size`` pixels.

    :param size: Output image width and height; must be positive.
    :return: An antialiased, transparent-background image.
    :raises ValueError: If ``size`` is not a positive integer.
    """

    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ValueError("Icon size must be a positive integer")

    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.scale(size / _CANVAS_SIZE, size / _CANVAS_SIZE)

    # Deep indigo tile with a paper card and a small teal prompt marker.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#172554"))
    painter.drawRoundedRect(QRectF(4, 4, 120, 120), 27, 27)

    paper = QPainterPath()
    paper.moveTo(39, 23)
    paper.lineTo(72, 23)
    paper.lineTo(94, 45)
    paper.lineTo(94, 99)
    paper.quadTo(94, 105, 88, 105)
    paper.lineTo(39, 105)
    paper.quadTo(33, 105, 33, 99)
    paper.lineTo(33, 29)
    paper.quadTo(33, 23, 39, 23)
    paper.closeSubpath()
    painter.setBrush(QColor("#F8FAFC"))
    painter.drawPath(paper)

    fold = QPainterPath()
    fold.moveTo(72, 23)
    fold.lineTo(72, 40)
    fold.quadTo(72, 45, 77, 45)
    fold.lineTo(94, 45)
    fold.closeSubpath()
    painter.setBrush(QColor("#CBD5E1"))
    painter.drawPath(fold)

    line_pen = QPen(QColor("#94A3B8"), 5, Qt.PenStyle.SolidLine)
    line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(line_pen)
    painter.drawLine(46, 58, 79, 58)
    painter.drawLine(46, 72, 79, 72)
    painter.drawLine(46, 86, 67, 86)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#2DD4BF"))
    painter.drawEllipse(QRectF(76, 76, 34, 34))
    painter.setPen(QPen(QColor("#0F172A"), 4, Qt.PenStyle.SolidLine))
    painter.drawLine(87, 93, 99, 93)
    painter.drawLine(93, 87, 93, 99)
    painter.end()
    return image


def create_app_icon() -> QIcon:
    """Return a multi-resolution Qt icon for windows and taskbars."""

    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(QPixmap.fromImage(render_logo(size)))
    return icon
