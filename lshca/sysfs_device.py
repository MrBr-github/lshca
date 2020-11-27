# Description: Part of lshca library
#
# Author: Michael Braverman
# Project repo: https://github.com/MrBr-github/lshca
# License: This utility provided under GNU GPLv3 license

from __future__ import print_function
import re
import sys
import os

import service_function


class SYSFSDevice(object):
    def __init__(self, bdf, data_source, config, port=1):
        self.bdf = bdf
        self.port = str(port)
        self.config = config

        sys_prefix = "/sys/bus/pci/devices/" + self.bdf

        vf_parent_file = data_source.read_link_if_exists(sys_prefix + "/physfn")
        if vf_parent_file is not "":
            self.sriov = "VF"
            self.vfParent = service_function.extract_string_by_regex(vf_parent_file, ".*\/([0-9].*)")
        else:
            self.sriov = "PF"
            self.vfParent = "-"

        self.numa = data_source.read_file_if_exists(sys_prefix + "/numa_node").rstrip()
        if not self.numa:
            print("Warning: %s has no NUMA assignment" % self.bdf, file=sys.stderr)

        self.rdma = data_source.list_dir_if_exists(sys_prefix + "/infiniband/").rstrip()
        net_list = data_source.list_dir_if_exists(sys_prefix + "/net/")

        self.net = ""
        for net in net_list.split(" "):
            # the below code tries to identify which of the files has valid port number dev_id or dev_port
            # in mlx4 dev_port has the valid value, in mlx5 - dev_id
            # this solution mimics one in ibdev2netdev

            net_port_dev_id = data_source.read_file_if_exists(sys_prefix + "/net/" + net + "/dev_id")
            try:
                net_port_dev_id = int(net_port_dev_id, 16)
            except ValueError:
                net_port_dev_id = 0

            net_port_dev_port = data_source.read_file_if_exists(sys_prefix + "/net/" + net + "/dev_port")
            try:
                net_port_dev_port = int(net_port_dev_port)
            except ValueError:
                net_port_dev_port = 0

            if net_port_dev_id > net_port_dev_port:
                net_port = net_port_dev_id
            else:
                net_port = net_port_dev_port

            net_port += 1

            if str(net_port) == self.port:
                self.net = net
                break

        self.hca_type = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma + "/hca_type").rstrip()

        self.lnk_state = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma + "/ports/" +
                                                         self.port + "/state")
        self.lnk_state = service_function.extract_string_by_regex(self.lnk_state, "[0-9:]+ (.*)", "").lower()
        if self.lnk_state == "active":
            self.lnk_state = "actv"

        if self.lnk_state == "down":
            self.phys_state = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma +
                                                              "/ports/" + self.port + "/phys_state")
            self.phys_state = service_function.extract_string_by_regex(self.phys_state, "[0-9:]+ (.*)", "").lower()

            if self.phys_state == "polling":
                self.lnk_state = "poll"

        self.link_layer = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma +
                                                          "/ports/" + self.port + "/link_layer")
        self.link_layer = self.link_layer.rstrip()
        if self.link_layer == "InfiniBand":
            self.link_layer = "IB"
        elif self.link_layer == "Ethernet":
            self.link_layer = "Eth"

        self.fw = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma + "/fw_ver")
        self.fw = self.fw.rstrip()

        self.psid = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma + "/board_id")
        self.psid = self.psid.rstrip()

        self.port_rate = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma + "/ports/" +
                                                         self.port + "/rate")
        self.port_rate = service_function.extract_string_by_regex(self.port_rate, "([0-9]*) .*", "")
        if self.lnk_state == "down" and self.config.show_warnings_and_errors is True:
            self.port_rate = self.port_rate + self.config.warning_sign

        self.port_list = data_source.list_dir_if_exists(sys_prefix + "/infiniband/" + self.rdma + "/ports/").rstrip()
        self.port_list = self.port_list.split(" ")

        self.plid = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma +
                                                    "/ports/" + self.port + "/lid")
        try:
            self.plid = int(self.plid, 16)
        except ValueError:
            self.plid = ""
        self.plid = str(self.plid)

        self.smlid = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma +
                                                     "/ports/" + self.port + "/sm_lid")
        try:
            self.smlid = int(self.smlid, 16)
        except ValueError:
            self.smlid = ""
        self.smlid = str(self.smlid)

        full_guid = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma +
                                                    "/ports/" + self.port + "/gids/0")

        self.pguid = service_function.extract_string_by_regex(full_guid, "((:[A-Fa-f0-9]{4}){4})$", "").lower()
        self.pguid = re.sub(':', '', self.pguid)

        self.ib_net_prefix = service_function.extract_string_by_regex(full_guid, "^(([A-Fa-f0-9]{4}:){4})", "").lower()
        self.ib_net_prefix = re.sub(':', '', self.ib_net_prefix)

        self.has_smi = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma +
                                                       "/ports/" + self.port + "/has_smi")
        self.has_smi = self.has_smi.rstrip()
        if self.link_layer != "IB" or re.match('mlx4', self.rdma):
            self.virt_hca = "N/A"
        elif self.has_smi == "0":
            self.virt_hca = "Virt"
        elif self.has_smi == "1":
            self.virt_hca = "Phys"
        else:
            self.virt_hca = ""

        self.operstate = data_source.read_file_if_exists("/sys/class/net/" + self.net + "/operstate").rstrip()
        self.ip_state = None
        if self.operstate == "up":
            # Implemented via shell cmd to avoid using non default libraries
            interface_data = data_source.exec_shell_cmd(" ip address show dev %s" % self.net)
            ipv4_data = service_function.find_in_list(interface_data, "inet .+")
            ipv6_data = service_function.find_in_list(interface_data, "inet6 .+")
            if ipv4_data and ipv6_data:
                self.ip_state = "up_ip46"
            elif ipv4_data:
                self.ip_state = "up_ip4"
            elif ipv6_data:
                self.ip_state = "up_ip6"
            else:
                self.ip_state = "up_noip"
        elif not self.operstate:
            self.ip_state = ""
        else:
            self.ip_state = "down"

        if self.ip_state == "down" and self.lnk_state == "actv" \
                and self.config.show_warnings_and_errors is True:
            self.ip_state = self.ip_state + self.config.error_sign
        if self.ip_state == "up_noip" and self.config.show_warnings_and_errors is True:
            self.ip_state = self.ip_state + self.config.warning_sign

        self.sys_image_guid = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma +
                                                              "/sys_image_guid").rstrip()

        # ========== RoCE view only related variables ==========
        self.gtclass = None
        self.tcp_ecn = None
        self.rdma_cm_tos = None

        if self.config.query_preset[self.config.QPRESET_ROCE]:
            self.gtclass = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma +
                                                           "/tc/1/traffic_class").rstrip()
            self.tcp_ecn = data_source.read_file_if_exists("/proc/sys/net/ipv4/tcp_ecn").rstrip()

            roce_tos_path_prefix = "/sys/kernel/config/rdma_cm/" + self.rdma
            roce_tos_path_prefix_cleanup = False
            try:
                if not os.path.isdir(roce_tos_path_prefix):
                    os.mkdir(roce_tos_path_prefix)
                    roce_tos_path_prefix_cleanup = True
                self.rdma_cm_tos = data_source.read_file_if_exists(roce_tos_path_prefix +
                                                                   "/ports/1/default_roce_tos").rstrip()
                if roce_tos_path_prefix_cleanup:
                    os.rmdir(roce_tos_path_prefix)
            except OSError:
                self.rdma_cm_tos = "Failed to retrieve"

    def __repr__(self):
        delim = " "
        return "SYS device:" + delim + \
               self.bdf + delim + \
               self.sriov + delim + \
               self.vfParent + delim + \
               self.numa
