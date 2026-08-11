"""Psychrometric calculations and psychrometric chart rendering.

This module is deliberately free of Home Assistant imports. It contains the
moist air maths shared by the sensors and the chart, plus a dependency free
SVG renderer for a psychrometric chart.

All formulas are taken from ASHRAE Handbook - Fundamentals 2021, chapter 1
(Psychrometrics). Equation numbers in the docstrings refer to that chapter.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from xml.sax.saxutils import escape

STANDARD_PRESSURE = 101325.0
"""Standard atmospheric pressure at sea level in Pa."""

CELSIUS_TO_KELVIN = 273.15

#: Ratio of the molecular mass of water vapor to that of dry air (eq 20).
MASS_RATIO = 0.621945

# ASHRAE fundamentals 2021 pg 1.5 eq 5, saturation over ice
_ICE_C1 = -5.6745359e03
_ICE_C2 = 6.3925247e00
_ICE_C3 = -9.6778430e-03
_ICE_C4 = 6.2215701e-07
_ICE_C5 = 2.0747825e-09
_ICE_C6 = -9.4840240e-13
_ICE_C7 = 4.1635019e00

# ASHRAE fundamentals 2021 pg 1.5 eq 6, saturation over liquid water
_WATER_C8 = -5.8002206e03
_WATER_C9 = 1.3914993e00
_WATER_C10 = -4.8640239e-02
_WATER_C11 = 4.1764768e-05
_WATER_C12 = -1.4452093e-08
_WATER_C13 = 6.5459673e00


def saturation_vapor_pressure(temperature: float) -> float:
    """Return the saturation vapor pressure in Pa for a temperature in °C.

    Below 0 °C saturation is calculated over ice (eq 5), above over liquid
    water (eq 6). This is the same convention used by printed psychrometric
    charts.
    """
    t = temperature + CELSIUS_TO_KELVIN
    if t < CELSIUS_TO_KELVIN:
        return math.exp(
            _ICE_C1 / t
            + _ICE_C2
            + _ICE_C3 * t
            + _ICE_C4 * t**2
            + _ICE_C5 * t**3
            + _ICE_C6 * t**4
            + _ICE_C7 * math.log(t)
        )
    return math.exp(
        _WATER_C8 / t
        + _WATER_C9
        + _WATER_C10 * t
        + _WATER_C11 * t**2
        + _WATER_C12 * t**3
        + _WATER_C13 * math.log(t)
    )


def saturation_temperature(
    vapor_pressure_pa: float, t_min: float = -100.0, t_max: float = 100.0
) -> float:
    """Return the temperature in °C at which air saturates at the given pressure.

    This is the numeric inverse of :func:`saturation_vapor_pressure`. Solving it
    by bisection instead of using the explicit dew point approximation (eq 39/40)
    keeps the result exactly on the saturation curve we draw.
    """
    low, high = t_min, t_max
    if vapor_pressure_pa <= saturation_vapor_pressure(low):
        return low
    if vapor_pressure_pa >= saturation_vapor_pressure(high):
        return high
    for _ in range(60):
        middle = (low + high) / 2
        if saturation_vapor_pressure(middle) < vapor_pressure_pa:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def vapor_pressure(temperature: float, humidity: float) -> float:
    """Return the partial vapor pressure in Pa (eq 22).

    :param temperature: dry-bulb temperature in °C
    :param humidity: relative humidity in %
    """
    return humidity / 100 * saturation_vapor_pressure(temperature)


def humidity_ratio(
    temperature: float, humidity: float, pressure: float = STANDARD_PRESSURE
) -> float:
    """Return the humidity ratio in kg water per kg dry air (eq 20).

    :param temperature: dry-bulb temperature in °C
    :param humidity: relative humidity in %
    :param pressure: atmospheric pressure in Pa
    """
    p_w = vapor_pressure(temperature, humidity)
    return MASS_RATIO * p_w / (pressure - p_w)


def moist_air_enthalpy(temperature: float, humidity_ratio_value: float) -> float:
    """Return the specific enthalpy of moist air in kJ per kg dry air (eq 30).

    :param temperature: dry-bulb temperature in °C
    :param humidity_ratio_value: humidity ratio in kg/kg
    """
    return 1.006 * temperature + humidity_ratio_value * (2501 + 1.86 * temperature)


def dew_point(
    humidity_ratio_value: float, pressure: float = STANDARD_PRESSURE
) -> float:
    """Return the dew point in °C for a humidity ratio in kg/kg.

    The dew point is where a horizontal line through the state point meets the
    saturation curve, so it is derived from the same saturation function the
    chart is drawn with.
    """
    p_w = pressure * humidity_ratio_value / (MASS_RATIO + humidity_ratio_value)
    return saturation_temperature(p_w)


@dataclass(frozen=True)
class ChartBounds:
    """Data space covered by the chart.

    Temperatures are in °C, humidity ratios in g water per kg dry air.
    """

    t_min: float
    t_max: float
    w_max: float

    @classmethod
    def for_state(
        cls,
        temperature: float,
        humidity_ratio_gkg: float,
        t_min: float = 0.0,
        t_max: float = 40.0,
        w_max: float = 30.0,
        step: float = 10.0,
    ) -> ChartBounds:
        """Return bounds that cover the default range plus the given state.

        The bounds are snapped to multiples of ``step`` so that the axes stay
        put while the state point moves around, instead of rescaling on every
        sensor update.
        """
        margin = step / 10
        return cls(
            t_min=min(t_min, math.floor((temperature - margin) / step) * step),
            t_max=max(t_max, math.ceil((temperature + margin) / step) * step),
            w_max=max(w_max, math.ceil((humidity_ratio_gkg + margin) / step) * step),
        )


@dataclass(frozen=True)
class _Layout:
    """Pixel geometry of the rendered chart."""

    width: int
    height: int
    left: int
    right: int
    top: int
    bottom: int

    @property
    def plot_left(self) -> int:
        """Left edge of the plot area."""
        return self.left

    @property
    def plot_right(self) -> int:
        """Right edge of the plot area."""
        return self.width - self.right

    @property
    def plot_top(self) -> int:
        """Top edge of the plot area."""
        return self.top

    @property
    def plot_bottom(self) -> int:
        """Bottom edge of the plot area."""
        return self.height - self.bottom


DEFAULT_RELATIVE_HUMIDITY_CURVES = (10, 20, 30, 40, 50, 60, 70, 80, 90)

_STYLE = """
:root {
  --tc-bg: #ffffff;
  --tc-panel: #f7f9fa;
  --tc-text: #37474f;
  --tc-muted: #78909c;
  --tc-grid: #dfe5e8;
  --tc-axis: #b0bec5;
  --tc-saturation: #0277bd;
  --tc-rh: #90a4ae;
  --tc-state: #e64a19;
}
@media (prefers-color-scheme: dark) {
  :root {
    --tc-bg: #111619;
    --tc-panel: #1b2226;
    --tc-text: #e2e8ea;
    --tc-muted: #90a4ae;
    --tc-grid: #2a3438;
    --tc-axis: #46545a;
    --tc-saturation: #4fc3f7;
    --tc-rh: #78909c;
    --tc-state: #ff7043;
  }
}
text { font-family: Roboto, "Helvetica Neue", Arial, sans-serif; fill: var(--tc-text); }
.bg { fill: var(--tc-bg); }
.plot { fill: var(--tc-panel); }
.grid { stroke: var(--tc-grid); stroke-width: 1; fill: none; }
.axis { stroke: var(--tc-axis); stroke-width: 1.25; fill: none; }
.tick { font-size: 12px; fill: var(--tc-muted); }
.axis-title { font-size: 13px; font-weight: 500; fill: var(--tc-text); }
.title { font-size: 15px; font-weight: 500; fill: var(--tc-text); }
.rh-curve { stroke: var(--tc-rh); stroke-width: 1; fill: none; opacity: 0.75; }
.rh-label {
  font-size: 10px;
  fill: var(--tc-muted);
  stroke: var(--tc-panel);
  stroke-width: 2.5px;
  paint-order: stroke;
  text-anchor: middle;
}
.saturation { stroke: var(--tc-saturation); stroke-width: 2.25; fill: none;
  stroke-linecap: round; stroke-linejoin: round; }
