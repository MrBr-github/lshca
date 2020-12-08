#!/usr/bin/env python2

# Description: This utility comes to provide bird's-eye view of HCAs installed.
#              It's mainly intended for system administrators, thus defaults configured accordingly.
# Author: Michael Braverman
# Email: mrbr.mail@gmail.com
# Project repo: https://github.com/MrBr-github/lshca
# License: This utility provided under GNU GPLv3 license

import os
import pickle
import re
import sre_constants
import StringIO
import subprocess
import sys
import tarfile
import time
import json
import argparse
import textwrap


class Config(object):
    def __init__(self):
        self.debug = False

        self.output_view = "system"
        self.output_order_general = {
                    "system": ["Dev", "Desc", "PN", "PSID", "SN", "FW", "PCI_addr", "RDMA", "Net", "Port", "Numa", "LnkStat",
                               "IpStat", "Link", "Rate", "SRIOV", "Parent_addr", "Tempr", "LnkCapWidth", "LnkStaWidth",
                               "HCA_Type", "Bond", "BondState", "BondMiiStat"],
                    "ib": ["Dev", "Desc", "PN", "PSID", "SN", "FW", "RDMA", "Port", "Net", "Numa", "LnkStat", "IpStat",
                           "VrtHCA", "PLid", "PGuid", "IbNetPref"],
                    "roce": ["Dev", "Desc", "PN", "PSID", "SN", "FW", "PCI_addr", "RDMA", "Net", "Port", "Numa", "LnkStat",
                             "IpStat", "RoCEstat"]
        }
        self.output_order = self.output_order_general[self.output_view]
        self.show_warnings_and_errors = True
        self.colour_warnings_and_errors = True
        self.warning_sign = "*"
        self.error_sign = " >!<"

        self.record_data_for_debug = False
        self.record_dir = "/tmp/lshca"
        self.record_tar_file = None

        self.ver = "3.4"

        self.mst_device_enabled = False
        self.sa_smp_query_device_enabled = False

        self.output_format = "human_readable"
        self.output_format_elastic = None
        self.output_separator_char = "-"
        self.output_fields_filter_positive = ""
        self.output_fields_filter_negative = ""
        self.where_output_filter = ""

        self.lossless_roce_expected_trust = "dscp"
        self.lossless_roce_expected_pfc = "00010000"
        self.lossless_roce_expected_gtclass = "Global tclass=106"
        self.lossless_roce_expected_tcp_ecn = "1"
        self.lossless_roce_expected_rdma_cm_tos = "106"

    def parse_arguments(self, user_args):
        parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter,
                                         epilog=textwrap.dedent('''\
                     Output warnings and errors:
                         In some cases warning and error signs will be shown. They highlight obvious issues
                         Warnings and errors won't be visible in JSON output and/or if the output is not to terminal
                          ''' + self.warning_sign + '''  == Warning.
                         Example: speed of disabled port might be 10G, where the actual port speed is 100G
                         ''' + self.error_sign + '''  == Error.
                         Example: HCA requires x16 PCI lanes, but only x8 available in the slot
                         
                     examples:
                         lshca -j -s mst -o \"-SN\"
                         lshca -o \"Dev,Port,Net,PN,Desc,RDMA\" -ow \"RDMA=mlx5_[48]\"

                        '''))

        parser.add_argument('-hh', action='store_true', dest="extended_help",
                            help="show extended help message and exit. All fields description and more")
        parser.add_argument('-d', action='store_true', dest="debug", help="run with debug outputs")
        parser.add_argument('-j', action='store_true', dest="json",
                            help="output data as JSON, affected by output selection flag")
        parser.add_argument('-v', '--version', action='version', version=str('%(prog)s ver. ' + self.ver))
        parser.add_argument('-m', choices=["normal", "record"], default="normal", dest="mode",
                            help=textwrap.dedent('''\
                            mode of operation (default: %(default)s):
                              normal - list HCAs
                              record - record all data for debug and lists HCAs\
                            '''))
        parser.add_argument('-w', choices=['system', 'ib', 'roce', 'all'], default='system', dest="view",
                            help=textwrap.dedent('''\
                            show output view (default: %(default)s):
                              system - (default). Show system oriented HCA info
                              ib     - Show IB oriented HCA info. Implies "sasmpquery" data source
                              roce   - Show RoCE oriented HCA info"
                              all    - Show all available HCA info. Aggregates all above views + MST data source.
                              Note: all human readable output views are elastic. See extended help for more info.
                            ''')
                            )
        parser.add_argument('--non-elastic', action='store_false', dest="elastic",
                            help="Set human readable output as non elastic")
        parser.add_argument('--no-colour', '--no-color', action='store_false', dest="colour",
                            help="Do not colour warrinings and errors.")
        parser.add_argument('-s', choices=['lspci', 'sysfs', 'mst', 'sasmpquery'], nargs='+', dest="sources",
                            help=textwrap.dedent('''\
                            add optional data sources (comma delimited list)
                            always on data sources are:
                              lspci    - provides lspci utility based info. Requires root for full output 
                              sysfs    - provides driver based info retrieved from /sys/
                            optional data sources:
                              mst        - provides MST based info. This data source slows execution
                              sasmpquery - provides SA/SMP query based info of the IB network
                            '''))
        parser.add_argument('-o', dest="output_fields_filter_positive", nargs="+",
                            help=textwrap.dedent('''\
                            SELECT fields to output (comma delimited list). Use field names as they appear in output
                            '''))
        parser.add_argument('-onot', dest="output_fields_filter_negative", nargs="+",
                            help=textwrap.dedent('''\
                            REMOVE fields from default output (comma delimited list).
                            Use field names as they appear in output. -o takes precedence
                            '''))
        parser.add_argument('-ow', dest="output_fields_value_filter", nargs='+',
                            help=textwrap.dedent('''\
                            select fields to output, WHERE field value is regex: field_name=value
                            (comma delimited list). Use field names as they appear in output
                            '''))

        # comes to handle comma separated list of choices
        cust_user_args = []
        for arg in user_args:
            result = arg.split(",")
            for member in result:
                cust_user_args.append(member)

        args = parser.parse_args(cust_user_args)
        self.process_arguments(args)

    def process_arguments(self, args):
        if args.mode == "record":
            self.record_data_for_debug = True

        if args.debug:
            self.debug = True

        if args.view == "ib":
            self.sa_smp_query_device_enabled = True
            self.output_view = "ib"
        elif args.view == "roce":
            self.output_view = "roce"
        elif args.view == "system":
            self.output_view = "system"
        elif args.view == "all":
            self.mst_device_enabled = True
            self.sa_smp_query_device_enabled = True
            self.output_view = "all"

        if self.output_view != "all":
            self.output_order = self.output_order_general[self.output_view]
        else:
            i = 0
            for view in self.output_order_general:
                if i == 0:
                    self.output_order = self.output_order_general[view]
                else:
                    for key in self.output_order_general[view]:
                        if key not in self.output_order:
                            self.output_order.append(key)
                i += 1

        if args.json:
            self.output_format = "json"
            self.show_warnings_and_errors = False

        if args.sources:
            for data_source in args.sources:
                if data_source == "lspci":
                    pass
                elif data_source == "sysfs":
                    pass
                elif data_source == "mst":
                    self.mst_device_enabled = True
                elif data_source == "sasmpquery":
                    self.sa_smp_query_device_enabled = True

        if args.output_fields_filter_positive:
            self.output_fields_filter_positive = args.output_fields_filter_positive

        if args.output_fields_filter_negative:
            self.output_fields_filter_negative = args.output_fields_filter_negative

        if args.output_fields_value_filter:
            self.where_output_filter = args.output_fields_value_filter

        if args.extended_help:
            self.extended_help()

        self.output_format_elastic = args.elastic

        self.colour_warnings_and_errors = args.colour

    @staticmethod
    def extended_help():
        print textwrap.dedent("""
        --== Detailed fields description ==--
        Note: BDF is a Bus-Device-Function PCI address. Each HCA port/vf has unique BDF.

        HCA header:
          Dev   - Device number. Enumerated value padded with #
          Desc  - HCA description as appears in lspci output
          FW    - HCA currently running firmware version
          PN    - HCA part number including revision
          SN    - HCA serial number
          PSID  - HCA PSID number (Parameter Set ID)
          Tempr - HCA temperature. Based on mget_temp utility from MFT

        BDF devices:
         Generic
          Net       - Network interface name, as appears in "ip link show"
          Numa      - NUMA affinity
          PCI_addr  - PCI address (BDF)
          Port      - Channel Adapter (ca_port, not related to physical port). On most mlx5 devices port is 1
          RDMA      - Channel Adapter name (ca_name)
          LnkStat   - Port state as provided by driver. Possible values:
                               State/Physical State
                        actv - active/linkup 
                        init - initializing/linkup
                        poll - down/polling
                        down - down/disabled
          IpStat    - Port IP address configuration state as provided by kernel. Possible values:
                               Operstate/IP address configured
                        down    - down/no ip addr. configured
                        up_noip - up/no ip addr. configured
                        up_ip4  - up/ipv4 addr. configured
                        up_ip6  - up/ipv6 addr. configured
                        up_ip46 - up/both ipv4 and ipv6 addr. configured

         System view
          HCA_Type      - Channel Adapter type, as appears in "ibstat"
          Link          - Link type. Possible values:
                            IB  - InfiniBand
                            Eth - Ethernet
          LnkCapWidth   - PCI width capability. Number of PCI lanes required by HCA. PF only.
          LnkStaWidth   - PCI width status. Number of PCI lanes avaliable for HCA in current slot. PF only.
          Parent_addr   - BDF address of SRIOV parent Physical Function for this Virtual Function
          Rate          - Link rate in Gbit/s
                          On bond master, will show all slave speeds delimited by /
          SRIOV         - SRIOV function type. Possible values:
                            PF - Physical Function
                            VF - Virtual Function
          Bond          - Name of Bond parent
          BondState     - On slave interface - status in a bond
                          On master interface - bonding policy appended by xmit hash policy if relevant
                          Search for bonding.txt in kernel.org for detailed information
          BondMiiStat   - Interface mii status in a bond. Search for bonding.txt in kernel.org for detailed information

         IB view
          IbNetPref     - IB network preffix
          PGuid         - Port GUID
          PLid          - Port LID
          SMGuid        - OpenSM GUID
          SwDescription - Switch description. As appears in "ibnetdiscover"
          SwGuid        - Switch GUID
          VrtHCA        - Is this a Virtual HCA port. Possible values:
                            Phys - Physical HCA port. For example, you could run openSM this ports
                            Virt - Virtual HCA port.
                            NA   - IB link - not supported with mlx4 driver OR non IB link
         RoCE view
          RoCEstat      - RoCE status. Possible values:
                            Lossless - Port configured with Lossless port configurations.
                            Lossy    - Port configured with Lossy port configurations


        --== Elastic output rules ==--
        Elastic output comes to reduce excessive information in human readable output.
        Following will be removed per HCA if the condition is True
        SRIOV, Parent_addr
                     - if there is no SRIOV VF
        LnkStaWidth  - if LnkStaWidth matches LnkCapWidth
        Port         - if all Port values are 1
        LnkStat      - if all LnkStat valuse are "actv"
        IpStat       - if all LnkStat valuse are "down"
        Bond, BondState, BondMiiStat
                     - if no bond device configured

        """)
        sys.exit(0)


