# netcheck

_netcheck_ monitors Internet availability and switches to alternate networks in a predefined
order if needed. This program gave the Parkbench team more control over the gateway network
than NetworkManager alone provided.

_netcheck_ is licensed under the GNU GPLv3. All source code commits prior to the public
release are also retroactively licensed under the GNU GPLv3.

This software is still in _beta_ and may not be ready for a production environment.

Bug fixes are welcome!

# Prerequisites

This software is currently only supported on Ubuntu 18.04.

The only supported method of installation for netcheck is building and installing your own Debian package. We make the following assumptions:

*    You are familiar with using a Linux terminal.
*    You are somewhat familiar with using debuild.
*    `debuild` is installed.

# Parkbench Dependencies

_netcheck_ depends on one other Parkbench package, which must be installed first:

* [_parkbench-common_](https://github.com/park-bench/parkbench-common)

# Steps to Build and Install

1. Clone the latest release tag. (Do not clone the `master` branch. Master might not be stable.)
2. Run `debuild` from the project root directory to build the package.
3. Run `apt install /path/to/package.deb` to install the package. The daemon will attempt to start and fail. (This is expected.)

# Post-Install configuration

## Configuring NetworkManager
1. Add any network connections you want Netcheck to manage with `nmcli con add`.
2. Set all network connections managed by Netcheck to not auto-connect with `nmcli con mod connection-name connection.autoconnect no`.

## Configuring Netcheck

Since running netcheck as a non-root user is more complex than with other Parkbench applications, you have the option of running netcheck as both a root and non-root user. In either case, you must do the following:

1. Locate the example configuration file at `/etc/netcheck/netcheck.conf.example`.
2. Copy or rename this file to `/etc/netcheck/netcheck.conf`. Edit this new file to add configuration details.
3. Remove all 'other' permission access to netcheck.conf.
4. To ease system maintenance, add 'netcheck' as a supplemental group to administrative users. Doing this will allow these users to view netcheck log files.

If you are running netcheck as a root user, please do the following:

1. Modify the configuration file to set 'run_as_root' to 'True'.

If you are running netcheck as a non-root user, please do the following:

1. Verify the configuration file has 'run_as_root' set to 'False'.
2. Run `mkdir -p /etc/dbus-1/system.d/`.
3. Replace `/etc/dbus-1/system.d/org.freedesktop.NetworkManager.conf` with a copy of `/usr/share/netcheck/etc/dbus-1/system.d/org.freedesktop.NetworkManager.conf`. This change denies access to NetworkManager except for users root and netcheck.
4. Run `mkdir -p /etc/NetworkManager/conf.d/`.
5. Copy `/usr/share/netcheck/etc/NetworkManager/conf.d/netcheck-auth-polkit-off.conf` to `/etc/NetworkManager/conf.d/`. This disables NetworkManager's polkit authentication.
6. If your system is configured for unattended-upgrades (recommended), copy `/usr/share/netcheck/etc/apt/apt.conf.d/99-netcheck-unattended-upgrades` to `/etc/apt/apt.conf.d/`. This forces automatic-upgrades (and apt) to keep local modifications of configuration files.

Once the configuration is complete, restart NetworkManager with `systemctl restart NetworkManager` and then restart netcheck with `systemctl restart netcheck`. If the above steps were followed correctly, the service should now start successfully.

# Updates

Updates may change configuration file options. If a configuration file already exists, check that it has all of the required options from the current example file.

# Known Errors and Limitations

* IPv4 and IPv6 networks do not work well together.
* Captive portal login pages typically trick netcheck into thinking it has access to the Internet.
