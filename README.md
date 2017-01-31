# netcheck

Monitors Internet availability and switches to alternate networks in a 
predefined order if needed. This program gave the Parkbench team more control
over the gateway network than NetworkManager alone provided.

Relies on the _timber_ logging library which can be found at 
https://github.com/park-bench/timber
Also depends on our _confighelper_ library which can be found at
https://github.com/park-bench/confighelper

netcheck is licensed under the GNU GPLv3. All source code commits prior to the
public release are also retroactively licensed under the GNU GPLv3.

Bug fixes are welcome.

This software is currently only supported on Ubuntu 14.04 and may not be ready
for use in a production environment.

The only current method of installation for our software is building and
installing your own package. We make the following assumptions:

*    You are already familiar with using a Linux terminal.
*    You already know how to use GnuPG.
*    You are already somewhat familiar with using debuild.

Clone the latest release tag, not the master branch, as master may not be
stable. Build the package with debuild from the project directory and install
with dpkg -i. Resolve any missing dependencies with apt-get -f install. The
daemon will attempt to start and fail.

Updates may change configuration file options, so if you have a configuration
file already, check that it has all of the required options in the current
example file.

## Post-install

Copy the configuration file from /etc/netcheck/netcheck.conf.example to
/etc/netcheck/netcheck.conf and fill out any necessary options, then restart
the daemon.
