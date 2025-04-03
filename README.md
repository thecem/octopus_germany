# octopus-germany
Octopus Energy Germany Home Assistant Integration
# Home Assistant Octopus Energy Germany

![installation_badge](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.octopus_germany.total) 
- [Home Assistant Octopus Energy Germany](#home-assistant-octopus-energy-germany)
  - [Features](#features)
  - [How to install](#how-to-install)
    - [HACS](#hacs)
    - [Manual](#manual)
  - [How to setup](#how-to-setup)
  - [Docs](#docs)
  - [FAQ](#faq)
  - [Sponsorship](#sponsorship)

Custom component built from the ground up to bring your Octopus Energy Germany details into Home Assistant to help you towards a more energy efficient (and or cheaper) home. This integration is built against the [Germany API](https://api.oeg-kraken.energy/v1/graphql/) provided by [Octopus Energy DE](https://octopusenergy.de/blog/ratgeber/auf-der-suche-nach-deutschen-energie-vorreitern) and has not been tested for any other countries. 

This integration is in no way affiliated with Octopus Energy.

If you find this useful and are planning on moving to Octopus Energy Germany, why not use my [referral link](https://share.octopusenergy.de/free-cat-744)?

## Features

Below are the main features of the integration

* [Dispatch Sensor]

## How to install

There are multiple ways of installing the integration. Once you've installed the integration, you'll need to [setup your account](#how-to-setup) before you can use the integration.

### HACS

[![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

This integration can be installed directly via HACS. To install:

* [Add the repository](https://my.home-assistant.io/redirect/hacs_repository/?owner=thecem&repository=octopus_germany&category=integration) to your HACS installation
* Click `Download`

### Manual

You should take the latest [published release](https://github.com/thecem/octopus_germany/releases). The current state of `develop` will be in flux and therefore possibly subject to change.

To install, place the contents of `custom_components` into the `<config directory>/custom_components` folder of your Home Assistant installation. Once installed, don't forget to restart your home assistant instance for the integration to be picked up.

## How to setup

WIP !!cPlease follow the [setup guide](https://thecem.github.io/octopus_germany/setup/account) to setup your initial account. This guide details the configuration, along with the sensors that will be available to you.

## Docs

WIP !! o get full use of the integration, please visit the [docs](https://thecem.github.io/octopus_germany/).

## FAQ

Before raising anything, please read through the [faq](https://thecem.github.io/octopus_germany/faq). If you have questions, then you can raise a [discussion](https://thecem.github.io/octopus_germany/discussions). If you have found a bug or have a feature request please [raise it](https://thecem.github.io/octopus_germany/issues) using the appropriate report template.

## Sponsorship

If you are enjoying the integration, why not use my [referral link](https://share.octopusenergy.de/free-cat-744)