class HCAManager(object):
    def __init__(self, data_source, config):
        self.config = config
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
                bdf_dev = MlnxBDFDevice(bdf, data_source, self.config, port_count)
                mlnx_bdf_devices.append(bdf_dev)

                if port_count >= len(bdf_dev.port_list):
                    break

                port_count += 1

        self.mlnxHCAs = []
        # First handle all PFs
        for bdf_dev in mlnx_bdf_devices:
            rdma_bond_bdf = None

            # Only first slave interface in a bond has infiniband information on his sysfs
            if bdf_dev.bond_master != "" and bdf_dev.rdma != "" :
                rdma_bond_bdf = MlnxRdmaBondDevice(bdf_dev.bdf, data_source, self.config)
                rdma_bond_bdf.fix_rdma_bond(data_source)

                bdf_dev.rdma = ""
                bdf_dev.lnk_state = ""

            if bdf_dev.sriov in ("PF", "PF" + self.config.warning_sign):
                hca_found = False
                for hca in self.mlnxHCAs:
                    if hca.sys_image_guid and bdf_dev.sys_image_guid == hca.sys_image_guid or \
                      bdf_dev.sn == hca.sn:
                        hca_found = True
                        if rdma_bond_bdf:
                            hca.add_bdf_dev(rdma_bond_bdf)
                        hca.add_bdf_dev(bdf_dev)

                if not hca_found:
                    if rdma_bond_bdf:
                        hca = MlnxHCA(rdma_bond_bdf, self.config)
                        hca.add_bdf_dev(bdf_dev)
                    else:
                        hca = MlnxHCA(bdf_dev,  self.config)
                    hca.hca_index = len(self.mlnxHCAs) + 1
                    self.mlnxHCAs.append(hca)

        # Now handle all VFs
        for bdf_dev in mlnx_bdf_devices:
            if bdf_dev.sriov == 'VF':
                vf_parent_bdf = bdf_dev.vfParent

                # TBD: refactor to function
                for parent_bdf_dev in mlnx_bdf_devices:
                    parent_found = False
                    if vf_parent_bdf == parent_bdf_dev.bdf:
                        parent_found = True

                        hca = self.get_hca_by_sys_image_guid(parent_bdf_dev.sys_image_guid)
                        if hca is not None:
                            hca.add_bdf_dev(bdf_dev)
                        else:
                            raise Exception("VF " + str(bdf_dev) + " This device has no parent PF")

                    if parent_found:
                        break

        if self.config.show_warnings_and_errors:
            for hca in self.mlnxHCAs:
                hca.check_for_issues()

    def display_hcas_info(self):
        out = Output(self.config)
        for hca in self.mlnxHCAs:
            output_info = hca.output_info()
            out.append(output_info)

        out.print_output()

    def get_hca_by_sys_image_guid(self, sys_image_guid):
        for hca in self.mlnxHCAs:
            if sys_image_guid == hca.sys_image_guid:
                return hca
        return None


