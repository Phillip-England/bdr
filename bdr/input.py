"""Desktop input helpers backed by pyautogui.

This module is intentionally lazy about importing pyautogui so that script
validation and documentation commands still work in environments without the
desktop-input dependency installed.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass


class DesktopInputError(Exception):
    """Raised when desktop input or screen-inspection calls fail."""


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class Color:
    r: int
    g: int
    b: int


def _split_args(args_str: str) -> list[str]:
    args_str = args_str.strip()
    if not args_str:
        return []

    args: list[str] = []
    current: list[str] = []
    in_string: str | None = None
    depth = 0
    i = 0

    while i < len(args_str):
        ch = args_str[i]
        if in_string:
            if ch == "\\" and i + 1 < len(args_str):
                current.append(ch)
                current.append(args_str[i + 1])
                i += 2
                continue
            current.append(ch)
            if ch == in_string:
                in_string = None
        elif ch in ('"', "'"):
            current.append(ch)
            in_string = ch
        elif ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1

    tail = "".join(current).strip()
    if tail:
        args.append(tail)
    return args


class DesktopController:
    def __init__(self) -> None:
        self._pyautogui = None

    def _lib(self):
        if self._pyautogui is not None:
            return self._pyautogui

        try:
            pyautogui = importlib.import_module("pyautogui")
        except Exception as exc:  # pragma: no cover - env-specific
            raise DesktopInputError(
                "desktop input requires the optional 'pyautogui' dependency\n"
                "  Hint: Install project dependencies again so pyautogui is available.\n"
                "  Hint: Desktop automation also requires a real GUI session and OS input permissions."
            ) from exc

        pyautogui.PAUSE = 0
        self._pyautogui = pyautogui
        return pyautogui

    def screen_size(self) -> Point:
        width, height = self._lib().size()
        return Point(int(width), int(height))

    def screen_center(self) -> Point:
        size = self.screen_size()
        return Point(size.x // 2, size.y // 2)

    def mouse_position(self) -> Point:
        x, y = self._lib().position()
        return Point(int(x), int(y))

    def move_to(self, x: int, y: int, duration: float = 0.0) -> None:
        self._lib().moveTo(x, y, duration=max(duration, 0.0))

    def move_rel(self, dx: int, dy: int, duration: float = 0.0) -> None:
        self._lib().moveRel(dx, dy, duration=max(duration, 0.0))

    def drag_to(
        self,
        x: int,
        y: int,
        duration: float = 0.0,
        button: str = "left",
    ) -> None:
        self._lib().dragTo(x, y, duration=max(duration, 0.0), button=button)

    def drag_rel(
        self,
        dx: int,
        dy: int,
        duration: float = 0.0,
        button: str = "left",
    ) -> None:
        self._lib().dragRel(dx, dy, duration=max(duration, 0.0), button=button)

    def click(self, button: str = "left", clicks: int = 1) -> None:
        self._lib().click(button=button, clicks=clicks)

    def mouse_down(self, button: str = "left") -> None:
        self._lib().mouseDown(button=button)

    def mouse_up(self, button: str = "left") -> None:
        self._lib().mouseUp(button=button)

    def scroll(self, amount: int) -> None:
        self._lib().scroll(amount)

    def key_press(self, key: str) -> None:
        self._lib().press(key)

    def key_down(self, key: str) -> None:
        self._lib().keyDown(key)

    def key_up(self, key: str) -> None:
        self._lib().keyUp(key)

    def hotkey(self, *keys: str) -> None:
        self._lib().hotkey(*keys)

    def write(self, text: str, interval: float = 0.0) -> None:
        self._lib().write(text, interval=max(interval, 0.0))

    def pixel_color(self, x: int, y: int) -> Color:
        color = self._lib().screenshot().getpixel((x, y))
        if isinstance(color, int):
            color = (color, color, color)
        if len(color) >= 3:
            return Color(int(color[0]), int(color[1]), int(color[2]))
        raise DesktopInputError(f"could not read pixel color at ({x}, {y})")

    def nearest_color_point(
        self,
        color: Color,
        tolerance: int = 0,
        radius: int | None = None,
        origin: Point | None = None,
    ) -> Point:
        screenshot = self._lib().screenshot()
        width, height = screenshot.size
        pixels = screenshot.load()
        origin = origin or self.mouse_position()
        best_point: Point | None = None
        best_distance: float | None = None
        radius_sq = None if radius is None else radius * radius

        for y in range(height):
            for x in range(width):
                raw = pixels[x, y]
                if isinstance(raw, int):
                    current = Color(raw, raw, raw)
                else:
                    current = Color(int(raw[0]), int(raw[1]), int(raw[2]))

                if (
                    abs(current.r - color.r) > tolerance
                    or abs(current.g - color.g) > tolerance
                    or abs(current.b - color.b) > tolerance
                ):
                    continue

                dx = x - origin.x
                dy = y - origin.y
                distance_sq = dx * dx + dy * dy
                if radius_sq is not None and distance_sq > radius_sq:
                    continue
                if best_distance is None or distance_sq < best_distance:
                    best_distance = distance_sq
                    best_point = Point(x, y)

        if best_point is None:
            target = format_color(color)
            if radius is None:
                raise DesktopInputError(
                    f"no pixel matching {target} was found on the screen"
                )
            raise DesktopInputError(
                f"no pixel matching {target} was found within {radius} pixels of {format_point(origin)}"
            )

        return best_point


def parse_call(token: str) -> tuple[str, list[str]] | None:
    token = token.strip()
    if "(" not in token or not token.endswith(")"):
        return None
    name, _, rest = token.partition("(")
    if not name or not rest:
        return None
    inner = rest[:-1]
    return name.strip(), _split_args(inner)


def parse_int(value: str, label: str) -> int:
    try:
        return int(float(value))
    except ValueError as exc:
        raise DesktopInputError(f"{label} must be a number, got '{value}'") from exc


def parse_float(value: str, label: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise DesktopInputError(f"{label} must be a number, got '{value}'") from exc


def parse_point(value: str, label: str = "point") -> Point:
    raw = value.strip()
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 2:
        raise DesktopInputError(
            f"{label} must be formatted as 'x,y', got '{value}'"
        )
    return Point(parse_int(parts[0], f"{label} x"), parse_int(parts[1], f"{label} y"))


def parse_color_from_args(args: list[str], label: str = "color") -> Color:
    if len(args) != 3:
        raise DesktopInputError(
            f"{label} requires 3 numeric components (r, g, b), got {len(args)}"
        )
    r = parse_int(args[0], f"{label} red")
    g = parse_int(args[1], f"{label} green")
    b = parse_int(args[2], f"{label} blue")
    return parse_color(f"{r},{g},{b}", label)


def parse_color(value: str, label: str = "color") -> Color:
    raw = value.strip()
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 3:
        raise DesktopInputError(
            f"{label} must be formatted as 'r,g,b', got '{value}'"
        )
    channels = [parse_int(part, label) for part in parts]
    for channel in channels:
        if channel < 0 or channel > 255:
            raise DesktopInputError(
                f"{label} channels must be between 0 and 255, got '{value}'"
            )
    return Color(channels[0], channels[1], channels[2])


def format_point(point: Point) -> str:
    return f"{point.x},{point.y}"


def format_color(color: Color) -> str:
    return f"{color.r},{color.g},{color.b}"
