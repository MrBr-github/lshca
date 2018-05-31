#!/usr/bin/env python2

import os
import pickle
import re
import StringIO
import subprocess
import sys
import tarfile
import time

# TBD: Fix Issues
#
# 1. This script does not handles mlx4 devices well
#    there is no consideration for cases where can be ports beside ( self.rdma + "/ports/1" )
# - Dev#: 2
# - Desc: Mellanox Technologies MT27600 [Connect-IB]
# - PN: MCB194A-FCAT
# - SN: MT1228X05404
# - FW: 10.16.1200
# ---------------------------------------------------------------------------------------------
# Link | State |   PCI addr   |  RDMA  | Numa | Rate | Parent addr |   Net   | PfVf | HCA Type
# ---------------------------------------------------------------------------------------------
#  IB  | actv  | 0000:03:00.0 | mlx5_2 |  0   |  56  |      -      | ib2 ib3 | PF   |  MT4113
#
#
# 2. Failed to identify, or provide any output for CX2 HCA
# #lspci | grep -i mella
# 0a:00.0 InfiniBand: Mellanox Technologies MT26428 [ConnectX VPI PCIe 2.0 5GT/s - IB QDR / 10GigE] (rev a0)
# root@dev-r-vrt-088 ~
# #ofed_info -s
# MLNX_OFED_LINUX-4.4-0.0.3.0:
#
#


class Config(object):
    def __init__(self):
        self.debug = False
        self.record_data_for_debug = False
        self.record_dir = None
        self.record_tar_file = None

        self.ver = "0.1"


class HCAManager(object):
    def __init__(self, data_source):
        mlnx_bdf_list = []
        raw_mlnx_bdf_list = data_source.exec_shell_cmd("lspci -Dd 15b3:")
        for member in raw_mlnx_bdf_list:
            bdf = extract_string_by_regex(member, "(.+) (Ethernet|Infini[Bb]and)")

            if bdf != "=N/A=":
                mlnx_bdf_list.append(bdf)

        mlnx_bdf_devices = []
        for bdf in mlnx_bdf_list:
            bdf_dev = MlnxBFDDevice(bdf, data_source)
            mlnx_bdf_devices.append(bdf_dev)

        self.mlnxHCAs = []
        # First handle all PFs
        for bdf_dev in mlnx_bdf_devices:
            if bdf_dev.get_pfvf() == "PF":
                hca_found = False
                for hca in self.mlnxHCAs:
                    if bdf_dev.get_sn() == hca.get_sn():
                        hca_found = True
                        hca.add_bdf_dev(bdf_dev)

                if not hca_found:
                    hca = MlnxHCA(bdf_dev)
                    self.mlnxHCAs.append(hca)

        # Now handle all VFs
        for bdf_dev in mlnx_bdf_devices:
            if bdf_dev.get_pfvf() == 'VF':
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
        count = 1
        for hca in self.mlnxHCAs:
            output_info = hca.output_info()
            output_info["hca_info"]["Dev#"] = count

            output_info["sub_header"] = output_info["hca_info"]
            output_info["data"] = output_info["bdf_devices"]
            output_info["data"].insert(0, output_info["bdf_devices_headers"])

            out.append(output_info)
            count += 1

        out.print_output()

    def get_hca_by_sn(self, sn):
        for hca in self.mlnxHCAs:
            if sn == hca.get_sn():
                return hca
        return None


class Output(object):
    # TBD header separator width might change if first line are shorter then following one
    def __init__(self):
        self.output = []
        self.column_width = {}
        self.separator_len = 0

    def append(self, data):
        self.output.append(data)

    def print_output(self):
        for line in self.output:
            for data in line["data"]:
                for key in data:
                    if key not in self.column_width:
                        self.column_width[key] = len(data[key])
                    elif len(data[key]) > self.column_width[key]:
                        self.column_width[key] = len(data[key])

        self.separator_len = sum(self.column_width.values()) + len(self.column_width)*3 - 2

        for line in self.output:
            self.print_sub_header(line["sub_header"])
            self.print_data(line["data"])

    def print_sub_header(self, args):
        output = ""
        new_line = ""
        for key in args:
            output += new_line + "- " + str(key) + ": " + str(args[key])
            new_line = "\n"
        separator = "-" * self.separator_len
        print separator
        print output
        print separator

    def print_data(self, args):
        count = 1

        for line in args:
            output = ""
            separator = ""
            if count == 2:
                print "-" * self.separator_len
            for key in line:
                output += separator + str("{:^{width}}".format(line[key], width=self.column_width[key]))
                separator = " | "
            print output

            count += 1


class LspciSource(object):
    def __init__(self):
        self.record_cmd_output = False

    def record_lspci_cmd_out(self, cmd):
        # TBD record cmd output to file called as cmd
        # do this as
        pass

    def get_mlnx_eth_devices_bfd(self):
        # PCI vendor 15b3 == Mellanox
        # PCI class 0200 == Ethernet devices , 0207 == Infiniband devices
        data = exec_shell_cmd("lspci -nDd 15b3::0200 | awk '{print $1}'")

        # TBD: if self.record is True

        return data

    def get_mlnx_ib_devices_bfd(self):
        # PCI vendor 15b3 == Mellanox
        # PCI class 0200 == Ethernet devices , 0207 == Infiniband devices
        data = exec_shell_cmd("lspci -nDd 15b3::0207 | awk '{print $1}'")

        # TBD: if self.record is True

        return data


class LspciMockup(object):
    def __init__(self):
        pass


