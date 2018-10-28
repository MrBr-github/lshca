#!/usr/bin/env python2

# Description: This utility comes to provide bird's-eye view of HCAs installed.
#              It's mainly intended for system administrators, thus defaults configured accordingly.
# Author: Michael Braverman
# Email: mrbr.mail@gmail.com
# Project repo: https://gitlab.com/MrBr-gitlab/lshca/
# License: This utility provided under GNU GPLv3 license

import os
import pickle
import re
import StringIO
import subprocess
import sys
import tarfile
import time
import json


class Config(object):
    def __init__(self):
        self.debug = False

        self.output_view = "system"
        self.output_order_general = {
                    "system": ["Dev#", "Desc", "PN", "SN", "FW", "PCI_addr", "RDMA", "Net", "Port", "Numa", "State",
                               "Link", "Rate", "SRIOV", "Parent_addr", "LnkCapWidth", "LnkStaWidth", "HCA_Type"],
                    "ib": ["Dev#", "Desc", "PN", "SN", "FW", "RDMA", "Port", "Net", "Numa", "State", "PLid", "PGuid",
                           "IbNetPref"]
        }
        self.output_order = self.output_order_general[self.output_view]

        self.record_data_for_debug = False
        self.record_dir = "/tmp/lshca"
        self.record_tar_file = None

        self.ver = "2.5"

        self.mst_device_enabled = False
        self.output_format = "human_readable"

    def set_output_order(self, output_order):
        decrement_list = self.output_order
        increment_list = []

        output_order_list = output_order.split(',')
        for item in output_order_list:
            if re.match(r"^-.+", item):
                item = item[1:]
                if item in self.output_order:
                    decrement_list.remove(item)
            else:
                increment_list.append(item)

        if len(increment_list) > 0:
            self.output_order = increment_list
        else:
            self.output_order = decrement_list


class HCAManager(object):
    def __init__(self, data_source):
        mlnx_bdf_list = []
        # Same lspci cmd used in MST source in order to benefit from cache
        raw_mlnx_bdf_list = data_source.exec_shell_cmd("lspci -Dd 15b3:", use_cache=True)
        for member in raw_mlnx_bdf_list:
            bdf = extract_string_by_regex(member, "(.+) (Ethernet|Infini[Bb]and|Network)")

            if bdf != "=N/A=":
                mlnx_bdf_list.append(bdf)

        mlnx_bdf_devices = []
        for bdf in mlnx_bdf_list:
            port_count = 1

            while True:
                bdf_dev = MlnxBFDDevice(bdf, data_source, port_count)
                mlnx_bdf_devices.append(bdf_dev)

                if port_count >= len(bdf_dev.get_port_list()):
                    break

                port_count += 1

        self.mlnxHCAs = []
        # First handle all PFs
        for bdf_dev in mlnx_bdf_devices:
            if bdf_dev.get_sriov() in ("PF", "PF*"):
                hca_found = False
                for hca in self.mlnxHCAs:
                    if bdf_dev.get_sn() == hca.get_sn():
                        hca_found = True
                        hca.add_bdf_dev(bdf_dev)

                if not hca_found:
                    hca = MlnxHCA(bdf_dev)
                    hca.set_hca_index(len(self.mlnxHCAs) + 1)
                    self.mlnxHCAs.append(hca)

        # Now handle all VFs
        for bdf_dev in mlnx_bdf_devices:
            if bdf_dev.get_sriov() == 'VF':
                vf_parent_bdf = bdf_dev.get_vf_parent()

                # TBD: refactor to function
                for parent_bdf_dev in mlnx_bdf_devices:
                    parent_found = False
                    if vf_parent_bdf == parent_bdf_dev.get_bdf():
                        parent_found = True

                        hca = self.get_hca_by_sn(parent_bdf_dev.get_sn())
                        if hca is not None:
                            hca.add_bdf_dev(bdf_dev)
                        else:
                            raise Exception("VF " + str(bdf_dev) + " This device has no parent PF")

                    if parent_found:
                        break

    def display_hcas_info(self):
        out = Output()
        for hca in self.mlnxHCAs:
            output_info = hca.output_info()
            out.append(output_info)

        out.print_output()

    def get_hca_by_sn(self, sn):
        for hca in self.mlnxHCAs:
            if sn == hca.get_sn():
                return hca
        return None


