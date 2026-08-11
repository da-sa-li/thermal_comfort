"""Tests for the psychrometric calculations and the chart renderer."""

from xml.etree import ElementTree

import pytest

from custom_components.thermal_comfort.psychrometrics import (
    STANDARD_PRESSURE,
    ChartBounds,
    dew_point,
    humidity_ratio,
    moist_air_enthalpy,
    render_psychrometric_chart,
    saturation_temperature,
    saturation_vapor_pressure,
    vapor_pressure,
)

SVG_NAMESPACE = "{http://www.w3.org/2000/svg}"


@pytest.mark.parametrize(
    ("temperature", "expected"),
    [
        # Published saturation pressures in Pa, over ice below 0 °C and over
        # liquid water above. The ASHRAE correlations reproduce them to about
        # 0.02 %, so the tolerance is what the formulas can deliver, not what
        # the maths library can.
        (-20.0, 103.24),
        (-10.0, 259.90),
        (0.0, 611.15),
        (10.0, 1228.1),
        (20.0, 2338.8),
        (30.0, 4245.5),
        (40.0, 7384.9),
    ],
)
def test_saturation_vapor_pressure(temperature, expected):
    """Saturation pressure matches the published table values."""
    assert saturation_vapor_pressure(temperature) == pytest.approx(expected, rel=5e-4)


def test_saturation_vapor_pressure_is_monotonic():
    """The saturation curve rises over the whole range the chart can show."""
    values = [saturation_vapor_pressure(t / 2) for t in range(-200, 120)]
    assert all(a < b for a, b in zip(values, values[1:]))


def test_saturation_temperature_inverts_saturation_vapor_pressure():
    """Solving for the temperature returns the temperature we started from."""
    for temperature in (-25.0, -0.5, 0.0, 12.3, 25.0, 45.0):
        pressure = saturation_vapor_pressure(temperature)
        assert saturation_temperature(pressure) == pytest.approx(temperature, abs=1e-6)


def test_saturation_temperature_clamps_to_the_search_range():
    """Pressures outside the search range return the range limits."""
    assert saturation_temperature(0.0, t_min=-40, t_max=40) == -40
    assert saturation_temperature(1e9, t_min=-40, t_max=40) == 40


def test_vapor_pressure():
    """Vapor pressure is the saturation pressure scaled by relative humidity."""
    assert vapor_pressure(20.0, 100.0) == pytest.approx(saturation_vapor_pressure(20.0))
    assert vapor_pressure(20.0, 50.0) == pytest.approx(
        saturation_vapor_pressure(20.0) / 2
    )
    assert vapor_pressure(20.0, 0.0) == 0.0


def test_humidity_ratio():
    """Humidity ratio matches hand calculated reference values."""
    assert humidity_ratio(25.0, 50.0) * 1000 == pytest.approx(9.881, abs=1e-3)
    assert humidity_ratio(20.0, 60.0) * 1000 == pytest.approx(8.734, abs=1e-3)
    # Drier air at the same temperature holds less water.
    assert humidity_ratio(25.0, 30.0) < humidity_ratio(25.0, 50.0)
    # Warmer air at the same relative humidity holds more water.
    assert humidity_ratio(25.0, 50.0) < humidity_ratio(30.0, 50.0)


def test_humidity_ratio_scales_with_pressure():
    """Thinner air at altitude holds more water for the same relative humidity."""
    assert humidity_ratio(20.0, 50.0, 80000) > humidity_ratio(
        20.0, 50.0, STANDARD_PRESSURE
    )


def test_moist_air_enthalpy():
    """Enthalpy matches the value the moist air enthalpy sensor reports."""
    assert moist_air_enthalpy(25.0, humidity_ratio(25.0, 50.0)) == pytest.approx(
        50.3219588021847
    )


def test_dew_point_of_saturated_air_is_the_air_temperature():
    """Air at 100 % relative humidity is already at its dew point."""
    for temperature in (-15.0, 0.0, 7.5, 21.0, 35.0):
        assert dew_point(humidity_ratio(temperature, 100.0)) == pytest.approx(
            temperature, abs=1e-6
        )


def test_dew_point_is_below_the_air_temperature():
    """Unsaturated air has to be cooled down before it condenses."""
    assert dew_point(humidity_ratio(25.0, 50.0)) == pytest.approx(13.864, abs=1e-3)
    assert dew_point(humidity_ratio(20.0, 60.0)) == pytest.approx(12.007, abs=1e-3)
    assert dew_point(humidity_ratio(20.0, 30.0)) < 20.0