class Output(object):
    def __init__(self, config):
        self.config = config
        self.output = []
        self.column_width = {}
        self.separator = ""
        self.separator_len = 0
        self.output_filter = {}
        self.output_order = self.config.output_order

    def append(self, data):
        self.output.append(data)

    def apply_select_output_filters(self):
        if len(self.config.output_fields_filter_positive) > 0:
            self.output_order = self.config.output_fields_filter_positive
        elif len(self.config.output_fields_filter_negative) > 0:
            decrement_list = self.output_order

            output_filter = self.config.output_fields_filter_negative
            for item in output_filter:
                if item in self.output_order:
                    decrement_list.remove(item)

            self.output_order = decrement_list

        data_keys_remove_list = []
        if len(self.output) > 0:
            output_data_keys = list(self.output[0]) + list(self.output[0]["bdf_devices"][0])
            data_keys_remove_list = list(set(output_data_keys) - set(self.output_order))

        for hca in self.output:
            for key in data_keys_remove_list:
                if key == "bdf_devices":
                    continue
                hca.pop(key, None)
            for bdf_device in hca["bdf_devices"]:
                bdf_device.pop(key, None)

    def apply_where_output_filters(self):
        if not self.config.where_output_filter:
            return

        output_filter = dict(item.split("=") for item in self.config.where_output_filter)
        for filter_key in output_filter:
            try:
                output_filter[filter_key] = re.compile(output_filter[filter_key])
            except sre_constants.error:
                print "Error: Invalid pattern \"%s\" passed to output filter " % output_filter[filter_key]
                sys.exit(1)

        for filter_key in output_filter:
            remove_hca_list = []
            for hca in self.output:
                remove_bdf_list = []
                for bdf_device in hca["bdf_devices"]:
                    if filter_key in bdf_device and not re.match(output_filter[filter_key],
                                                                 bdf_device[filter_key]):
                        remove_bdf_list.append(bdf_device)

                for bdf_device in remove_bdf_list:
                    hca["bdf_devices"].remove(bdf_device)

                if len(hca["bdf_devices"]) == 0 or \
                        filter_key in hca and not \
                        re.match(output_filter[filter_key], hca[filter_key]):
                    remove_hca_list.append(hca)

            for hca in remove_hca_list:
                self.output.remove(hca)

    def elastic_output(self):
        for hca in self.output:
            hca_fields_for_removal = []
            remove_sriov_and_parent = True
            remove_lnk_sta_width = True
            remove_port = True
            remove_lnk_stat = True
            remove_ip_stat = True
            remove_bond = True

            for bdf_device in hca["bdf_devices"]:
                # ---- Removing SRIOV and Parent_addr if no VFs present
                if "SRIOV" in bdf_device:
                    if bdf_device["SRIOV"].strip() != "PF" and \
                            bdf_device["SRIOV"].strip() != "PF" + self.config.warning_sign:
                        remove_sriov_and_parent = False

                # ---- Remove LnkStaWidth if it matches LnkCapWidth
                if "LnkStaWidth" in bdf_device:
                    field_value = bdf_device["LnkStaWidth"].strip()
                    if re.search(re.escape(self.config.error_sign) + "$", field_value):
                        remove_lnk_sta_width = False

                # ---- Remove Port if all values are 1
                if "Port" in bdf_device:
                    if bdf_device["Port"].strip() != "1":
                        remove_port = False

                # ---- Remove IpStat if all LnkStat are down
                if "LnkStat" in bdf_device:
                    if bdf_device["LnkStat"].strip() != "down":
                        remove_ip_stat = False

                # ---- Remove LnkStat if all are actv
                if "LnkStat" in bdf_device:
                    if ( bdf_device["LnkStat"].strip() != "actv" and bdf_device["Bond"] == "" ) or \
                       ( bdf_device["LnkStat"].strip() != "" and bdf_device["Bond"] != "" ):
                        remove_lnk_stat = False

                # ---- Remove bond related fields if no bond configured
                if "Bond" in bdf_device:
                    if bdf_device["Bond"].strip() and bdf_device["Bond"].strip() != "=N/A=":
                        remove_bond = False

            if remove_sriov_and_parent:
                hca_fields_for_removal.append("SRIOV")
                hca_fields_for_removal.append("Parent_addr")
            if remove_lnk_sta_width:
                hca_fields_for_removal.append("LnkStaWidth")
            if remove_port:
                hca_fields_for_removal.append("Port")
            if remove_ip_stat:
                hca_fields_for_removal.append("IpStat")
            if remove_lnk_stat:
                hca_fields_for_removal.append("LnkStat")
            if remove_bond:
                hca_fields_for_removal.append("Bond")
                hca_fields_for_removal.append("BondState")
                hca_fields_for_removal.append("BondMiiStat")

            for field in hca_fields_for_removal:
                if field in hca:
                    del hca[field]
                for bdf_device in hca["bdf_devices"]:
                    if field in bdf_device:
                        del bdf_device[field]

    def filter_out_data(self):
        self.apply_where_output_filters()
        self.apply_select_output_filters()
        if self.config.output_format == "human_readable" and self.config.output_format_elastic:
            self.elastic_output()

    def update_separator_and_column_width(self):
        line_width = 0
        for hca in self.output:
            curr_hca_column_width = {}
            for key in hca:
                if key == "bdf_devices":
                    for bdf_device in hca["bdf_devices"]:
                        for bdf_key in bdf_device:
                            if bdf_key in self.output_order:
                                if len(bdf_device[bdf_key]) > len(bdf_key):
                                    width = len(bdf_device[bdf_key])
                                else:
                                    width = len(bdf_key)

                                if bdf_key not in self.column_width or \
                                        len(bdf_device[bdf_key]) > self.column_width[bdf_key]:
                                    self.column_width[bdf_key] = width
                                if bdf_key not in curr_hca_column_width or \
                                        len(bdf_device[bdf_key]) > curr_hca_column_width[bdf_key]:
                                    curr_hca_column_width[bdf_key] = width
                else:
                    current_width = len(key) + len(str(hca[key])) + 5
                    if line_width < current_width:
                        line_width = current_width

            bdf_device_line_width = sum(curr_hca_column_width.values()) + len(curr_hca_column_width) * 3 - 2

            self.separator_len = max(self.separator_len, bdf_device_line_width, line_width)

    def print_output(self):
        self.filter_out_data()

        if self.config.output_format == "human_readable":
            self.update_separator_and_column_width()
            if self.separator_len == 0:
                print("No HCAs to display")
                sys.exit(0)
            self.print_output_human_readable()
        elif self.config.output_format == "json":
            self.print_output_json()

    def colour_warnings_and_errors(self, field_value):
        if self.config.show_warnings_and_errors and self.config.colour_warnings_and_errors:
            if re.search(re.escape(self.config.error_sign) + "$", str(field_value).strip()):
                field_value = BColors.FAIL + field_value + BColors.ENDC
            elif re.search(re.escape(self.config.warning_sign) + "$", str(field_value).strip()):
                field_value = BColors.WARNING + field_value + BColors.ENDC

        return field_value

    def print_output_human_readable(self):
        self.separator = self.config.output_separator_char * self.separator_len

        print self.separator
        for hca in self.output:
            self.print_hca_header(hca)
            print self.separator
            self.print_bdf_devices(hca["bdf_devices"])
            print self.separator

    def print_output_json(self):
        print json.dumps(self.output, indent=4, sort_keys=True)

    def print_hca_header(self, args):
        order_dict = {}

        position = 0
        for key in self.output_order:
            if key in args:
                order_dict[key] = position
                position += 1

        output_list = [""] * len(order_dict)
        for key in args:
            if key in order_dict:
                if key == "Dev":
                    prefix = ""
                    suffix = " "
                else:
                    prefix = " "
                    suffix = ": "
                output_list = output_list[0:order_dict[key]] + \
                              [prefix + str(key) + suffix + str(self.colour_warnings_and_errors(args[key]))] + \
                              output_list[order_dict[key] + 1:]

        if output_list:
            print '\n'.join(output_list)

    def print_bdf_devices(self, args):
        count = 1
        order_dict = {}

        position = 0
        for key in self.output_order:
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
                print self.separator

            for key in line:
                if key in order_dict:
                    field_value = str("{0:^{width}}".format(line[key], width=self.column_width[key]))
                    field_value = self.colour_warnings_and_errors(field_value)
                    output_list = output_list[0:order_dict[key]] + [field_value] + \
                                   output_list[order_dict[key] + 1:]

            count += 1
            print ' | '.join(output_list)