class Output(object):
    def __init__(self):
        self.output = []
        self.column_width = {}
        self.separator_len = 0

    def append(self, data):
        self.output.append(data)

    def print_output(self):
        if config.output_format == "human_readable":
            hca_info_line_width = 0

            for output_key in self.output:
                for data in output_key["bdf_devices"]:
                    for key in data:
                        if key in config.output_order:
                            if len(data[key]) > len(key):
                                width = len(data[key])
                            else:
                                width = len(key)

                            if key not in self.column_width or len(data[key]) > self.column_width[key]:
                                self.column_width[key] = width
                for key in output_key["hca_info"]:
                    current_width = len(key) + len(str(output_key["hca_info"][key])) + 5
                    if hca_info_line_width < current_width:
                        hca_info_line_width = current_width

            bdf_device_line_width = sum(self.column_width.values()) + len(self.column_width)*3 - 2

            if bdf_device_line_width > hca_info_line_width:
                self.separator_len = bdf_device_line_width
            else:
                self.separator_len = hca_info_line_width

            for output_key in self.output:
                self.print_hca_info(output_key["hca_info"])
                self.print_bdf_devices(output_key["bdf_devices"])
        elif config.output_format == "json":
            print json.dumps(self.output, indent=4, sort_keys=True)

    def print_hca_info(self, args):
        order_dict = {}

        position = 0
        for key in config.output_order:
            if key in args:
                order_dict[key] = position
                position += 1

        output_list = [""] * len(order_dict)
        for key in args:
            if key in order_dict:
                output_list = output_list[0:order_dict[key]] + \
                              ["- " + str(key) + ": " + str(args[key])] + \
                              output_list[order_dict[key] + 1:]

        separator = "-" * self.separator_len
        print separator
        print '\n'.join(output_list)
        print separator

    def print_bdf_devices(self, args):
        count = 1
        order_dict = {}

        position = 0
        for key in config.output_order:
            if key in args[0]:
                order_dict[key] = position
                position += 1

        for line in args:
            output_list = [""] * len(order_dict)
            if count == 1:
                for key in line:
                    if key in order_dict:
                        output_list = output_list[0:order_dict[key]] + \
                                      [str("{0:^{width}}".format(key, width=self.column_width[key]))] + \
                                      output_list[order_dict[key] + 1:]
                print ' | '.join(output_list)
                print "-" * self.separator_len

            for key in line:
                if key in order_dict:
                    output_list = output_list[0:order_dict[key]] + \
                                   [str("{0:^{width}}".format(line[key], width=self.column_width[key]))] + \
                                   output_list[order_dict[key] + 1:]

            count += 1
            print ' | '.join(output_list)


class MSTDevice(object):
    def __init__(self, bdf, data_source):
        self.bdf = bdf
        self.mst_device = ""
        self.mst_raw_data = "No MST data"
        self.bdf_short_format = True
        mst_init_running = False

        if config.mst_device_enabled:
            if "MST_device" not in config.output_order:
                config.output_order.append("MST_device")

            result = data_source.exec_shell_cmd("which mst &> /dev/null ; echo $?", use_cache=True)
            if result == ["0"]:
                mst_installed = True
            else:
                mst_installed = False

            if mst_installed:
                result = data_source.exec_shell_cmd("mst status | grep -c 'MST PCI configuration module loaded'",
                                                    use_cache=True)
                if result != ["0"]:
                    mst_init_running = True

                if not mst_init_running:
                    data_source.exec_shell_cmd("mst start", use_cache=True)

                self.mst_raw_data = data_source.exec_shell_cmd("mst status -v", use_cache=True)
                self.got_raw_data = True

                if not mst_init_running:
                    data_source.exec_shell_cmd("mst stop", use_cache=True)

                # Same lspci cmd used in HCAManager in order to benefit from cache
                lspci_raw_data = data_source.exec_shell_cmd("lspci -Dd 15b3:", use_cache=True)
                for line in lspci_raw_data:
                    pci_domain = extract_string_by_regex(line, "([0-9]{4}):.*")
                    if pci_domain != "0000":
                        self.bdf_short_format = False

                if self.bdf_short_format:
                    self.bdf = extract_string_by_regex(self.bdf, "[0-9]{4}:(.*)")

                for line in self.mst_raw_data:
                    data_line = extract_string_by_regex(line, "(.*" + self.bdf + ".*)")
                    if data_line != "=N/A=":
                        mst_device = extract_string_by_regex(data_line, ".* (/dev/mst/[^\s]+) .*")
                        self.mst_device = mst_device

    def __repr__(self):
        return self.mst_raw_data

    def get_mst_device(self):
        return self.mst_device