def test_chart_bounds_keep_the_default_range_for_indoor_air():
    """Ordinary room conditions do not move the axes around."""
    bounds = ChartBounds.for_state(21.5, humidity_ratio(21.5, 45.0) * 1000)
    assert bounds == ChartBounds(t_min=0.0, t_max=40.0, w_max=30.0)


def test_chart_bounds_grow_to_include_the_state():
    """Axes are extended in fixed steps so they do not jitter."""
    assert ChartBounds.for_state(-6.0, 2.0).t_min == -10.0
    assert ChartBounds.for_state(46.0, 2.0).t_max == 50.0
    assert ChartBounds.for_state(20.0, 34.0).w_max == 40.0
    # A state exactly on the default limit still gets a margin.
    assert ChartBounds.for_state(40.0, 2.0).t_max == 50.0
    assert ChartBounds.for_state(0.0, 2.0).t_min == -10.0


def parse_svg(chart: str) -> ElementTree.Element:
    """Parse a chart, which also asserts that it is well formed xml.

    The chart is produced by the code under test, not read from anywhere, so
    the usual worries about parsing xml from an untrusted source do not apply.
    """
    return ElementTree.fromstring(chart)  # noqa: S314


def parse_chart(**kwargs) -> ElementTree.Element:
    """Render a chart with the given arguments and return it parsed."""
    return parse_svg(render_psychrometric_chart(**kwargs))


def classes_of(root: ElementTree.Element, tag: str) -> list[str]:
    """Return the css classes of all elements with the given tag."""
    return [element.get("class", "") for element in root.iter(f"{SVG_NAMESPACE}{tag}")]


def test_render_returns_a_valid_svg_document():
    """The chart is a standalone, correctly sized SVG document."""
    root = parse_chart(temperature=23.4, humidity=47.5)
    assert root.tag == f"{SVG_NAMESPACE}svg"
    assert root.get("viewBox") == "0 0 820 560"
    assert root.get("width") == "820"
    assert root.get("height") == "560"


def test_render_draws_the_saturation_curve_and_the_state():
    """The two things the chart is about are present."""
    root = parse_chart(temperature=23.4, humidity=47.5)
    assert "saturation" in classes_of(root, "path")
    assert "state-dot" in classes_of(root, "circle")
    assert "dew-dot" in classes_of(root, "circle")


def test_render_draws_relative_humidity_curves():
    """One curve is drawn per requested relative humidity."""
    root = parse_chart(
        temperature=23.4, humidity=47.5, relative_humidity_curves=(30, 60)
    )
    assert classes_of(root, "path").count("rh-curve") == 2
    labels = [element.text for element in root.iter(f"{SVG_NAMESPACE}text")]
    assert "30 %" in labels
    assert "60 %" in labels
    assert "90 %" not in labels


def test_render_reports_the_current_condition():
    """The readout lists the state and the values derived from it."""
    chart = render_psychrometric_chart(23.4, 47.5)
    assert "23.4 °C" in chart
    assert "47.5 %" in chart
    assert "8.51 g/kg" in chart
    assert "11.6 °C" in chart
    assert "45.2 kJ/kg" in chart


def test_render_without_a_state():
    """A chart is still drawn while the source sensors are unknown."""
    root = parse_chart(temperature=None, humidity=None)
    assert "saturation" in classes_of(root, "path")
    assert "state-dot" not in classes_of(root, "circle")
    assert "unavailable" in classes_of(root, "text")


def test_render_places_the_state_inside_the_plot():
    """Extreme conditions stay on the chart because the axes grow with them."""
    for temperature, humidity in ((-25.0, 95.0), (50.0, 90.0), (5.0, 1.0)):
        root = parse_chart(temperature=temperature, humidity=humidity)
        dot = next(
            element
            for element in root.iter(f"{SVG_NAMESPACE}circle")
            if element.get("class") == "state-dot"
        )
        assert 30 <= float(dot.get("cx")) <= 820 - 88
        assert 28 <= float(dot.get("cy")) <= 560 - 60


def test_render_escapes_the_title():
    """A device name can not break out of the svg."""
    chart = render_psychrometric_chart(20.0, 50.0, title='Kitchen & <Bath>"')
    assert "<Bath>" not in chart
    assert "Kitchen &amp; &lt;Bath&gt;" in chart
    assert parse_svg(chart) is not None