class MSTDevice(object):
    def __init__(self, bdf, data_source, config):
        self.bdf = bdf
        self.config = config
        self.mst_device = ""
        self.mst_raw_data = "No MST data"
        self.bdf_short_format = True
        mst_init_running = False

        if self.config.mst_device_enabled:
            if "MST_device" not in self.config.output_order:
                self.config.output_order.append("MST_device")

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
            else:
                print >> sys.stderr, "\n\nError: MST tool is missing\n\n"
                # Disable further use.access to mst device
                self.config.mst_device_enabled = False

    def __repr__(self):
        return self.mst_raw_data


class PCIDevice(object):
    def __init__(self, bdf, data_source, config):
        self.bdf = bdf
        self.config = config
        self.bdWithoutF = self.bdf.split(".", 1)[0]
        self.data = data_source.exec_shell_cmd("lspci -vvvD -s" + bdf, use_cache=True)
        # Handling following string, taking reset of string after HCA type
        # 0000:01:00.0 Infiniband controller: Mellanox Technologies MT27700 Family [ConnectX-4]
        self.description = self.get_info_from_lspci_data("^[0-9].*", str(self.bdf) + ".*:(.+)")
        self.sn = self.get_info_from_lspci_data("\[SN\].*", ".*:(.+)")
        self._pn = self.get_info_from_lspci_data("\[PN\].*", ".*:(.+)")
        self.revision = self.get_info_from_lspci_data("\[EC\].*", ".*:(.+)")
        self.lnkCapWidth = self.get_info_from_lspci_data("LnkCap:.*Width.*", ".*Width (x[0-9]+)")
        self.lnkStaWidth = self.get_info_from_lspci_data("LnkSta:.*Width.*", ".*Width (x[0-9]+)")
        self.pciGen = self.get_info_from_lspci_data(".*[Pp][Cc][Ii][Ee] *[Gg][Ee][Nn].*",
                                                    ".*[Pp][Cc][Ii][Ee] *[Gg][Ee][Nn]([0-9]) +")

        if self.lnkCapWidth != self.lnkStaWidth and self.config.show_warnings_and_errors is True:
            self.lnkStaWidth = str(self.lnkStaWidth) + self.config.error_sign

        self.lnkCapWidth = str(self.lnkCapWidth) + " G" + str(self.pciGen)

    def __repr__(self):
        delim = " "
        return "PCI device:" + delim +\
               self.bdf + delim + \
               self.sn + delim + \
               self.pn + delim +\
               "\"" + self.description + "\""

    @property
    def pn(self):
        if self.revision != "=N/A=":
            return self._pn + "  rev. " + self.revision
        else:
            return self._pn

    def get_info_from_lspci_data(self, search_regex, output_regex):
        search_result = find_in_list(self.data, search_regex)
        search_result = extract_string_by_regex(search_result, output_regex)
        return str(search_result).strip()