class PCIDevice(object):
    def __init__(self, bdf, data_source):
        self.bdf = bdf
        self.bdWithoutF = self.bdf.split(".", 1)[0]
        self.data = data_source.exec_shell_cmd("lspci -vvvD -s" + bdf, use_cache=True)
        # Handling following string, taking reset of string after HCA type
        # 0000:01:00.0 Infiniband controller: Mellanox Technologies MT27700 Family [ConnectX-4]
        self.description = self.get_info_from_lspci_data("^[0-9].*", str(self.bdf) + ".*:(.+)")
        self.sn = self.get_info_from_lspci_data("\[SN\].*", ".*:(.+)")
        self.pn = self.get_info_from_lspci_data("\[PN\].*", ".*:(.+)")
        self.lnkCapWidth = self.get_info_from_lspci_data("LnkCap:.*Width.*", ".*Width (x[0-9]+)")
        self.lnkStaWidth = self.get_info_from_lspci_data("LnkSta:.*Width.*", ".*Width (x[0-9]+)")
        self.pciGen = self.get_info_from_lspci_data(".*[Pp][Cc][Ii][Ee] *[Gg][Ee][Nn].*",
                                                    ".*[Pp][Cc][Ii][Ee] *[Gg][Ee][Nn]([0-9]) +")

        if self.lnkCapWidth != self.lnkStaWidth:
            self.lnkStaWidth = str(self.lnkStaWidth) + " <- !"

        self.lnkCapWidth = str(self.lnkCapWidth) + " G" + str(self.pciGen)

    def __repr__(self):
        delim = " "
        return "PCI device:" + delim +\
               self.get_bdf() + delim + \
               self.get_sn() + delim + \
               self.get_pn() + delim +\
               "\"" + self.description + "\""

    def get_bdf(self):
        return self.bdf

    def get_sn(self):
        return self.sn

    def get_pn(self):
        return self.pn

    def get_description(self):
        return self.description

    def get_lnk_cap_width(self):
        return self.lnkCapWidth

    def get_lnk_sta_width(self):
        return self.lnkStaWidth

    def get_info_from_lspci_data(self, search_regex, output_regex):
        search_result = find_in_list(self.data, search_regex)
        search_result = extract_string_by_regex(search_result, output_regex)
        return str(search_result).strip()


class SYSFSDevice(object):
    def __init__(self, bdf, data_source, port=1):
        self.bdf = bdf
        self.port = port

        sys_prefix = "/sys/bus/pci/devices/" + self.bdf

        vf_parent_file = data_source.read_link_if_exists(sys_prefix + "/physfn")
        if vf_parent_file is not "":
            self.sriov = "VF"
            self.vfParent = extract_string_by_regex(vf_parent_file, ".*\/([0-9].*)")
        else:
            self.sriov = "PF"
            self.vfParent = "-"

        self.numa = data_source.read_file_if_exists(sys_prefix + "/numa_node").rstrip()
        if not self.numa:
            print >> sys.stderr, "Warning: " + self.bdf + " has no NUMA assignment"

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

            if net_port == self.port:
                self.net = net
                break

        self.hca_type = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma + "/hca_type").rstrip()

        self.state = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma + "/ports/" +
                                                     str(self.port) + "/state")
        self.state = extract_string_by_regex(self.state, "[0-9:]+ (.*)", "").lower()
        if self.state == "active":
            self.state = "actv"

        self.phys_state = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma +
                                                          "/ports/" + str(self.port) + "/phys_state")
        self.phys_state = extract_string_by_regex(self.phys_state, "[0-9:]+ (.*)", "").lower()

        self.link_layer = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma +
                                                          "/ports/" + str(self.port) + "/link_layer")
        self.link_layer = self.link_layer.rstrip()
        if self.link_layer == "InfiniBand":
            self.link_layer = "IB"
        elif self.link_layer == "Ethernet":
            self.link_layer = "Eth"

        self.fw = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma + "/fw_ver")
        self.fw = self.fw.rstrip()

        self.port_rate = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma + "/ports/" +
                                                         str(self.port) + "/rate")
        self.port_rate = extract_string_by_regex(self.port_rate, "([0-9]*) .*", "")
        if self.state == "down":
            self.port_rate = self.port_rate + "*"

        self.port_list = data_source.list_dir_if_exists(sys_prefix + "/infiniband/" + self.rdma + "/ports/").rstrip()
        self.port_list = self.port_list.split(" ")

        self.plid = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma +
                                                    "/ports/" + str(self.port) + "/lid")
        self.plid = str(int(self.plid, 16))

        full_guid = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma +
                                                    "/ports/" + str(self.port) + "/gids/0")

        self.pguid = extract_string_by_regex(full_guid, "((:[A-Fa-f0-9]{4}){4})$", "").lower()
        self.pguid = re.sub(':', '', self.pguid)

        self.ib_net_prefix = extract_string_by_regex(full_guid, "^(([A-Fa-f0-9]{4}:){4})", "").lower()
        self.ib_net_prefix = re.sub(':', '', self.ib_net_prefix)

    def __repr__(self):
        delim = " "
        return "SYS device:" + delim +\
               self.get_bdf() + delim + \
               self.get_sriov() + delim + \
               self.get_vf_parent() + delim + \
               self.get_numa()

    def get_bdf(self):
        return self.bdf

    def get_sriov(self):
        return self.sriov

    def get_vf_parent(self):
        return self.vfParent

    def get_numa(self):
        return self.numa

    def get_rdma(self):
        return self.rdma

    def get_net(self):
        return self.net

    def get_hca_type(self):
        return self.hca_type

    def get_state(self):
        return self.state

    def get_phys_state(self):
        return self.phys_state

    def get_link_layer(self):
        return self.link_layer

    def get_fw(self):
        return self.fw

    def get_port_rate(self):
        return self.port_rate

    def get_port_list(self):
        return self.port_list

    def get_port(self):
        return str(self.port)

    def get_plid(self):
        return self.plid

    def get_pguid(self):
        return self.pguid

    def get_ib_net_prefix(self):
        return self.ib_net_prefix