.saturation-label { font-size: 11px; font-weight: 500; fill: var(--tc-saturation);
  stroke: var(--tc-panel); stroke-width: 2.5px; paint-order: stroke; text-anchor: middle; }
.guide { stroke: var(--tc-state); stroke-width: 1; stroke-dasharray: 4 3;
  opacity: 0.7; fill: none; }
.state-halo { fill: var(--tc-state); opacity: 0.18; }
.state-dot { fill: var(--tc-state); stroke: var(--tc-bg); stroke-width: 2; }
.dew-dot { fill: none; stroke: var(--tc-state); stroke-width: 1.5; }
.readout-box { fill: var(--tc-bg); stroke: var(--tc-grid); stroke-width: 1; opacity: 0.94; }
.readout-key { font-size: 11px; fill: var(--tc-muted); }
.readout-value { font-size: 12px; font-weight: 500; fill: var(--tc-text); text-anchor: end; }
.unavailable { font-size: 14px; fill: var(--tc-muted); text-anchor: middle; }
"""


def _fmt(value: float) -> str:
    """Format a coordinate without trailing zeros to keep the SVG small."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _tick_step(span: float, target: int = 8) -> float:
    """Return a human friendly tick step covering span in about target steps."""
    if span <= 0:
        return 1.0
    raw = span / target
    magnitude = 10 ** math.floor(math.log10(raw))
    for multiple in (1, 2, 2.5, 5):
        if raw <= multiple * magnitude:
            return multiple * magnitude
    return 10 * magnitude