class SYSFSDevice(object):
    def __init__(self, bdf, data_source, config, port=1):
        self.bdf = bdf
        self.port = str(port)
        self.config = config

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

            if str(net_port) == self.port:
                self.net = net
                break

        self.hca_type = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma + "/hca_type").rstrip()

        self.lnk_state = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma + "/ports/" +
                                                         self.port + "/state")
        self.lnk_state = extract_string_by_regex(self.lnk_state, "[0-9:]+ (.*)", "").lower()
        if self.lnk_state == "active":
            self.lnk_state = "actv"

        if self.lnk_state == "down":
            self.phys_state = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma +
                                                          "/ports/" + self.port + "/phys_state")
            self.phys_state = extract_string_by_regex(self.phys_state, "[0-9:]+ (.*)", "").lower()

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
        self.port_rate = extract_string_by_regex(self.port_rate, "([0-9]*) .*", "")
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

        self.pguid = extract_string_by_regex(full_guid, "((:[A-Fa-f0-9]{4}){4})$", "").lower()
        self.pguid = re.sub(':', '', self.pguid)

        self.ib_net_prefix = extract_string_by_regex(full_guid, "^(([A-Fa-f0-9]{4}:){4})", "").lower()
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

        self.sys_image_guid = data_source.read_file_if_exists(sys_prefix + "/infiniband/" + self.rdma +
                                                              "/sys_image_guid").rstrip()

        self.bond_mii_status = data_source.read_file_if_exists(sys_prefix + "/net/" + self.net +
                                                              "/bonding_slave/mii_status").rstrip()
        self.bond_state = data_source.read_file_if_exists(sys_prefix + "/net/" + self.net +
                                                              "/bonding_slave/state").rstrip()

        self.operstate = data_source.read_file_if_exists("/sys/class/net/" + self.net + "/operstate").rstrip()
        self.ip_state = None
        if self.operstate == "up":
            # Implemented via shell cmd to avoid using non default libraries
            interface_data = data_source.exec_shell_cmd(" ip address show dev %s" % self.net)
            ipv4_data = find_in_list(interface_data, "inet .+")
            ipv6_data = find_in_list(interface_data, "inet6 .+")
            if ipv4_data and ipv6_data:
                self.ip_state = "up_ip46"
            elif ipv4_data:
                self.ip_state = "up_ip4"
            elif ipv6_data:
                self.ip_state = "up_ip6"
            else:
                if self.bond_state:
                    self.ip_state = "up"
                else:
                    self.ip_state = "up_noip"
        elif not self.operstate:
            self.ip_state = ""
        else:
            self.ip_state = "down"

        tmp = data_source.list_dir_if_exists(sys_prefix + "/net/" + self.net).split(" ")
        bond_master_dir = find_in_list(tmp, "upper_.*").rstrip()
        self.bond_master = extract_string_by_regex(bond_master_dir, "upper_(.*)$")

        if self.ip_state == "down" and ( self.lnk_state == "actv" or self.bond_state ) \
                and self.config.show_warnings_and_errors is True:
            self.ip_state = self.ip_state + self.config.error_sign
        if self.ip_state == "up_noip" and self.config.show_warnings_and_errors is True:
            self.ip_state = self.ip_state + self.config.warning_sign

        # ========== RoCE view only related variables ==========
        self.gtclass = None
        self.tcp_ecn = None
        self.rdma_cm_tos = None

        if self.config.output_view == "roce" or self.config.output_view == "all":
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
        return "SYS device:" + delim +\
               self.bdf + delim + \
               self.sriov + delim + \
               self.vfParent + delim + \
               self.numa