class MlnxBFDDevice(object):
    def __init__(self, bdf, data_source, port=1):
        self.bdf = bdf
        self.sysFSDevice = SYSFSDevice(self.bdf, data_source, port)
        self.pciDevice = PCIDevice(self.bdf, data_source)
        self.mstDevice = MSTDevice(self.bdf, data_source)
        self.slaveBDFDevices = []

    def __repr__(self):
        return self.sysFSDevice.__repr__() + "\n" + self.pciDevice.__repr__() + "\n" + \
                self.mstDevice.__repr__() + "\n"

    def add_slave_bdf_device(self, slave_bdf_device):
        self.slaveBDFDevices.append(slave_bdf_device)

    def get_slave_bdf_devices(self):
        return self.slaveBDFDevices

    def get_bdf(self):
        return self.bdf

    def get_sn(self):
        return self.pciDevice.get_sn()

    def get_pn(self):
        return self.pciDevice.get_pn()

    def get_description(self):
        return self.pciDevice.get_description()

    def get_lnk_cap_width(self):
        return self.pciDevice.get_lnk_cap_width()

    def get_lnk_sta_width(self):
        return self.pciDevice.get_lnk_sta_width()

    def get_sriov(self):
        if self.sysFSDevice.get_sriov() == "PF" and \
                re.match(r".*[Vv]irtual [Ff]unction.*", self.pciDevice.get_description()):
            return self.sysFSDevice.get_sriov() + "*"
        else:
            return self.sysFSDevice.get_sriov()

    def get_vf_parent(self):
        return self.sysFSDevice.vfParent

    def get_numa(self):
        return self.sysFSDevice.get_numa()

    def get_rdma(self):
        return self.sysFSDevice.get_rdma()

    def get_net(self):
        return self.sysFSDevice.get_net()

    def get_hca_type(self):
        return self.sysFSDevice.get_hca_type()

    def get_state(self):
        return self.sysFSDevice.get_state()

    def get_phys_state(self):
        return self.sysFSDevice.get_phys_state()

    def get_link_layer(self):
        return self.sysFSDevice.get_link_layer()

    def get_fw(self):
        return self.sysFSDevice.get_fw()

    def get_port_rate(self):
        return self.sysFSDevice.get_port_rate()

    def get_port_list(self):
        return self.sysFSDevice.get_port_list()

    def get_port(self):
        return self.sysFSDevice.get_port()

    def get_plid(self):
        return self.sysFSDevice.get_plid()

    def get_pguid(self):
        return self.sysFSDevice.get_pguid()

    def get_ib_net_prefix(self):
        return self.sysFSDevice.get_ib_net_prefix()

    def get_mst_dev(self):
        return self.mstDevice.get_mst_device()

    def output_info(self):
        if self.get_sriov() in ("PF", "PF*"):
            sriov = self.get_sriov() + "  "
        else:
            sriov = "  " + self.get_sriov()
        output = {"SRIOV": sriov,
                  "Numa": self.get_numa(),
                  "PCI_addr": self.get_bdf(),
                  "Parent_addr": self.get_vf_parent(),
                  "RDMA": self.get_rdma(),
                  "Net": self.get_net(),
                  "HCA_Type": self.get_hca_type(),
                  "State": self.get_state(),
                  "Rate": self.get_port_rate(),
                  "Port": self.get_port(),
                  "Link": self.get_link_layer(),
                  "MST_device": self.get_mst_dev(),
                  "LnkCapWidth": self.get_lnk_cap_width(),
                  "LnkStaWidth": self.get_lnk_sta_width(),
                  "PLid": self.get_plid(),
                  "PGuid": self.get_pguid(),
                  "IbNetPref": self.get_ib_net_prefix()}
        return output


