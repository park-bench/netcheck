# netcheck

_netcheck_ monitors Internet availability and switches to alternate networks in a predefined
order if needed. This program gave the Parkbench team more control over the gateway network
than NetworkManager alone provided.

Also depends on our _confighelper_ library which can be found at
https://github.com/park-bench/confighelper

netcheck is licensed under the GNU GPLv3. All source code commits prior to the public release
are also retroactively licensed under the GNU GPLv3.

Bug fixes are welcome!

## Prerequisites

This software is currently only supported on Ubuntu 14.04 and may not be ready for use in a
production environment.

The only current method of installation for our software is building and installing your own
debian package. We make the following assumptions:

*    You are already familiar with using a Linux terminal.
*    You are already somewhat familiar with using debuild.
*    `build-essential` is installed.
*    `devscripts` is installed.

## Parkbench Dependencies

_netcheck_ depends on one other piece of the Parkbench project, which must be installed
first:

* [_confighelper_](https://github.com/park-bench/confighelper)

## Steps to Build and Install

1. Clone the latest release tag. (Do not clone the master branch. `master` may not be
   stable.)
2. Use `debuild` from the project root directory to build the package.
3. Use `dpkg -i` to install the package.
4. Use `apt-get -f install` to resolve any missing dependencies. The daemon will attempt to
   start and fail. (This is expected.)

## Post-Install configuration

# Configuring NetworkManager
1. Edit the file `/etc/network/interfaces` and remove any interfaces that you want Netcheck
   to use.
2. Add any network interfaces you want Netcheck to use with `nmcli con add`.

# Configuring Netcheck
1. Locate the example configuration file at `/etc/netcheck/netcheck.conf.example`.
2. Copy or rename this file to `netcheck.conf` in the same directory. Edit this file to add
   configuration details.
3. Restart the daemon with `service netcheck restart`. If the configuration file is valid and
   named correctly, the service will now start successfully.

## Updates

Updates may change configuration file options, so if you have a configuration
file already, check that it has all of the required options in the current
example file.