class SaSmpQueryDevice(object):
    def __init__(self, rdma, port, plid, smlid, data_source, config):
        self.sw_guid = ""
        self.sw_description = ""
        self.sm_guid = ""
        self.config = config

        if self.config.sa_smp_query_device_enabled:
            if "SMGuid" not in self.config.output_order:
                self.config.output_order.append("SMGuid")
            if "SwGuid" not in self.config.output_order:
                self.config.output_order.append("SwGuid")
            if "SwDescription" not in self.config.output_order:
                self.config.output_order.append("SwDescription")

            self.data = data_source.exec_shell_cmd("smpquery -C " + rdma + " -P " + port + " NI -D  0,1")
            self.sw_guid = self.get_info_from_sa_smp_query_data(".*SystemGuid.*", "\.+(.*)")
            self.sw_guid = extract_string_by_regex(self.sw_guid, "0x(.*)")

            self.data = data_source.exec_shell_cmd("smpquery -C " + rdma + " -P " + port + " ND -D  0,1")
            self.sw_description = self.get_info_from_sa_smp_query_data(".*Node *Description.*", "\.+(.*)")

            self.data = data_source.exec_shell_cmd("saquery SMIR -C " + rdma + " -P " + port + " " + smlid)
            self.sm_guid = self.get_info_from_sa_smp_query_data(".*GUID.*", "\.+(.*)")
            self.sm_guid = extract_string_by_regex(self.sm_guid, "0x(.*)")

    def get_info_from_sa_smp_query_data(self, search_regex, output_regex):
        search_result = find_in_list(self.data, search_regex)
        search_result = extract_string_by_regex(search_result, output_regex)
        return str(search_result).strip()


class MiscCMDs(object):
    def __init__(self, net, rdma, data_source, config):
        self.data_source = data_source
        self.net = net
        self.rdma = rdma
        self.config = config

    def get_mlnx_qos_trust(self):
        data = self.data_source.exec_shell_cmd("mlnx_qos -i " + self.net, use_cache=True)
        regex = "Priority trust state: (.*)"
        search_result = find_in_list(data, regex)
        search_result = extract_string_by_regex(search_result, regex)
        return search_result

    def get_mlnx_qos_pfc(self):
        data = self.data_source.exec_shell_cmd("mlnx_qos -i " + self.net, use_cache=True)
        regex = '^\s+enabled\s+(([0-9]\s+)+)'
        search_result = find_in_list(data, regex)
        search_result = extract_string_by_regex(search_result, regex).replace(" ", "")
        return search_result

    def get_tempr(self):
        data = self.data_source.exec_shell_cmd("mget_temp -d " + self.rdma, use_cache=True)
        regex = '^([0-9]+)\s+$'
        search_result = find_in_list(data, regex)
        search_result = extract_string_by_regex(search_result, regex).replace(" ", "")
        try:
            if int(search_result) > 90:
                return search_result + self.config.error_sign
            elif int(search_result) > 80:
                return search_result + self.config.warning_sign
            return search_result
        except ValueError:
            return "=N/A="