class MlnxHCA(object):
    def __init__(self, bfd_dev):
        self.bfd_devices = []

        if bfd_dev.get_sriov() in ("PF", "PF*"):
            self.bfd_devices.append(bfd_dev)
        else:
            raise ValueError("MlnxHCA object can be initialised ONLY with PF bfdDev")

        self.sn = bfd_dev.get_sn()
        self.pn = bfd_dev.get_pn()
        self.fw = bfd_dev.get_fw()
        self.hca_index = None

    def __repr__(self):
        output = ""
        for bfd_dev in self.bfd_devices:
            output = output + str(bfd_dev)
        return output

    def set_hca_index(self, index):
        self.hca_index = index

    def add_bdf_dev(self, new_bfd_dev):
        if new_bfd_dev.get_sriov() == "VF" and new_bfd_dev.get_vf_parent() != "-":
            for i, bfd_dev in enumerate(self.bfd_devices):
                if bfd_dev.get_bdf() == new_bfd_dev.get_vf_parent():
                    self.bfd_devices.insert(i+1, new_bfd_dev)
        else:
            self.bfd_devices.append(new_bfd_dev)

    def get_sn(self):
        return self.sn

    def get_pn(self):
        return self.pn

    def get_fw(self):
        return self.fw

    def get_description(self):
        return self.bfd_devices[0].get_description()

    def get_hca_index(self):
        return self.hca_index

    def output_info(self):
        output = {"hca_info": {"SN": self.get_sn(),
                               "PN": self.get_pn(),
                               "FW": self.get_fw(),
                               "Desc": self.get_description(),
                               "Dev#": self.get_hca_index()},
                  "bdf_devices": []}
        for bdf_dev in self.bfd_devices:
            output["bdf_devices"].append(bdf_dev.output_info())
        return output


class DataSource(object):
    def __init__(self):
        self.cache = {}
        if config.record_data_for_debug is True:
            if not os.path.exists(config.record_dir):
                os.makedirs(config.record_dir)

            config.record_tar_file = config.record_dir + "/" + os.uname()[1] + "--" + str(time.time()) + ".tar"

            print "\nlshca started data recording"
            print "output saved in " + config.record_tar_file + " file\n\n"

    def exec_shell_cmd(self, cmd, use_cache=False):
        cache_key = self.cmd_to_str(cmd)

        if use_cache is True and cache_key in self.cache:
            output = self.cache[cache_key]

        else:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
            output, error = process.communicate()
            if use_cache is True:
                self.cache.update({cache_key: output})

        output = output.splitlines()
        if config.record_data_for_debug is True:
            self.record_data(cmd, output)

        return output

    def record_data(self, cmd, output):
        p_output = pickle.dumps(output)
        file_name = self.cmd_to_str(cmd)

        tarinfo = tarfile.TarInfo(file_name)
        tarinfo.size = len(p_output)
        tarinfo.mtime = time.time()

        tar = tarfile.open(name=config.record_tar_file, mode='a')
        tar.addfile(tarinfo, StringIO.StringIO(p_output))
        tar.close()

    def read_file_if_exists(self, file_to_read):
        if os.path.exists(file_to_read):
            f = open(file_to_read, "r")
            output = f.read()
            f.close()
        else:
            output = ""

        if config.record_data_for_debug is True:
            cmd = "os.path.exists" + file_to_read
            self.record_data(cmd, output)

        return output

    def read_link_if_exists(self, link_to_read):
        try:
            output = os.readlink(link_to_read)
        except OSError as exception:
            # if OSError: [Errno 2] No such file or directory
            if exception.errno == 2:
                output = ""
            else:
                raise exception

        if config.record_data_for_debug is True:
            cmd = "os.readlink" + link_to_read
            self.record_data(cmd, output)

        return output

    def list_dir_if_exists(self, dir_to_list):
        try:
            output = os.listdir(dir_to_list)
            output = " ".join(output)
        except OSError as exception:
            # if OSError: [Errno 2] No such file or directory
            if exception.errno == 2:
                output = ""
            else:
                raise exception

        if config.record_data_for_debug is True:
            cmd = "os.listdir" + dir_to_list
            self.record_data(cmd, output)

        return output

    @staticmethod
    def cmd_to_str(cmd):
        output = re.escape(cmd)
        return output


