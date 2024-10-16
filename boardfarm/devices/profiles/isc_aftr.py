#!/usr/bin/env python3
"""Linux based DSLite server using ISC AFTR."""
import ipaddress
import os
import sys
from collections import Counter, OrderedDict

import pexpect

from boardfarm.devices.profiles import base_profile
from boardfarm.lib.installers import apt_install, install_wget


class AFTR(base_profile.BaseProfile):
    """Linux based DSLite server using ISC AFTR.

    This profile class should be inherited along
    with a Linux Derived Class.
    """

    model = "aftr"
    aftr_dir = "/root/aftr"
    aftr_url = "https://downloads.isc.org/isc/lwds-lite/1.0/rt28354.tbz"

    # this can be used to override behavior.
    # base device's method can be key.
    # e.g. Debian's configure method can call profile's configure method using self.profile['configure']
    profile = {}

    def __init__(self, *args, **kwargs):
        """To initialize the container details."""
        self.aftr_conf = OrderedDict()
        self.is_installed = False

        # IPv6 ep must be from a different subnet than WAN container.
        self.ipv6_ep = ipaddress.IPv6Interface(str(kwargs.get("ipv6_ep", "2001::1/48")))
        # Open gateway subnets need to be in this ACL.
        self.ipv6_acl = [
            str(self.ipv6_ep.network),
            str(self.ipv6_interface.network),
        ] + kwargs.get("ipv6_ACL", ["2001:dead:beef::/48"])

        # this address will double NAT to WAN container's public IP
        self.ipv4_nat = ipaddress.IPv4Interface(
            str(kwargs.get("ipv4_nat", "198.18.200.111/16"))
        )
        self.ipv4_nat_ip = str(self.ipv4_nat.ip)

        # static pool port range
        self.ipv4_nat_pool = kwargs.get("ipv4_nat_pool", "5000-59999")
        # dynamic pool port range
        self.ipv4_pcp_pool = kwargs.get("ipv4_pcp_pool", "60000-64999")

        # default mss size is 1420
        self.mtu = kwargs.get("mss", "1420")

        # local URL of aftr tarball. If we have an offline mirror.
        self.aftr_local = kwargs.get("local_site", None)
        self.aftr_fqdn = kwargs.get("aftr_fqdn", "aftr.boardfarm.com")

        AFTR.configure_profile(
            self,
            self.configure_aftr,
            hosts={"aftr.boardfarm.com": str(self.ipv6_ep.ip)},
        )

    def configure_aftr(self):
        """Check the aftr exists already else configuring the same."""
        self.install_aftr()
        start_conf = self.generate_aftr_conf()
        start_script = self.generate_aftr_script()

        run_conf = None
        # check if aftr.conf already exists
        self.sendline("ls /root/aftr/aftr.conf")
        if self.expect(["No such file or directory", pexpect.TIMEOUT], timeout=2) == 1:
            self.expect(self.prompt)
            self.sendline("cat /root/aftr/aftr.conf")
            self.expect(self.prompt)
            run_conf = [
                i.strip() for i in self.before.split("\n")[1:] if i.strip() != ""
            ]
            self.sendline("\n")
        self.expect(self.prompt)

        run_script = None
        # check if aftr-script already exists
        self.sendline("ls /root/aftr/aftr-script")
        if self.expect(["No such file or directory", pexpect.TIMEOUT], timeout=2) == 1:
            self.expect(self.prompt)
            self.sendline("cat /root/aftr/aftr-script")
            self.expect(self.prompt)
            run_script = [
                i.strip() for i in self.before.split("\n")[1:] if i.strip() != ""
            ]
            self.sendline("\n")
        self.expect(self.prompt)

        # if contents are same just restart the service.
        # will be useful in case we go with one aftr for a location.
        if Counter(
            [i.strip() for i in start_conf.split("\n") if i.strip() != ""]
        ) != Counter(run_conf):
            to_send = f"cat > /root/aftr/aftr.conf << EOF\n{start_conf}\nEOF"
            self.sendline(to_send)
            self.expect(self.prompt)

        # the replace is pretty static here, will figure out something later.
        if Counter(
            [
                i.strip().replace(r"\$", "$").replace(r"\`", "`")
                for i in start_script.split("\n")
                if i.strip() != ""
            ]
        ) != Counter(run_script):
            to_send = f"cat > /root/aftr/aftr-script << EOF\n{start_script}\nEOF"
            self.sendline(to_send)
            self.expect(self.prompt)
            self.sendline("chmod +x /root/aftr/aftr-script")
            self.expect(self.prompt)

        # this part could be under a flagged condition.
        # forcing a reset since service is per board.
        self.sendline("killall aftr")
        self.expect(self.prompt)
        self.sendline(
            "/root/aftr/aftr -c /root/aftr/aftr.conf -s /root/aftr/aftr-script"
        )
        self.expect(self.prompt)

        self.expect(pexpect.TIMEOUT, timeout=2)
        assert (
            str(self.get_interface_ipaddr("tun0")) == "192.0.0.1"
        ), "Failed to bring up tun0 interface."

    def generate_aftr_conf(self):
        """To generate aftr.conf file.

        Refers conf/aftr.conf template inside ds-lite package.

        :return : aftr conf file
        :rtype : multiline string
        """
        run_conf = []

        # section 0 defines global parameters for NAT, PCP and tunnel.
        # If not specified, aftr script will consider it's default values.
        self.aftr_conf["section 0: global parameters"] = OrderedDict(
            [
                ("defmtu ", self.mtu),
                ("defmss ", "on"),
                # don't throw error if IPv4 packet is too big to fit in one IPv6 encapsulating packet
                ("deftoobig ", "off"),
            ]
        )

        # section 1 defines required parameters.
        # providing minimum requirement to bring up aftr tunnel.
        self.aftr_conf["section 1: required parameters"] = OrderedDict(
            [
                ("address endpoint ", str(self.ipv6_ep.ip)),
                ("address icmp ", self.ipv4_nat_ip),
                (f"pool {self.ipv4_nat_ip} tcp ", self.ipv4_nat_pool),
                (f"pool {self.ipv4_nat_ip} udp ", self.ipv4_nat_pool),
                (f"pcp {self.ipv4_nat_ip} tcp ", self.ipv4_pcp_pool),
                (f"pcp {self.ipv4_nat_ip} udp ", self.ipv4_pcp_pool),
                (
                    "#All IPv6 ACLs\n",
                    "\n".join(map(lambda x: f"acl6 {x}", self.ipv6_acl)),
                ),
            ]
        )

        for k, v in self.aftr_conf.items():
            run_conf.append(f"## {k}\n")
            for option, value in v.items():
                run_conf.append(f"{option}{value}")
            run_conf[-1] += "\n"

        return "\n".join(run_conf)

    def generate_aftr_script(self):
        """To generate aftr-httpserverscript.

        Refers conf/aftr-script.linux template inside ds-lite package.

        :return : aftr script
        :rtype : multiline string
        """
        tab = "    "

        script = "#!/bin/sh\n\n"
        run_conf = OrderedDict()

        # added a few sysctls to get it working inside a container.
        run_conf["aftr_start()"] = "\n".join(
            map(
                lambda x: f"{tab}{x}",
                [
                    "ip link set tun0 up",
                    "sysctl -w net.ipv4.ip_forward=1",
                    "sysctl -w net.ipv6.conf.all.forwarding=1",
                    "sysctl -w net.ipv6.conf.all.disable_ipv6=0",
                    "ip addr add 192.0.0.1 peer 192.0.0.2 dev tun0",
                    f"ip route add {str(self.ipv4_nat.network)} dev tun0",
                    f"ip -6 route add {str(self.ipv6_ep.network)} dev tun0",
                    "iptables -t nat -F",
                    r"iptables -t nat -A POSTROUTING -s %s -j SNAT --to-source \$PUBLIC"
                    % self.ipv4_nat_ip,
                    r"iptables -t nat -A PREROUTING -p tcp -d \$PUBLIC --dport %s -j DNAT --to-destination %s"
                    % (self.ipv4_pcp_pool.replace("-", ":"), self.ipv4_nat_ip),
                    r"iptables -t nat -A PREROUTING -p udp -d \$PUBLIC --dport %s -j DNAT --to-destination %s"
                    % (self.ipv4_pcp_pool.replace("-", ":"), self.ipv4_nat_ip),
                    r"iptables -t nat -A OUTPUT -p tcp -d \$PUBLIC --dport %s -j DNAT --to-destination %s"
                    % (self.ipv4_pcp_pool.replace("-", ":"), self.ipv4_nat_ip),
                    r"iptables -t nat -A OUTPUT -p udp -d \$PUBLIC --dport %s -j DNAT --to-destination %s"
                    % (self.ipv4_pcp_pool.replace("-", ":"), self.ipv4_nat_ip),
                ],
            )
        )

        run_conf["aftr_stop()"] = "\n".join(
            map(
                lambda x: f"{tab}{x}",
                ["iptables -t nat -F", "ip link set tun0 down"],
            )
        )

        extra_bits = "\n".join(
            [
                "set -x",
                r"PUBLIC=\`ip addr show dev %s | grep -w inet | awk '{print \$2}' | awk -F/ '{print \$1}'\`"
                % self.iface_dut,
                "\n" + r'case "\$1" in',
                "start)",
                f"{tab}aftr_start",
                f"{tab};;",
                "stop)",
                f"{tab}aftr_stop",
                f"{tab};;",
                "*)",
                r'%secho "Usage: \$0 start|stop"' % tab,
                f"{tab}exit 1",
                f"{tab};;",
                "esac\n",
                "exit 0",
            ]
        )

        # there could be a better way to generate this shell script.
        script += "{}\n{}".format(
            "\n".join([f"{k}\n{{\n{v}\n}}" for k, v in run_conf.items()]),
            extra_bits,
        )
        return script

    def install_aftr(self):
        """To check the aftr installation.

        :raise Exception : installation fails , throws exception
        """
        # check for aftr executable
        attempt = 0
        while attempt < 2:
            self.sendline("ls /root/aftr/aftr")
            if (
                self.expect(["No such file or directory", pexpect.TIMEOUT], timeout=2)
                == 0
            ):
                self.expect(self.prompt)
                apt_install(self, "build-essential")
                # check for configure script.
                self.sendline("ls /root/aftr/configure")
                if (
                    self.expect(
                        ["No such file or directory", pexpect.TIMEOUT], timeout=2
                    )
                    == 0
                ):
                    self.expect(self.prompt)
                    # need to download the tar file and extract it.
                    install_wget(self)
                    self.aftr_url = (
                        self.aftr_local
                        if self.aftr_local is not None
                        else self.aftr_url
                    )
                    self.sendline(f"mgmt curl {self.aftr_url} -o /root/aftr.tbz")
                    self.expect(self.prompt, timeout=60)
                    self.sendline(
                        "tar -C /root -xvjf /root/aftr.tbz; mv /root/rt28354 /root/aftr"
                    )
                self.expect(self.prompt, timeout=30)
                self.sendline("cd /root/aftr")
                self.expect(self.prompt)
                self.sendline("./configure")
                self.expect(self.prompt, timeout=30)
                self.sendline("make; cd")
                self.expect(self.prompt, timeout=30)
                attempt += 1
            else:
                self.is_installed = True
                self.expect(self.prompt)
                break

        if not self.is_installed:
            raise Exception("failed to install AFTR.")

    def enable_aftr(self):
        """To enable aftr."""
        pass

    def disable_aftr(self):
        """To disable aftr."""
        pass


if __name__ == "__main__":
    # Example use
    try:
        ipaddr, port = sys.argv[1].split(":")
    except Exception:
        raise Exception("First argument should be in form of ipaddr:port")

    # for getting lib.common from tests working
    sys.path.append(os.getcwd() + "/../")
    sys.path.append(os.getcwd() + "/../tests")

    # get a base class to work with AFTR profile class.
    from boardfarm.devices.debian import DebianBox as BaseCls

    class BfNode(BaseCls, AFTR):
        """Base class to work with AFTR profile class."""

        def __init__(self, *args, **kwargs):
            """Instance initialization."""
            BaseCls.__init__(self, *args, **kwargs)
            AFTR.__init__(self, *args, **kwargs)

    dev = BfNode(
        ipaddr=ipaddr,
        color="blue",
        username="root",
        password="bigfoot1",
        port=port,
        options="tftpd-server, wan-static-ip:10.64.38.23/23, wan-no-eth0, wan-static-ipv6:2001:730:1f:60a::cafe:23, static-route:0.0.0.0/0-10.64.38.2",
    )

    dev.configure("wan_device")
    dev.profile["on_boot"]()