class MlnxBDFDevice(object):
    def __init__(self, bdf, data_source, config, port=1):
        self.bdf = bdf
        self.config = config
        self.slaveBDFDevices = []

        self.sysFSDevice = SYSFSDevice(self.bdf, data_source, self.config, port)
        self.fw = self.sysFSDevice.fw
        self.hca_type = self.sysFSDevice.hca_type
        self.ib_net_prefix = self.sysFSDevice.ib_net_prefix
        self.link_layer = self.sysFSDevice.link_layer
        self.ip_state = self.sysFSDevice.ip_state
        self.pguid = self.sysFSDevice.pguid
        self.port = self.sysFSDevice.port
        self.port_list = self.sysFSDevice.port_list
        self.port_rate = self.sysFSDevice.port_rate
        self.plid = self.sysFSDevice.plid
        self.net = self.sysFSDevice.net
        self.numa = self.sysFSDevice.numa
        self.rdma = self.sysFSDevice.rdma
        self.smlid = self.sysFSDevice.smlid
        self.lnk_state = self.sysFSDevice.lnk_state
        self.virt_hca = self.sysFSDevice.virt_hca
        self.vfParent = self.sysFSDevice.vfParent
        self.sys_image_guid = self.sysFSDevice.sys_image_guid
        self.psid = self.sysFSDevice.psid
        self.bond_master = self.sysFSDevice.bond_master
        self.bond_state = self.sysFSDevice.bond_state
        self.bond_mii_status = self.sysFSDevice.bond_mii_status

        self.pciDevice = PCIDevice(self.bdf, data_source, self.config)
        self.description = self.pciDevice.description
        if self.sriov != "VF":
            self.lnkCapWidth = self.pciDevice.lnkCapWidth
            self.lnkStaWidth = self.pciDevice.lnkStaWidth
        else:
            self.lnkCapWidth = ""
            self.lnkStaWidth = ""
        self.pn = self.pciDevice.pn
        self.sn = self.pciDevice.sn

        self.mstDevice = MSTDevice(self.bdf, data_source, self.config)
        self.mst_device = self.mstDevice.mst_device

        self.miscDevice = MiscCMDs(self.net, self.rdma, data_source, self.config)
        self.tempr = self.miscDevice.get_tempr()

        self.sasmpQueryDevice = SaSmpQueryDevice(self.rdma, self.port, self.plid, self.smlid,
                                                 data_source, self.config)
        self.sw_guid = self.sasmpQueryDevice.sw_guid
        self.sw_description = self.sasmpQueryDevice.sw_description
        self.sm_guid = self.sasmpQueryDevice.sm_guid

    def __repr__(self):
        return self.sysFSDevice.__repr__() + "\n" + self.pciDevice.__repr__() + "\n" + \
                self.mstDevice.__repr__() + "\n"

    # Not in use, consider removal
    def add_slave_bdf_device(self, slave_bdf_device):
        self.slaveBDFDevices.append(slave_bdf_device)

    # Not in use, consider removal
    def get_slave_bdf_devices(self):
        return self.slaveBDFDevices

    @property
    def sriov(self):
        if self.config.show_warnings_and_errors is True and self.sysFSDevice.sriov == "PF" and \
                re.match(r".*[Vv]irtual [Ff]unction.*", self.pciDevice.description):
            return self.sysFSDevice.sriov + self.config.warning_sign
        else:
            return self.sysFSDevice.sriov

    @property
    def roce_status(self):
        if self.link_layer != "Eth":
            return "N/A"

        if self.sysFSDevice.gtclass == self.config.lossless_roce_expected_gtclass and \
           self.sysFSDevice.tcp_ecn == self.config.lossless_roce_expected_tcp_ecn and \
           self.sysFSDevice.rdma_cm_tos == self.config.lossless_roce_expected_rdma_cm_tos and \
           self.miscDevice.get_mlnx_qos_trust() == self.config.lossless_roce_expected_trust and \
           self.miscDevice.get_mlnx_qos_pfc() == self.config.lossless_roce_expected_pfc:
            return "Lossless"
        else:
            return "Lossy"

    def output_info(self):
        if self.sriov in ("PF", "PF" + self.config.warning_sign):
            sriov = self.sriov + "  "
        else:
            sriov = "  " + self.sriov
        output = {"SRIOV": sriov,
                  "Numa": self.numa,
                  "PCI_addr": self.bdf,
                  "Parent_addr": self.vfParent,
                  "RDMA": self.rdma,
                  "Net": self.net,
                  "HCA_Type": self.hca_type,
                  "LnkStat": self.lnk_state,
                  "Rate": self.port_rate,
                  "Port": self.port,
                  "Link": self.link_layer,
                  "MST_device": self.mst_device,
                  "LnkCapWidth": self.lnkCapWidth,
                  "LnkStaWidth": self.lnkStaWidth,
                  "PLid": self.plid,
                  "PGuid": self.pguid,
                  "IbNetPref": self.ib_net_prefix,
                  "SMGuid": self.sm_guid,
                  "SwGuid": self.sw_guid,
                  "SwDescription": self.sw_description,
                  "VrtHCA": self.virt_hca,
                  "IpStat": self.ip_state,
                  "RoCEstat": self.roce_status,
                  "Bond": self.bond_master,
                  "BondState": self.bond_state,
                  "BondMiiStat": self.bond_mii_status}
        return output


class MlnxHCA(object):
    def __init__(self, bdf_dev, config):
        self.bdf_devices = []
        self.config = config

        if bdf_dev.sriov in ("PF", "PF" + self.config.warning_sign):
            self.bdf_devices.append(bdf_dev)
        else:
            raise ValueError("MlnxHCA object can be initialised ONLY with PF bdfDev")

        self.sn = bdf_dev.sn
        self.pn = bdf_dev.pn
        self.fw = bdf_dev.fw
        self.psid = bdf_dev.psid
        self.sys_image_guid = bdf_dev.sys_image_guid
        self.description = bdf_dev.description
        self.tempr = bdf_dev.tempr
        self._hca_index = None

    def __repr__(self):
        output = ""
        for bdf_dev in self.bdf_devices:
            output = output + str(bdf_dev)
        return output

    @property
    def hca_index(self):
        return "#" + str(self._hca_index)

    @hca_index.setter
    def hca_index(self, index):
        self._hca_index = index

    def add_bdf_dev(self, new_bdf_dev):
        if new_bdf_dev.sriov == "VF" and new_bdf_dev.vfParent != "-":
            for i, bdf_dev in enumerate(self.bdf_devices):
                if bdf_dev.bdf == new_bdf_dev.vfParent:
                    self.bdf_devices.insert(i + 1, new_bdf_dev)
        else:
            self.bdf_devices.append(new_bdf_dev)

    def output_info(self):
        output = {"SN": self.sn,
                  "PN": self.pn,
                  "FW": self.fw,
                  "PSID": self.psid,
                  "Desc": self.description,
                  "Tempr": self.tempr,
                  "Dev": self.hca_index,
                  "bdf_devices": []}
        for bdf_dev in self.bdf_devices:
            output["bdf_devices"].append(bdf_dev.output_info())
        return output

    def check_for_issues(self):
        # this function comes to check for issues on HCA level cross all BDFs
        inactive_bond_slaves = []
        bond_type = ""

        for bdf in self.bdf_devices:
            if "802.3ad" in bdf.bond_state:
                bond_type = "802.3ad"
            elif bdf.bond_state != "active":
                inactive_bond_slaves.append(bdf)

        if bond_type == "802.3ad" and len(inactive_bond_slaves) > 0:
            for bdf in inactive_bond_slaves:
                bdf.bond_state = bdf.bond_state + self.config.error_sign