def extract_string_by_regex(data_string, regex, na_string="=N/A="):
    # The following will print first GROUP in the regex, thus grouping should be used
    try:
        search_result = re.search(regex, data_string).group(1)
    except AttributeError:
        search_result = na_string

    return search_result


def find_in_list(list_to_search_in, regex_pattern):
    # TBD : refactor to more human readable
    regex = re.compile(regex_pattern)
    result = [m.group(0) for l in list_to_search_in for m in [regex.search(l)] if m]

    if result:
        return result[0]
    else:
        return ""


def parse_arguments():
    user_args = sys.argv[1:]

    index = 0
    while index < len(user_args):
        if user_args[index] == "-h" or user_args[index] == "--help":
            usage()
        elif user_args[index] == "-m":
            index += 1
            if index > len(user_args):
                print "\n-m requires parameter\n"
                usage()

            if user_args[index] == "normal":
                pass
            elif user_args[index] == "record":
                config.record_data_for_debug = True
            else:
                print "\n" + user_args[index] + " - Unknown parameter for -m\n"
                usage()
        elif user_args[index] == "-v":
            print "lshca ver. " + config.ver
            sys.exit()
        elif user_args[index] == "-d":
            config.debug = True
        elif user_args[index] == "-w":
            index += 1
            if index > len(user_args):
                print "\n-w requires parameter\n"
                usage()

            if user_args[index] == "ib":
                config.output_order = config.output_order_general["ib"]
            elif user_args[index] == "system":
                config.output_order = config.output_order_general["system"]
            else:
                print "\n" + user_args[index] + " - Unknown parameter for -w\n"
                usage()
        elif user_args[index] == "-j":
            config.output_format = "json"
        elif user_args[index] == "-s":
            index += 1
            if index > len(user_args):
                print "\n-s requires parameter\n"
                usage()

            if user_args[index] == "mst":
                config.mst_device_enabled = True
            else:
                print "\n" + user_args[index] + " - Unknown parameter for -s\n"
                usage()
        elif user_args[index] == "-o":
            index += 1
            if index > len(user_args):
                print "\n-o requires parameter\n"
                usage()
            else:
                config.set_output_order(user_args[index])
        else:
            print "\n" + user_args[index] + " - Unknown parameter\n"
            usage()

        index += 1


def usage():
    print "Usage: lshca [-hdvj] [-m <mode>] [-s <data source>]"
    print "-h, --help"
    print "  Show this help"
    print "-d"
    print "  run with debug outputs"
    print "-m <mode>"
    print "  Mode of operation"
    print "    normal - (default) list HCAs"
    print "    record - record all data for debug and lists HCAs"
    print "-s <mst>"
    print "  Add optional data sources."
    print "  Always on data sources are:"
    print "    sysfs, lspci"
    print "  Optional data sources:"
    print "    mst - provides MST based info. This data source slows execution"
    print "-v"
    print "  show version"
    print ""
    print "Output options:"
    print "-w"
    print "  Show output view. Views are"
    print "    system - (default). Show system oriented HCA info"
    print "    ib     - Show IB oriented HCA info "
    print "-j"
    print "  Output data as JSON, not affected by output selection flag"
    print "-o"
    print "  Select fields to output. Comma delimited list. Use field names as they appear in output"
    print "  Adding \"-\" to field name will remove it from default selections"
    print ""
    print ""
    print "Examples:"
    print "    lshca -j -s mst -o \"-SN\""
    print "    lshca -o \"Dev#,Port,Net,PN,Desc\""
    print ""
    sys.exit()


config = Config()


def main():
    if os.geteuid() != 0:
        exit("You need to have root privileges to run this script")

    parse_arguments()

    data_source = DataSource()

    hca_manager = HCAManager(data_source)

    hca_manager.display_hcas_info()


if __name__ == "__main__":
    main()
