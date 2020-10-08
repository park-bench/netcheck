# netcheck

_netcheck_ monitors Internet availability and, if needed, switches to alternative connections
in a predefined order. This program provides more control over the gateway connection than
NetworkManager alone provides.

netcheck is licensed under the GNU GPLv3. All source code commits prior to the public release
are also retroactively licensed under the GNU GPLv3.

This software is still in _beta_ and may not be ready for use in a production environment.

Bug fixes are welcome!

## Prerequisites

This software is currently only supported on Ubuntu 18.04.

Currently, the only supported method for installation of this project is building and
installing a Debian package. The rest of these instructions make the following assumptions:

*   You are familiar with using a Linux terminal.
*   You are somewhat familiar with using `debuild`.
*   You are familiar with using `git` and GitHub.
*   `debhelper` and `devscripts` are installed on your build server.
*   You are familiar with GnuPG (for deb signing).

## Parkbench Dependencies

netcheck depends on one other Parkbench package, which must be installed first:

*   [parkbench-common](https://github.com/park-bench/parkbench-common)

## Steps to Build and Install

1.  Clone the repository and checkout the latest release tag. (Do not build against the
    `master` branch. The `master` branch might not be stable.)
2.  Run `debuild` in the project root directory to build the package.
3.  Run `apt install /path/to/package.deb` to install the package. The daemon will attempt to
    start and fail. (This is expected.)

## Post-Install configuration

### Configuring NetworkManager

1.  Add any network connections you want Netcheck to manage with `nmcli con add`.
2.  Set all network connections managed by Netcheck to not auto-connect with
    `nmcli con mod connection-name connection.autoconnect no`.

### Configuring Netcheck

Since running netcheck as a non-root user is more complex than with other Parkbench
applications, you have the option of running netcheck as both a root and non-root user. In
either case, you must do the following:

1.  Copy or rename the example configuration file `/etc/netcheck/netcheck.conf.example` to
    `/etc/netcheck/netcheck.conf`. Edit this file to enter the connection IDs, nameservers,
    and queryable domains. Other settings can also be modified.
2.  Change the ownership and permissions of the configuration file:
```
chown root:netcheck /etc/netcheck/netcheck.conf
chmod u=rw,g=r,o= /etc/netcheck/netcheck.conf
```
3.  To ease system maintenance, add `netcheck` as a supplemental group to administrative
    users. Doing this will allow these users to view netcheck log files.

If you are running netcheck as a root user, please do the following:

1.  Modify the configuration file to set 'run_as_root' to 'True'.

If you are running netcheck as a non-root user, please do the following:

1.  Verify the configuration file has 'run_as_root' set to 'False'.
2.  Run `mkdir -p /etc/dbus-1/system.d/`.
3.  Replace `/etc/dbus-1/system.d/org.freedesktop.NetworkManager.conf` with a copy of
    `/usr/share/netcheck/etc/dbus-1/system.d/org.freedesktop.NetworkManager.conf`. This change
    denies access to NetworkManager except for users root and netcheck.
4.  Run `mkdir -p /etc/NetworkManager/conf.d/`.
5.  Copy `/usr/share/netcheck/etc/NetworkManager/conf.d/netcheck-auth-polkit-off.conf` to
    `/etc/NetworkManager/conf.d/`. This disables NetworkManager's polkit authentication.
6.  If your system is configured for unattended-upgrades (recommended), copy
    `/usr/share/netcheck/etc/apt/apt.conf.d/99-netcheck-unattended-upgrades` to
    `/etc/apt/apt.conf.d/`. This forces automatic-upgrades (and apt) to keep local
    modifications of configuration files.

Once the configuration is complete, restart NetworkManager with
`systemctl restart NetworkManager` and then restart netcheck with
`systemctl restart netcheck`. If the above steps were followed correctly, the service will
start successfully.

## Updates

Updates may change configuration file options. If a configuration file already exists, check
that it has all of the required options from the current example file.

## Known Errors and Limitations

*   IPv4 and IPv6 networks do not work well together.
*   Captive portal login pages typically trick netcheck into thinking it has access to the
    Internet.