class MlnxRdmaBondDevice(MlnxBDFDevice):
    def fix_rdma_bond(self, data_source):
        index = extract_string_by_regex(self.rdma, ".*([0-9]+)$")
        self.bdf = "rdma_bond_" + index
        self.net = self.bond_master
        self.bond_master = ""
        self.bond_mii_status = ""
        self.ip_state = None

        sys_prefix = "/sys/devices/virtual/net/" + self.net

        operstate = data_source.read_file_if_exists(sys_prefix + "/operstate").rstrip()
        if operstate == "up":
            # Implemented via shell cmd to avoid using non default libraries
            interface_data = data_source.exec_shell_cmd(" ip address show dev %s" % self.net)
            ipv4_data = find_in_list(interface_data, "inet .+")
            ipv6_data = find_in_list(interface_data, "inet6 .+")
            if ipv4_data and ipv6_data:
                self.ip_state = "up_ip46"
            elif ipv4_data:
                self.ip_state = "up_ip4"
            elif ipv6_data:
                self.ip_state = "up_ip6"
            else:
                self.ip_state = "up_noip"
        elif not operstate:
            self.ip_state = ""
        else:
            self.ip_state = "down"

        if self.ip_state == "down" and self.lnk_state == "actv" \
                and self.config.show_warnings_and_errors is True:
            self.ip_state = self.ip_state + self.config.error_sign
        if self.ip_state == "up_noip" and self.config.show_warnings_and_errors is True:
            self.ip_state = self.ip_state + self.config.warning_sign

        mode = data_source.read_file_if_exists(sys_prefix + "/bonding/mode").rstrip()
        mode = mode.split(" ")[0]
        xmit_hash_policy = data_source.read_file_if_exists(sys_prefix + "/bonding/xmit_hash_policy").rstrip()
        xmit_hash_policy = xmit_hash_policy.split(" ")[0]
        xmit_hash_policy = xmit_hash_policy.replace("layer","l")
        xmit_hash_policy = xmit_hash_policy.replace("encap","e")

        self.bond_state = mode
        if xmit_hash_policy != "" :
            self.bond_state = self.bond_state + "/" + xmit_hash_policy

        # Slaves speed check
        slaves = data_source.read_file_if_exists(sys_prefix + "/bonding/slaves").rstrip().split(" ")
        bond_speed = ""
        bond_speed_missmatch = False
        for slave in slaves:
            slave_speed = data_source.read_file_if_exists(sys_prefix + "/slave_" + slave + "/speed").rstrip()
            slave_speed = str(int(slave_speed)/1000)
            if self.port_rate != slave_speed:
                bond_speed_missmatch = True

            if bond_speed == "":
                bond_speed = slave_speed
            else:
                bond_speed = bond_speed + "/" + slave_speed

        self.port_rate = bond_speed

        if bond_speed_missmatch:
            if self.config.show_warnings_and_errors is True:
                self.port_rate  = self.port_rate + self.config.error_sign


class DataSource(object):
    def __init__(self, config):
        self.cache = {}
        self.config = config
        if self.config.record_data_for_debug is True:
            if not os.path.exists(self.config.record_dir):
                os.makedirs(self.config.record_dir)

                self.config.record_tar_file = "%s/%s--%s.tar" % (self.config.record_dir, os.uname()[1],
                                                                 str(time.time()))

            print "\nlshca started data recording"
            print "output saved in " + self.config.record_tar_file + " file\n"

            self.stdout = StringIO.StringIO()
            sys.stdout = self.stdout

    def __del__(self):
        if self.config.record_data_for_debug is True:
            sys.stdout = sys.__stdout__
            self.record_data("cmd", "lshca " + " ".join(sys.argv[1:]))
            self.record_data("output", self.stdout.getvalue())

            self.config.record_data_for_debug = False
            environment = list()
            environment.append("LSHCA: " + self.config.ver)
            environment.append("OFED: " + " ".join(self.exec_shell_cmd("ofed_info -s")))
            environment.append("MST:  " + " ".join(self.exec_shell_cmd("mst version")))
            environment.append("Uname:  " + " ".join(self.exec_shell_cmd("uname -a")))
            environment.append("Release:  " + " ".join(self.exec_shell_cmd("cat /etc/*release")))
            environment.append("Env:  " + " ".join(self.exec_shell_cmd("env")))
            self.record_data("environment", environment)

    def exec_shell_cmd(self, cmd, use_cache=False):
        cache_key = self.cmd_to_str(cmd)

        if use_cache is True and cache_key in self.cache:
            output = self.cache[cache_key]

        else:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, executable="/bin/bash")
            output, error = process.communicate()
            if use_cache is True:
                self.cache.update({cache_key: output})

        output = output.splitlines()
        if self.config.record_data_for_debug is True:
            cmd = "shell.cmd/" + cmd
            self.record_data(cmd, output)

        return output

    def record_data(self, cmd, output):
        p_output = pickle.dumps(output)
        # file_name = self.cmd_to_str(cmd)
        file_name = cmd

        tarinfo = tarfile.TarInfo(file_name)
        tarinfo.size = len(p_output)
        tarinfo.mtime = time.time()

        tar = tarfile.open(name=self.config.record_tar_file, mode='a')
        tar.addfile(tarinfo, StringIO.StringIO(p_output))
        tar.close()

    def read_file_if_exists(self, file_to_read):
        if os.path.exists(file_to_read):
            f = open(file_to_read, "r")
            output = f.read()
            f.close()
        else:
            output = ""

        if self.config.record_data_for_debug is True:
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

        if self.config.record_data_for_debug is True:
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

        if self.config.record_data_for_debug is True:
            cmd = "os.listdir" + dir_to_list.rstrip('/') + "_dir"
            self.record_data(cmd, output)

        return output

    @staticmethod
    def cmd_to_str(cmd):
        output = re.escape(cmd)
        return output


class BColors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


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


def main():
    if os.geteuid() != 0:
        exit("You need to have root privileges to run this script")

    config = Config()
    config.parse_arguments(sys.argv[1:])

    data_source = DataSource(config)

    hca_manager = HCAManager(data_source, config)

    hca_manager.display_hcas_info()


if __name__ == "__main__":
    main()