class PCIDevice(object):
    def __init__(self, bdf, data_source):
        self.bdf = bdf
        self.bdWithoutF = self.bdf.split(".", 1)[0]
        self.data = data_source.exec_shell_cmd("lspci -vvvD -s" + bdf)
        # Handling following string, taking reset of string after HCA type
        # 0000:01:00.0 Infiniband controller: Mellanox Technologies MT27700 Family [ConnectX-4]
        self.description = self.get_info_from_lspci_data("^[0-9].*", str(self.bdf) + ".*:(.+)")
        self.sn = self.get_info_from_lspci_data("\[SN\].*", ".*:(.+)")
        self.pn = self.get_info_from_lspci_data("\[PN\].*", ".*:(.+)")

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
            self.pfvf = "VF"
            self.vfParent = extract_string_by_regex(vf_parent_file, ".*\/([0-9].*)")
        else:
            self.pfvf = "PF"
            self.vfParent = "-"

        self.numa = data_source.read_file_if_exists(sys_prefix + "/numa_node").rstrip()
        if not self.numa:
            print >> sys.stderr, "Warning: " + self.bdf + " has no NUMA assignment"

        self.rdma = data_source.list_dir_if_exists(sys_prefix + "/infiniband/").rstrip()
        self.net = data_source.list_dir_if_exists(sys_prefix + "/net/").rstrip()
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

    def __repr__(self):
        delim = " "
        return "SYS device:" + delim +\
               self.get_bdf() + delim + \
               self.get_pfvf() + delim + \
               self.get_vf_parent() + delim + \
               self.get_numa()

    def get_bdf(self):
        return self.bdf

    def get_pfvf(self):
        return self.pfvf

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


class MlnxBFDDevice(object):
    def __init__(self, bdf, data_source):
        self.bdf = bdf
        self.sysFSDevice = SYSFSDevice(self.bdf, data_source)
        self.pciDevice = PCIDevice(self.bdf, data_source)
        self.slaveBDFDevices = []

    def __repr__(self):
        return self.sysFSDevice.__repr__() + "\n" + self.pciDevice.__repr__() + "\n"

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

    def get_pfvf(self):
        return self.sysFSDevice.get_pfvf()

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

    def output_info(self):
        if self.get_pfvf() is "PF":
            pfvf = self.get_pfvf() + "  "
        else:
            pfvf = "  " + self.get_pfvf()
        output = {"pfvf": pfvf,
                  "numa": self.get_numa(),
                  "bdf": self.get_bdf(),
                  "vf_parent": self.get_vf_parent(),
                  "rdma": self.get_rdma(),
                  "net": self.get_net(),
                  "hca_type": self.get_hca_type(),
                  "state": self.get_state(),
                  "port_rate": self.get_port_rate(),
                  "link_layer": self.get_link_layer()}
        return output

    @staticmethod
    def output_headers():
        output = {"pfvf": "PfVf",
                  "numa": "Numa",
                  "bdf": "PCI addr",
                  "vf_parent": "Parent addr",
                  "rdma": "RDMA",
                  "net": "Net",
                  "hca_type": "HCA Type",
                  "state": "State",
                  "port_rate": "Rate",
                  "link_layer": "Link"}
        return output


class MlnxHCA(object):
    def __init__(self, bfd_dev):
        self.bfd_devices = []

        if bfd_dev.get_pfvf() == "PF":
            self.bfd_devices.append(bfd_dev)
        else:
            raise ValueError("MlnxHCA object can be initialised ONLY with PF bfdDev")

        self.sn = bfd_dev.get_sn()
        self.pn = bfd_dev.get_pn()
        self.fw = bfd_dev.get_fw()

    def __repr__(self):
        output = ""
        for bfd_dev in self.bfd_devices:
            output = output + str(bfd_dev)
        return output

    def add_bdf_dev(self, bfd_dev):
        self.bfd_devices.append(bfd_dev)

    def get_sn(self):
        return self.sn

    def get_pn(self):
        return self.pn

    def get_fw(self):
        return self.fw

    def get_description(self):
        return self.bfd_devices[0].get_description()

    def output_info(self):
        output = {"hca_info": {"SN": self.get_sn(),
                               "PN": self.get_pn(),
                               "FW": self.get_fw(),
                               "Desc": self.get_description()},
                  "bdf_devices": [],
                  "bdf_devices_headers": self.bfd_devices[0].output_headers()}
        for bdf_dev in self.bfd_devices:
            output["bdf_devices"].append(bdf_dev.output_info())
        return output


class DataSource(object):
    def __init__(self):
        if config.record_data_for_debug is True:
            if config.record_dir is None:
                config.record_dir = "/tmp/lshca"

            if not os.path.exists(config.record_dir):
                os.makedirs(config.record_dir)

            config.record_tar_file = config.record_dir + "/" + os.uname()[1] + "--" + str(time.time()) + ".tar"

            print "\nlshca started data recording"
            print "output saved in " + config.record_tar_file + " file\n\n"

    def exec_shell_cmd(self, cmd):
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
        output, error = process.communicate()
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
        else:
            print "\n" + user_args[index] + " - Unknown parameter\n"
            usage()

        index += 1


def usage():
    print "Usage: lspci [-h] [-m normal|record]"
    print "-h, --help"
    print "  Show this help"
    print "-d"
    print "  run with debug outputs"
    print "-m <mode>"
    print "  Mode of operation"
    print "    normal - (default) list HCAs"
    print "    record - record all data for debug and lists HCAs"
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