def _ticks(start: float, stop: float, step: float) -> list[float]:
    """Return tick values from start to stop, inclusive of both ends."""
    first = math.ceil(start / step) * step
    # Counting the ticks up front keeps floating point drift from adding or
    # dropping the last one.
    count = int((stop - first) / step + 1 + 1e-9)
    return [round(first + index * step, 6) for index in range(max(count, 0))]


class _Scale:
    """Map psychrometric data coordinates to SVG pixel coordinates."""

    def __init__(self, bounds: ChartBounds, layout: _Layout) -> None:
        """Initialize the scale for the given bounds and layout."""
        self._bounds = bounds
        self._layout = layout

    def x(self, temperature: float) -> float:
        """Return the pixel x for a temperature in °C."""
        bounds, layout = self._bounds, self._layout
        fraction = (temperature - bounds.t_min) / (bounds.t_max - bounds.t_min)
        return layout.plot_left + fraction * (layout.plot_right - layout.plot_left)

    def y(self, humidity_ratio_gkg: float) -> float:
        """Return the pixel y for a humidity ratio in g/kg."""
        layout = self._layout
        fraction = humidity_ratio_gkg / self._bounds.w_max
        return layout.plot_bottom - fraction * (layout.plot_bottom - layout.plot_top)


def _relative_humidity_curve(
    relative_humidity: float,
    bounds: ChartBounds,
    pressure: float,
    samples: int = 96,
) -> list[tuple[float, float]]:
    """Return the (°C, g/kg) points of a constant relative humidity line.

    The curve is cut off where it leaves the top of the chart. Because the
    humidity ratio grows monotonically with temperature the crossing point can
    be found with a plain bisection on the last segment.
    """
    span = bounds.t_max - bounds.t_min
    points: list[tuple[float, float]] = []
    for index in range(samples + 1):
        temperature = bounds.t_min + span * index / samples
        w_gkg = humidity_ratio(temperature, relative_humidity, pressure) * 1000
        if w_gkg > bounds.w_max:
            if points:
                low, high = points[-1][0], temperature
                for _ in range(40):
                    middle = (low + high) / 2
                    if (
                        humidity_ratio(middle, relative_humidity, pressure) * 1000
                        <= bounds.w_max
                    ):
                        low = middle
                    else:
                        high = middle
                points.append((low, bounds.w_max))
            break
        points.append((temperature, w_gkg))
    return points


def _path(points: list[tuple[float, float]], scale: _Scale) -> str:
    """Return an SVG path definition for data space points."""
    return " ".join(
        f"{'M' if index == 0 else 'L'}{_fmt(scale.x(t))} {_fmt(scale.y(w))}"
        for index, (t, w) in enumerate(points)
    )


def _curve_label(
    points: list[tuple[float, float]],
    scale: _Scale,
    text: str,
    css_class: str,
    position: float = 0.68,
) -> str:
    """Return a label rotated along the tangent of a curve."""
    if len(points) < 2:
        return ""
    index = min(max(int(len(points) * position), 1), len(points) - 1)
    x1, y1 = scale.x(points[index - 1][0]), scale.y(points[index - 1][1])
    x2, y2 = scale.x(points[index][0]), scale.y(points[index][1])
    angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
    # Lift the text a little above the curve it belongs to.
    return (
        f'<text class="{css_class}" x="{_fmt(x2)}" y="{_fmt(y2)}" '
        f'transform="rotate({_fmt(angle)} {_fmt(x2)} {_fmt(y2)})" dy="-5">'
        f"{escape(text)}</text>"
    )


