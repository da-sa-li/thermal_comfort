# Psychrometric Chart

Thermal Comfort draws a psychrometric chart of the air your virtual device is
watching. A psychrometric chart is the standard way to look at moist air: it
puts the dry-bulb temperature on the x-axis and the humidity ratio (how many
grams of water each kilogram of dry air carries) on the y-axis.

![Psychrometric Chart](https://raw.githubusercontent.com/dolezsa/thermal_comfort/master/screenshots/psychrometric_chart.png)

The chart currently contains:

* the **saturation curve** at 100 % relative humidity, the line above which
  water condenses out of the air,
* **constant relative humidity curves** from 10 % to 90 %,
* the **current state of the air** as a point, with guides to the temperature
  axis, to the humidity ratio axis and to its dew point on the saturation
  curve,
* a **readout** of temperature, relative humidity, humidity ratio, dew point
  and moist air enthalpy.

The axes cover 0 to 40 °C and 0 to 30 g/kg and grow in steps of 10 when the
current state falls outside of that, so they stay put while the state point
moves around.

## The Entity

A device configured through the user interface gets its chart automatically, as
one image entity, for example `image.living_room_psychrometric_chart`. With yaml
the chart is opt in: it is only created for `thermal_comfort` entries that carry
an [`image` section](#yaml-configuration).

The chart is drawn as an SVG, so it stays sharp at any size, and it follows the
light or dark color scheme of your browser.

The state of an image entity is the timestamp of the last change, which is why
you normally want to hide the state when you place it on a dashboard.

## Displaying the Chart

### Picture card

The [picture card](https://www.home-assistant.io/dashboards/picture/) shows
nothing but the chart and is the best fit for a dashboard:

```yaml
type: picture
image_entity: image.living_room_psychrometric_chart
```

### Picture entity card

The [picture entity card](https://www.home-assistant.io/dashboards/picture-entity/)
adds a name, a state and a tap action. Turn the state off, a timestamp is not
what you want to read under a chart:

```yaml
type: picture-entity
entity: image.living_room_psychrometric_chart
name: Living Room
show_state: false
```

Tapping the card opens the chart in the more info dialog, which is a
comfortable way to look at it full screen on a phone.

### Markdown card

If you want the chart next to other content, a
[markdown card](https://www.home-assistant.io/dashboards/markdown/) can embed
it through the `entity_picture` attribute. That attribute already carries the
signed url of the image, and it is refreshed for you when the chart changes:

```yaml
type: markdown
content: >-
  ### Living Room

  <img src="{{ state_attr('image.living_room_psychrometric_chart',
  'entity_picture') }}" width="100%">
```

### Saving the chart to a file

The [`image.snapshot`](https://www.home-assistant.io/integrations/image/)
action writes the current chart to disk, which is useful for notifications, for
an e-ink display or for anything outside of Home Assistant:

```yaml
action: image.snapshot
target:
  entity_id: image.living_room_psychrometric_chart
data:
  filename: /config/www/psychrometric_chart.svg
```

The target folder has to be in
[`allowlist_external_dirs`](https://www.home-assistant.io/integrations/homeassistant/#allowlist_external_dirs),
`/config/www` (served as `/local`) is allowed by default.

### Building your own card

The chart is a plain SVG document that you can fetch and inline in a custom
Lovelace card. Inlining it, instead of putting it in an `<img>` tag, lets the
css of the SVG see your Home Assistant theme variables and lets you attach your
own tooltips or click handlers. If you only need a static picture, the picture
card above is the simpler route.

### Chart cards from HACS

Cards like [plotly-graph-card](https://github.com/dbuezas/lovelace-plotly-graph-card)
or [apexcharts-card](https://github.com/RomRider/apexcharts-card) can plot the
history of a state point over time, which this chart does not do. They cannot
draw the saturation curve out of the box, so you would have to feed it in as a
second series from a template sensor. It is a trade of setup effort against
interactivity and history.

## Yaml Configuration

With yaml the chart is configured in an `image` section next to your `sensor`
section:

```yaml
thermal_comfort:
  - sensor:
      - name: Living Room
        temperature_sensor: sensor.temperature_livingroom
        humidity_sensor: sensor.humidity_livingroom
        unique_id: 2f842c63-051a-4c49-9da2-4f04ee677514
    image:
      - name: Living Room
        temperature_sensor: sensor.temperature_livingroom
        humidity_sensor: sensor.humidity_livingroom
        unique_id: 2f842c63-051a-4c49-9da2-4f04ee677514
```

Reusing the `unique_id` of the sensors puts the chart on the same virtual
device as the sensors.

### Image Configuration Variables

<dl>
  <dt><strong>name</strong> <code>string</code> <code>(optional)</code></dt>
  <dd>
    Name of the chart. It is used for the entity id and is drawn as the
    heading of the chart. e.g. Kitchen would get you
    <code>image.kitchen_psychrometric_chart</code>.
  </dd>
  <dt><strong>temperature_sensor</strong> <code>string</code> <code>REQUIRED</code></dt>
  <dd>ID of the temperature sensor entity to be charted.</dd>
  <dt><strong>humidity_sensor</strong> <code>string</code> <code>REQUIRED</code></dt>
  <dd>ID of the humidity sensor entity to be charted.</dd>
  <dt><strong>unique_id</strong> <code>string</code> <code>REQUIRED</code></dt>
  <dd>
    An ID that uniquely identifies the chart. Use the same value as for your
    sensors to get one virtual device holding both. Internally we append
    <code>psychrometric_chart</code> to it.
  </dd>
</dl>

## Notes

* The chart is drawn in °C and g/kg regardless of your Home Assistant unit
  system. Source sensors in °F are converted for you.
* Calculations assume standard atmospheric pressure at sea level (101325 Pa),
  the same assumption the moist air enthalpy sensor makes. At altitude the
  humidity ratio is higher than the chart shows.
* Below 0 °C the saturation curve is saturation over ice, which is the
  convention printed psychrometric charts use.
* Light and dark are picked from the color scheme of your browser
  (`prefers-color-scheme`), not from your Home Assistant theme. They agree as
  long as your Home Assistant theme is set to auto.
