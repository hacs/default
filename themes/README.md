# Dark Stell Blue with Colors Theme

> Dark Stell Blue with Colors Theme by joselito11

## Screenshots

### Lights & Switches overview

![Alt text](https://github.com/joselito11/home-assistant/blob/master/Zaslonska%20slika%202020-01-25%2012-14-33.png "Optional title")
![Alt text](https://github.com/joselito11/home-assistant/blob/master/Zaslonska%20slika%202020-01-25%2012-14-59.png "Optional title")

### Map

![Alt text](https://github.com/joselito11/home-assistant/blob/master/Zaslonska%20slika%202020-01-25%2012-13-12.png "Optional title")


### Community

![Alt text](https://github.com/joselito11/home-assistant/blob/master/Zaslonska%20slika%202020-01-25%2012-13-35.png "Optional title")

### Hassio

![Alt text](https://github.com/joselito11/home-assistant/blob/master/Zaslonska%20slika%202020-01-25%2012-15-31.png "Optional title")

### Developer Tools

![Alt text](https://github.com/joselito11/home-assistant/blob/master/Zaslonska%20slika%202020-01-25%2012-16-32.png "Optional title")

### Configuration

![Alt text](https://github.com/joselito11/home-assistant/blob/master/Zaslonska%20slika%202020-01-25%2012-15-41.png "Optional title")

### Notifications

![Alt text](https://github.com/joselito11/home-assistant/blob/master/Zaslonska%20slika%202020-01-25%2012-15-59.png "Optional title")

## Installation

1. Add the following code to your `configuration.yaml` file (reboot required).

```yaml
frontend:
  ... # your configuration.
  themes: !include_dir_merge_named themes
  ... # your configuration.
```

2. Go to the Community Store.
3. Search for `DarkSteelBlueColors`.
4. Navigate to `DarkSteelBlueColors` theme.
5. Press `Install`.
6. Go to services and trigger the `frontend.reload_themes` service.