def _readout(
    rows: list[tuple[str, str]],
    x: float,
    y: float,
    width: float = 168,
) -> str:
    """Return a small panel listing the current air condition."""
    line_height = 18
    padding = 10
    height = padding * 2 + line_height * len(rows)
    parts = [
        f'<rect class="readout-box" x="{_fmt(x)}" y="{_fmt(y)}" '
        f'width="{_fmt(width)}" height="{_fmt(height)}" rx="6"/>'
    ]
    for index, (key, value) in enumerate(rows):
        baseline = y + padding + line_height * index + 13
        parts.append(
            f'<text class="readout-key" x="{_fmt(x + padding)}" '
            f'y="{_fmt(baseline)}">{escape(key)}</text>'
        )
        parts.append(
            f'<text class="readout-value" x="{_fmt(x + width - padding)}" '
            f'y="{_fmt(baseline)}">{escape(value)}</text>'
        )
    return "".join(parts)


def render_psychrometric_chart(
    temperature: float | None,
    humidity: float | None,
    *,
    pressure: float = STANDARD_PRESSURE,
    title: str | None = None,
    width: int = 820,
    height: int = 560,
    relative_humidity_curves: tuple[int, ...] = DEFAULT_RELATIVE_HUMIDITY_CURVES,
    unavailable_text: str = "Waiting for temperature and humidity",
) -> str:
    """Render a psychrometric chart as an SVG document.

    The chart plots the humidity ratio over the dry-bulb temperature. It shows
    the saturation curve (100 % relative humidity), a set of constant relative
    humidity curves and the current state of the air.

    :param temperature: dry-bulb temperature in °C, None if unknown
    :param humidity: relative humidity in %, None if unknown
    :param pressure: atmospheric pressure in Pa
    :param title: optional heading drawn above the plot
    :param width: width of the SVG in pixels
    :param height: height of the SVG in pixels
    :param relative_humidity_curves: relative humidity values in % to draw
    :param unavailable_text: shown instead of a state point when input is missing
    :returns: a standalone SVG document
    """
    has_state = temperature is not None and humidity is not None
    w_kgkg = humidity_ratio(temperature, humidity, pressure) if has_state else 0.0
    w_gkg = w_kgkg * 1000

    bounds = ChartBounds.for_state(
        temperature if has_state else 20.0, w_gkg if has_state else 0.0
    )
    layout = _Layout(
        width=width,
        height=height,
        left=30,
        right=88,
        top=44 if title else 28,
        bottom=60,
    )
    scale = _Scale(bounds, layout)

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Psychrometric chart">',
        f"<style>{_STYLE}</style>",
        f'<rect class="bg" width="{width}" height="{height}"/>',
    ]

    if title:
        parts.append(
            f'<text class="title" x="{layout.plot_left}" y="26">{escape(title)}</text>'
        )

    plot_width = layout.plot_right - layout.plot_left
    plot_height = layout.plot_bottom - layout.plot_top
    parts.append(
        f'<rect class="plot" x="{layout.plot_left}" y="{layout.plot_top}" '
        f'width="{plot_width}" height="{plot_height}"/>'
    )

    # Grid and ticks.
    t_step = _tick_step(bounds.t_max - bounds.t_min)
    w_step = _tick_step(bounds.w_max, target=6)
    for value in _ticks(bounds.t_min, bounds.t_max, t_step):
        x = scale.x(value)
        parts.append(
            f'<path class="grid" d="M{_fmt(x)} {layout.plot_top}'
            f'V{layout.plot_bottom}"/>'
        )
        parts.append(
            f'<text class="tick" x="{_fmt(x)}" y="{layout.plot_bottom + 18}" '
            f'text-anchor="middle">{_fmt(value)}</text>'
        )
    for value in _ticks(0, bounds.w_max, w_step):
        y = scale.y(value)
        parts.append(
            f'<path class="grid" d="M{layout.plot_left} {_fmt(y)}'
            f'H{layout.plot_right}"/>'
        )
        parts.append(
            f'<text class="tick" x="{layout.plot_right + 8}" y="{_fmt(y + 4)}">'
            f"{_fmt(value)}</text>"
        )

    parts.append(
        f'<path class="axis" d="M{layout.plot_left} {layout.plot_bottom}'
        f'H{layout.plot_right}V{layout.plot_top}"/>'
    )
    parts.append(
        f'<text class="axis-title" x="{_fmt((layout.plot_left + layout.plot_right) / 2)}" '
        f'y="{layout.plot_bottom + 42}" text-anchor="middle">'
        f"Dry-bulb temperature (°C)</text>"
    )
    moisture_axis_x = layout.plot_right + 56
    moisture_axis_y = (layout.plot_top + layout.plot_bottom) / 2
    parts.append(
        f'<text class="axis-title" x="{_fmt(moisture_axis_x)}" '
        f'y="{_fmt(moisture_axis_y)}" text-anchor="middle" '
        f'transform="rotate(90 {_fmt(moisture_axis_x)} {_fmt(moisture_axis_y)})">'
        f"Humidity ratio (g/kg dry air)</text>"
    )

    # Constant relative humidity curves below saturation. Curves for a high
    # relative humidity are steep and leave the chart early, so their labels are
    # pushed towards the end of the curve to spread all labels over the plot
    # instead of piling them up next to the saturation curve.
    for relative_humidity in relative_humidity_curves:
        points = _relative_humidity_curve(relative_humidity, bounds, pressure)
        if len(points) < 2:
            continue
        parts.append(f'<path class="rh-curve" d="{_path(points, scale)}"/>')
        parts.append(
            _curve_label(
                points,
                scale,
                f"{relative_humidity} %",
                "rh-label",
                position=0.3 + 0.006 * relative_humidity,
            )
        )

    # Saturation curve, the defining line of the chart.
    saturation = _relative_humidity_curve(100, bounds, pressure, samples=160)
    if len(saturation) >= 2:
        parts.append(f'<path class="saturation" d="{_path(saturation, scale)}"/>')
        parts.append(
            _curve_label(
                saturation, scale, "100 % saturation", "saturation-label", 0.55
            )
        )

    if has_state:
        state_x = scale.x(temperature)
        state_y = scale.y(w_gkg)
        dew = dew_point(w_kgkg, pressure)
        enthalpy = moist_air_enthalpy(temperature, w_kgkg)

        # Guides to the temperature axis, to the moisture axis and to the dew
        # point on the saturation curve.
        parts.append(
            f'<path class="guide" d="M{_fmt(state_x)} {_fmt(state_y)}'
            f'V{layout.plot_bottom}"/>'
        )
        parts.append(
            f'<path class="guide" d="M{_fmt(state_x)} {_fmt(state_y)}'
            f'H{layout.plot_right}"/>'
        )
        if bounds.t_min <= dew <= temperature:
            dew_x = scale.x(dew)
            parts.append(
                f'<path class="guide" d="M{_fmt(dew_x)} {_fmt(state_y)}'
                f'H{_fmt(state_x)}"/>'
            )
            parts.append(
                f'<circle class="dew-dot" cx="{_fmt(dew_x)}" cy="{_fmt(state_y)}" r="4"/>'
            )

        parts.append(
            f'<circle class="state-halo" cx="{_fmt(state_x)}" cy="{_fmt(state_y)}" r="11"/>'
        )
        parts.append(
            f'<circle class="state-dot" cx="{_fmt(state_x)}" cy="{_fmt(state_y)}" r="5.5"/>'
        )

        parts.append(
            _readout(
                [
                    ("Temperature", f"{temperature:.1f} °C"),
                    ("Relative humidity", f"{humidity:.1f} %"),
                    ("Humidity ratio", f"{w_gkg:.2f} g/kg"),
                    ("Dew point", f"{dew:.1f} °C"),
                    ("Enthalpy", f"{enthalpy:.1f} kJ/kg"),
                ],
                x=layout.plot_left + 16,
                y=layout.plot_top + 16,
            )
        )
    else:
        parts.append(
            f'<text class="unavailable" '
            f'x="{_fmt((layout.plot_left + layout.plot_right) / 2)}" '
            f'y="{_fmt((layout.plot_top + layout.plot_bottom) / 2)}">'
            f"{escape(unavailable_text)}</text>"
        )

    parts.append("</svg>")
    return "".join(parts)
