#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Description: This utility comes to provide bird's-eye view of HCAs installed.
#              It's mainly intended for system administrators, thus defaults configured accordingly.
# Author: Michael Braverman
# Email: mrbr.mail@gmail.com
# Project repo: https://github.com/MrBr-github/lshca
# License: This utility provided under GNU GPLv3 license

from __future__ import division
from __future__ import print_function
import os
import pickle
import re
import sre_constants
import subprocess
import sys
import tarfile
import time
import json
import argparse
import textwrap
import hashlib
import ctypes
import socket
import fcntl
import signal
import struct

try:
    from StringIO import StringIO # for Python 2
except ImportError:
    from io import StringIO, BytesIO # for Python 3


class Config(object):
    def __init__(self):
        self.debug = 0

        self.output_view = "system"
        self.output_order_general = {
                    "system": ["Dev", "Desc", "PN", "PSID", "SN", "FW", "Driver", "PCI_addr", "RDMA", "Net", "Port", "Numa", "LnkStat",
                               "IpStat", "Link", "Rate", "SRIOV", "Parent_addr", "Tempr", "LnkCapWidth", "LnkStaWidth",
                               "HCA_Type", "Bond", "BondState", "BondMiiStat"],
                    "ib": ["Dev", "Desc", "PN", "PSID", "SN", "FW", "Driver", "RDMA", "Port", "Net", "Numa", "LnkStat", "IpStat",
                           "VrtHCA", "PLid", "PGuid", "IbNetPref"],
                    "roce": ["Dev", "Desc", "PN", "PSID", "SN", "FW", "Driver", "PCI_addr", "RDMA", "Net", "Port", "Numa", "LnkStat",
                             "IpStat", "RoCEstat"],
                    "cable": ["Dev", "Desc", "PN", "PSID", "SN", "FW", "Driver", "RDMA", "Net", "MST_device",  "CblPN", "CblSN", "CblLng",
                              "PhyLinkStat", "PhyLnkSpd", "PhyAnalisys"],
                    "traffic": ["Dev", "Desc", "PN", "PSID", "SN", "FW", "Driver", "RDMA", "Net", "TX_bps", "RX_bps", "PktSeqErr"],
                    "lldp": ["Dev", "Desc", "PN", "PSID", "SN", "FW", "Driver", "PCI_addr", "RDMA", "Net", "Port", "Numa", "LnkStat",
                             "IpStat", "LLDPportId", "LLDPsysName", "LLDPmgmtAddr", "LLDPsysDescr"],
                    "dpu": ["Dev", "Desc", "PN", "PSID", "SN", "FW", "Driver", "RDMA", "Port", "Net", "DPUmode", "BFBver", "OvsBrdg",
                             "LnkStat", "IpStat", "UplnkRepr", "PfRepr", "VfRepr", "SRIOV"]
        }
        self.output_order = self.output_order_general[self.output_view]
        self.show_warnings_and_errors = True
        self.colour_warnings_and_errors = True
        self.warning_sign = "*"
        self.error_sign = " >!<"

        self.record_data_for_debug = False
        self.record_dir = "/tmp/lshca"
        self.record_tar_file = None

        self.ver = "3.8"

        self.mst_device_enabled = False
        self.sa_smp_query_device_enabled = False

        self.output_format = "human_readable"
        self.output_format_elastic = None
        self.output_separator_char = "-"
        self.output_fields_filter_positive = ""
        self.output_fields_filter_negative = ""
        self.where_output_filter = ""

        # based on https://community.mellanox.com/s/article/lossless-roce-configuration-for-linux-drivers-in-dscp-based-qos-mode
        self.lossless_roce_expected_trust = "dscp"
        self.lossless_roce_expected_pfc = "00010000"
        self.lossless_roce_expected_gtclass = "Global tclass=106"
        self.lossless_roce_expected_tcp_ecn = "1"
        self.lossless_roce_expected_rdma_cm_tos = "106"

        # based on https://docs.mellanox.com/pages/viewpage.action?pageId=43714202#LinkLayerDiscoveryProtocol(LLDP)-lldptimer
        self.lldp_capture_timeout = 35 # seconds. Based on default 30s value in Mellanox Onyx OS

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
        parser.add_argument('-d', type=int, default='0', dest="debug", help="run with debug outputs")
        parser.add_argument('-j', action='store_true', dest="json",
                            help="output data as JSON, affected by output selection flag")
        parser.add_argument('-v', '--version', action='version', version=str('%(prog)s ver. ' + self.ver))
        parser.add_argument('-m', choices=["normal", "record"], default="normal", dest="mode",
                            help=textwrap.dedent('''\
                            mode of operation (default: %(default)s):
                              normal - list HCAs
                              record - record all data for debug and lists HCAs\
                            '''))
        parser.add_argument('-w', choices=['system', 'ib', 'roce', 'cable', 'traffic', 'lldp', 'dpu', 'all'], default='system', dest="view",
                            help=textwrap.dedent('''\
                            show output view (default: %(default)s):
                              system  - (default). Show system oriented HCA info
                              ib      - Show IB oriented HCA info. Implies "sasmpquery" data source
                              roce    - Show RoCE oriented HCA info"
                              cable   - Show cable and physical link HCA info. Based on mlxcable and mlxlink utils.
                                        Note: It takes time to display this view due to underling utils execution time.
                              traffic - Show port traffic
                              lldp    - Show lldp information.
                              dpu     - Shou DPU (blueField) information
                              all     - Show all available HCA info. Aggregates all above views + MST data source.
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
            self.debug = args.debug

        if args.view == "ib":
            self.sa_smp_query_device_enabled = True
            self.output_view = "ib"
        elif args.view == "roce":
            self.output_view = "roce"
        elif args.view == "system":
            self.output_view = "system"
        elif args.view == "cable":
            self.output_view = "cable"
        elif args.view == "traffic":
            self.output_view = "traffic"
        elif args.view == "lldp":
            self.output_view = "lldp"
        elif args.view == "dpu":
            self.output_view = "dpu"
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

    def extended_help(self):
        extended_help = textwrap.dedent("""
        --== Detailed fields description ==--
        Note: BDF is a Bus-Device-Function PCI address. Each HCA port/vf has unique BDF.

        HCA header:
          Dev    - Device number. Enumerated value padded with #
          Desc   - HCA description as appears in lspci output
          FW     - HCA currently running firmware version
          PN     - HCA part number including revision
          SN     - HCA serial number
          PSID   - HCA PSID number (Parameter Set ID)
          Driver - Driver source (mlnx_ofed/inbox) and it version
          Tempr  - HCA temperature. Based on mget_temp utility from MFT

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
          LnkCapWidth   - PCI width capability. Number of PCI lanes and PCI generation required by HCA. PF only.
          LnkStaWidth   - PCI width status. Number of PCI lanes and PCI generation avaliable for HCA in current slot. PF only.
          Parent_addr   - BDF address of SRIOV parent Physical Function for this Virtual Function
          Rate          - Link rate in Gbit/s
                          On bond master, will show all slave speeds delimited by /
          SRIOV         - SRIOV and more function types. Possible values:
                            PF - Physical Function
                            VF - Virtual Function
                            SF - Scalable Function
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

         Cable view   (use source utils for more info)
          MST_device    - MST device name. Source mst
          CblPN         - Part number of the connected cable. Source mlxcable
          CblSN         - Serial number of the connected cable. Source mlxcable
          CblLng        - Length of the connected cable. Source mlxcable
          PhyAnalisys   - If something goes wrong, some analisys will be shown to assist in issue resolution. Source mlxlink
          PhyLinkStat   - Status of the physical link. May differ from its logical state. Source mlxlink
          PhyLnkSpd     - Speed of the physical link. I.e protocol used for communication. Source mlxlink

         RoCE view
          RoCEstat      - RoCE status. Possible values:
                            Lossless       - Port configured with Lossless port configurations.
                            Lossy[:bitmap] - Port configured with Lossy port configurations
                                   XXXXX     Bitmap will appear if lossless configuration is partial
                                   ││││└─ rdma_cm_tos - expected \"""" + self.lossless_roce_expected_rdma_cm_tos + """\"
                                   │││└── tcp_ecn  - expected \"""" + self.lossless_roce_expected_tcp_ecn + """\"
                                   ││└─── gtclass - expected \"""" + self.lossless_roce_expected_gtclass + """\"
                                   │└──── pfc - expected \"""" + self.lossless_roce_expected_pfc + """\"
                                   └───── trust - expected \"""" + self.lossless_roce_expected_trust + """\"

         Traffic view (K, M ,G used for human readability. K = 1000 bit.)
          TX_bps    - Transmitted traffic in bit/sec. Based on port_rcv_data counter
          RX_bps    - Received traffic in bit/sec. Based on port_xmit_data counter
          PktSeqErr - The number of received NAK sequence error packets (counts how many times there was a sequence number gap)
                      Based on packet_seq_err counter

         LLDP view
             This view relies on:
              * LLDP information been sent by the connected switch (if not NoLldpRcvd error msg will be received)
              * local port should be up and valid (if not LnkDown/LnkStatUnclr warning msg will be received)
             NOTE1: using this view puts interfaces in to promiscuous mode, use with CAUTION
             NOTE2: the script waits for LLDP packets to arrive,
                    it might take """ + str(self.lldp_capture_timeout) + """ * num_of_interfaces sec to complete
          LLDPportId    - Switch port description. LLDP TLV 2
          LLDPsysName   - Switch system name. LLDP TLV 5
          LLDPmgmtAddr  - Switch management IP address. LLDP TLV 8
          LLDPsysDescr  - Switch system description. Usualy contains Switch type, OS type and OS ver. LLDP TLV 6

         DPU view
          DPUmode   - DPU mode of operation.
            See link detailed explanations: https://docs.nvidia.com/networking/display/BlueFieldDPUOSLatest/Modes+of+Operation
            Possible values:
                ECPF      - the NIC resources and functionality are owned and controlled by the embedded Arm subsystem
                RestrHost - ECPF with DPU controled ONLY via ARM subsystem
                NIC       - DPU behaves exactly like an adapter card from the perspective of the external host
                Separated - network function is assigned to both the Arm cores and the x86 host cores. Traffic reaches both of them
                Undefined - Failed to identify DPU operation mode
          BFBver    - version of DPU BFB image. Works ONLY within the DPU os
          UplnkRepr - Uplink representor
          PfRepr    - PF representors
          VfRepr    - VF representors
          OvsBrdg   - OVS bridge see link [representors] for more information
          [representors] - https://docs.nvidia.com/networking/display/BlueFieldDPUOSLatest/Kernel+Representors+Model

        --== Elastic output rules ==--
        Elastic output comes to reduce excessive information in human readable output.
        Following will be removed per HCA if the condition is True
        SRIOV        - if there are only PF
        Parent_addr  - if there is no SRIOV VF
        LnkStaWidth  - if LnkStaWidth matches LnkCapWidth
        Port         - if all Port values are 1
        LnkStat      - if all LnkStat valuse are "actv"
        IpStat       - if all LnkStat valuse are "down"
        Bond, BondState, BondMiiStat
                     - if no bond device configured
        PhyAnalisys  - if no issue detected
        DPUmode      - if it has no value
        BFBver       - if it has no value
        LLDPportId, LLDPsysName, LLDPmgmtAddr, LLDPsysDescr
                     - if the interface is not Ethernet
        Whole BDF    - if it part of DPU and LnkStat is nop (unused BDFs)


        """)
        print(extended_help)
        sys.exit(0)


class HCAManager(object):
    def __init__(self, data_source, config):
        self._config = config
        self._data_source = data_source
        self.mlnxHCAs = []

    def get_data(self):
        mlnx_bdf_list = []
        # Same lspci cmd used in MST source in order to benefit from cache
        raw_mlnx_bdf_list = self._data_source.exec_shell_cmd("lspci -Dd 15b3:", use_cache=True)
        for member in raw_mlnx_bdf_list:
            bdf = extract_string_by_regex(member, "(.+) (Ethernet|Infini[Bb]and|Network)")

            if bdf != "=N/A=":
                mlnx_bdf_list.append(bdf)

        mlnx_bdf_devices = []
        for bdf in mlnx_bdf_list:
            port_count = 1

            while True:
                bdf_dev = MlnxBDFDevice(bdf, self._data_source, self._config, port_count)
                bdf_dev.get_data()
                mlnx_bdf_devices.append(bdf_dev)

                for sf in bdf_dev.sf_list:
                    sf_dev = MlnxBDFDevice(bdf, self._data_source, self._config, port_count, sf=sf)
                    sf_dev.get_data()
                    mlnx_bdf_devices.append(sf_dev)


                if port_count >= len(bdf_dev.port_list):
                    break

                port_count += 1

        # First handle all PFs
        for bdf_dev in mlnx_bdf_devices:
            rdma_bond_bdf = None

            # Only first slave interface in a bond has infiniband information on his sysfs
            if bdf_dev.bond_master != "=N/A=" and bdf_dev.bond_master != "ovs-system" and bdf_dev.rdma != "" :
                rdma_bond_bdf = MlnxRdmaBondDevice(bdf_dev.bdf, self._data_source, self._config)
                rdma_bond_bdf.get_data()

                bdf_dev.rdma = ""
                bdf_dev.lnk_state = ""

            if bdf_dev.sriov in ("PF", "PF" + self._config.warning_sign, "SF"):
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
                        hca = MlnxHCA(rdma_bond_bdf, self._config)
                        hca.add_bdf_dev(bdf_dev)
                    else:
                        hca = MlnxHCA(bdf_dev,  self._config)
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

                        hca = self._get_hca_by_sys_image_guid(parent_bdf_dev.sys_image_guid)
                        if hca is not None:
                            hca.add_bdf_dev(bdf_dev)
                        else:
                            raise Exception("VF " + str(bdf_dev) + " This device has no parent PF")

                    if parent_found:
                        break

        if self._config.show_warnings_and_errors:
            for hca in self.mlnxHCAs:
                hca.check_for_issues()

    def display_hcas_info(self):
        out = Output(self._config)
        for hca in self.mlnxHCAs:
            output_info = hca.output_info()
            out.append(output_info)

        out.print_output()

    def _get_hca_by_sys_image_guid(self, sys_image_guid):
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
                print("Error: Invalid pattern \"%s\" passed to output filter " % output_filter[filter_key])
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
            hca_fields_to_remove = {}
            bfb_fields_to_remove = {}
            bdf_devices_to_remove = []

            # ---- Removing SRIOV and Parent_addr if no VFs present
            bfb_fields_to_remove["SRIOV"] = True
            bfb_fields_to_remove["Parent_addr"] = True
            # ---- Remove LnkStaWidth if it matches LnkCapWidth
            bfb_fields_to_remove["LnkStaWidth"] = True
            # ---- Remove Port if all values are 1
            bfb_fields_to_remove["Port"] = True
            # ---- Remove IpStat if all LnkStat are down
            bfb_fields_to_remove["IpStat"] = True
            # ---- Remove LnkStat if all are actv
            bfb_fields_to_remove["LnkStat"] = True
            # ---- Remove bond related fields if no bond configured
            bfb_fields_to_remove["Bond"] = True
            bfb_fields_to_remove["BondState"] = True
            bfb_fields_to_remove["BondMiiStat"] = True
            # ---- Remove PhyAnalisys if there are no issues
            bfb_fields_to_remove["PhyAnalisys"] = True
            # ---- Remove LLDP fields if the interface in not Eth
            bfb_fields_to_remove["LLDPportId"] = True
            bfb_fields_to_remove["LLDPsysName"] = True
            bfb_fields_to_remove["LLDPmgmtAddr"] = True
            bfb_fields_to_remove["LLDPsysDescr"] = True

            for bdf_device in hca["bdf_devices"]:
                # ---- Removing SRIOV and Parent_addr if no VFs present
                if bdf_device.get("SRIOV") and bdf_device.get("SRIOV").strip() != "PF" and \
                  bdf_device.get("SRIOV").strip() != "PF" + self.config.warning_sign:
                    bfb_fields_to_remove["SRIOV"] = False
                    if bdf_device.get("SRIOV").strip() == "VF":
                        bfb_fields_to_remove["Parent_addr"] = False

                # ---- Remove LnkStaWidth if it matches LnkCapWidth
                if bdf_device.get("LnkStaWidth"):
                    field_value = bdf_device.get("LnkStaWidth").strip()
                    if re.search(re.escape(self.config.error_sign) + "$", field_value) or \
                            re.search(re.escape(self.config.warning_sign) + "$", field_value):
                        bfb_fields_to_remove["LnkStaWidth"] = False

                # ---- Remove Port if all values are 1
                if bdf_device.get("Port") and bdf_device.get("Port").strip() != "1":
                    bfb_fields_to_remove["Port"] = False

                # ---- Remove IpStat if all LnkStat are down
                if bdf_device.get("LnkStat") and bdf_device.get("LnkStat").strip() != "down":
                    bfb_fields_to_remove["IpStat"] = False

                # ---- Remove LnkStat if all are actv
                if bdf_device.get("LnkStat") and ( \
                  ( bdf_device.get("LnkStat").strip() != "actv" and ( bdf_device.get("Bond") == "" or bdf_device.get("Bond") == "=N/A=" ) ) or \
                  ( bdf_device.get("LnkStat").strip() != "" and ( bdf_device.get("Bond") != "" and bdf_device.get("Bond") != "=N/A=" ) )
                  ):
                    bfb_fields_to_remove["LnkStat"] = False

                # ---- Remove bond related fields if no bond configured
                if bdf_device.get("Bond") and bdf_device.get("Bond").strip() != "=N/A=" and bdf_device.get("Bond").strip() != 'ovs-system':
                    bfb_fields_to_remove["Bond"] = False
                    bfb_fields_to_remove["BondState"] = False
                    bfb_fields_to_remove["BondMiiStat"] = False

                # ---- Remove PhyAnalisys if there are no issues
                if bdf_device.get("PhyAnalisys") and bdf_device.get("PhyAnalisys") != "No_issue":
                    bfb_fields_to_remove["PhyAnalisys"] = False

                # ---- Remove whole BDF device if it part of DPU and LnkStat is nop
                if hca.get("DPUmode") != "" and bdf_device["LnkStat"] == "nop":
                    bdf_devices_to_remove.append(hca["bdf_devices"].index(bdf_device))

                # ---- Remove LLDP fields if the interface in not Eth
                if bdf_device.get("Link") == "Eth":
                    bfb_fields_to_remove["LLDPportId"] = False
                    bfb_fields_to_remove["LLDPsysName"] = False
                    bfb_fields_to_remove["LLDPmgmtAddr"] = False
                    bfb_fields_to_remove["LLDPsysDescr"] = False


            for field,do_remove in bfb_fields_to_remove.items():
                for bdf_device in hca["bdf_devices"]:
                    if field in bdf_device and do_remove:
                        del bdf_device[field]


            ### HCA wide filters below
            # ---- Remove DPUmode if it has no value
            if hca.get("DPUmode") == "":
                hca_fields_to_remove["DPUmode"] = True

                # ---- Remove BFBver if it has no value and the HCA is not DPU
                if hca.get("BFBver") == "":
                    hca_fields_to_remove["BFBver"] = True

            for field,do_remove in hca_fields_to_remove.items():
                if field in hca and do_remove:
                    del hca[field]


            ### Remove filtered our BDFs
            bdf_devices_to_remove.sort(reverse=True)
            for index in bdf_devices_to_remove:
                del hca["bdf_devices"][index]


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

        print(self.separator)
        for hca in self.output:
            self.print_hca_header(hca)
            print(self.separator)
            self.print_bdf_devices(hca["bdf_devices"])
            print(self.separator)

    def print_output_json(self):
        print(json.dumps(self.output, indent=4, sort_keys=True))

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
            print('\n'.join(output_list))

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
                print(' | '.join(output_list))
                print(self.separator)

            for key in line:
                if key in order_dict:
                    field_value = str("{0:^{width}}".format(line[key], width=self.column_width[key]))
                    field_value = self.colour_warnings_and_errors(field_value)
                    output_list = output_list[0:order_dict[key]] + [field_value] + \
                                   output_list[order_dict[key] + 1:]

            count += 1
            print(' | '.join(output_list))


class MSTDevice(object):
    mst_device_enabled = False
    mst_service_initialized = False
    mst_service_should_be_stopped = False

    def __init__(self, data_source, config):
        self._config = config
        self._data_source = data_source
        self._mst_raw_data = None

        self.mst_device = ""
        self.mst_cable = ""

    def __del__(self):
        if MSTDevice.mst_service_should_be_stopped:
            self._data_source.exec_shell_cmd("mst stop", use_cache=True)
            MSTDevice.mst_service_should_be_stopped = False

    def __repr__(self):
        return self._mst_raw_data

    def init_mst_service(self):
        if MSTDevice.mst_service_initialized:
            return

        result = self._data_source.exec_shell_cmd("which mst &> /dev/null ; echo $?", use_cache=True)
        if result == ["0"]:
            mst_installed = True
        else:
            mst_installed = False

        if mst_installed:
            result = self._data_source.exec_shell_cmd("mst status | grep -c 'MST PCI configuration module loaded'", use_cache=True)
            if int(result[0]) == 0:
                self._data_source.exec_shell_cmd("mst start", use_cache=True)
                MSTDevice.mst_service_should_be_stopped = True
            self._data_source.exec_shell_cmd("mst cable add", use_cache=True)
            MSTDevice.mst_device_enabled = True
        else:
            print("\n\nError: MST tool is missing\n\n", file=sys.stderr)
            # Disable further use.access to mst device
            self._config.mst_device_enabled = False

        MSTDevice.mst_service_initialized = True

    def get_data(self, bdf):
        if not MSTDevice.mst_device_enabled:
            return

        mst_device_suffix = "None"
        self._mst_raw_data = self._data_source.exec_shell_cmd("mst status -v", use_cache=True)
        bdf_short = extract_string_by_regex(bdf, "0000:(.+)")
        if bdf_short == "=N/A=":
            bdf_short = bdf

        for line in self._mst_raw_data:
            data_line = extract_string_by_regex(line, "(.*" + bdf_short + ".*)")

            if data_line != "=N/A=":
                self.mst_device = extract_string_by_regex(data_line, r".* (/dev/mst/[^\s]+) .*")
                mst_device_suffix = extract_string_by_regex(data_line, r"/dev/mst/([^\s]+)")

        self.mst_cable = find_in_list(self._mst_raw_data, r"({}_cable_[^\s]+)".format(mst_device_suffix)).strip()


class PCIDevice(object):
    def __init__(self, bdf, data_source, config):
        self._bdf = bdf
        self._config = config
        self._data_source = data_source

    def get_data(self):
        self._data = self._data_source.exec_shell_cmd("lspci -vvvDnn -s" + self._bdf, use_cache=True)
        # Handling following string, taking reset of string after HCA type
        # 0000:01:00.0 Infiniband controller: Mellanox Technologies MT27700 Family [ConnectX-4]
        self.description = self.get_info_from_lspci_data("^[0-9].*", str(self._bdf) + "[^:]+: (.+?)(?= \[[a-f0-9]{4}:[a-f0-9]{4}\]|$)")
        self.sn = self.get_info_from_lspci_data("\[SN\].*", ".*:(.+)")
        self._pn = self.get_info_from_lspci_data("\[PN\].*", ".*:(.+)")
        self.revision = self.get_info_from_lspci_data("\[EC\].*", ".*:(.+)")
        self._lnkCapWidth = self.get_info_from_lspci_data("LnkCap:.*Width.*", ".*Width (x[0-9]+)")
        self._lnkStaWidth = self.get_info_from_lspci_data("LnkSta:.*Width.*", ".*Width (x[0-9]+)")
        self._lnkCapSpeed = self.get_info_from_lspci_data("LnkCap:.*Speed.*", ".*Speed ([0-9]+)")
        self._lnkStaSpeed = self.get_info_from_lspci_data("LnkSta:.*Speed.*", ".*Speed ([0-9]+)")
        self._pciGen = self.get_info_from_lspci_data(".*[Pp][Cc][Ii][Ee] *[Gg][Ee][Nn].*",
                                            ".*[Pp][Cc][Ii][Ee] *[Gg][Ee][Nn]([0-9]) +")
        self.pci_device_id = self.get_info_from_lspci_data("^[0-9].*", str(self._bdf) + ".*\[([a-f0-9]{4}:[a-f0-9]{4})\]")

        # self._pciGen and below speed IF statements here for backward compatibility of regression
        # they can be safely removed if all recorded sources will contain Speed
        if self._lnkCapSpeed:
            self.lnkCapWidth = str(self._lnkCapWidth) + " G" + self.pci_speed_to_pci_gen(self._lnkCapSpeed)
        else:
            self.lnkCapWidth = str(self.lnkCapWidth) + " G" + str(self.pciGen)

        if self._lnkStaSpeed:
            self.lnkStaWidth = str(self._lnkStaWidth) + " G" + self.pci_speed_to_pci_gen(self._lnkStaSpeed)
        else:
            self.lnkStaWidth = str(self._lnkStaWidth)


        if self._lnkCapWidth != self._lnkStaWidth and self._config.show_warnings_and_errors is True:
            self.lnkStaWidth = str(self.lnkStaWidth) + self._config.error_sign
        elif self._lnkCapSpeed != self._lnkStaSpeed and self._config.show_warnings_and_errors is True:
            self.lnkStaWidth = str(self.lnkStaWidth) + self._config.warning_sign


    def __repr__(self):
        delim = " "
        return "PCI device:" + delim +\
               self._bdf + delim + \
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
        search_result = find_in_list(self._data, search_regex)
        search_result = extract_string_by_regex(search_result, output_regex)
        return str(search_result).strip()

    @staticmethod
    def pci_speed_to_pci_gen(speed):
        if str(speed) == "2.5":
            gen = "1"
        elif str(speed) == "5":
            gen = "2"
        elif str(speed) == "8":
            gen = "3"
        elif str(speed) == "16":
            gen = "4"
        elif str(speed) == "32":
            gen = "5"
        elif str(speed) == "64":
            gen = "6"
        else:
            gen = "_unknown"
        return gen


class SYSFSDevice(object):
    def __init__(self, bdf, data_source, config, port=1, sf=""):
        self._bdf = bdf
        self._config = config
        self._data_source = data_source
        self._port = str(port)

        self._sys_prefix = "/sys/bus/pci/devices/" + self._bdf

        self.is_sf = False
        if sf:
            self._sys_prefix += "/" + sf
            self.is_sf = True

    def __repr__(self):
        delim = " "
        return "SYS device:" + delim +\
               self._bdf + delim + \
               self.sriov + delim + \
               self.vfParent + delim + \
               self.numa

    def get_data(self):

        self._data_source.log_debug(level=1, data="BDF:{} Port:{} SysFS path prefix:{}".format(self._bdf, self._port, self._sys_prefix ))
        vf_parent_file = self._data_source.read_link_if_exists(self._sys_prefix + "/physfn")
        if vf_parent_file != "":
            self.sriov = "VF"
            self.vfParent = extract_string_by_regex(vf_parent_file, ".*\/([0-9].*)")
        else:
            self.sriov = "PF"
            self.vfParent = "-"

        if self.is_sf:
            self.sriov = "SF"

        self.numa = self._data_source.read_file_if_exists(self._sys_prefix + "/numa_node").rstrip()
        if not self.numa and not self.is_sf:
            print("Warning: " + self._bdf + " has no NUMA assignment", file=sys.stderr)

        self.rdma = self._data_source.list_dir_if_exists(self._sys_prefix + "/infiniband/").rstrip()
        net_list = self._data_source.list_dir_if_exists(self._sys_prefix + "/net/")
        self.net = ""
        matched_net_list = []
        for net in net_list.split(" "):
            # the below code tries to identify which of the files has valid port number dev_id or dev_port
            # in mlx4 dev_port has the valid value, in mlx5 - dev_id
            # this solution mimics one in ibdev2netdev

            # Multiple network interfaces can be in mlx4 devices or in DPUs (representors)
            net_port_dev_id = self._data_source.read_file_if_exists(self._sys_prefix + "/net/" + net + "/dev_id")
            try:
                net_port_dev_id = int(net_port_dev_id, 16)
            except ValueError:
                net_port_dev_id = 0

            net_port_dev_port = self._data_source.read_file_if_exists(self._sys_prefix + "/net/" + net + "/dev_port")
            try:
                net_port_dev_port = int(net_port_dev_port)
            except ValueError:
                net_port_dev_port = 0

            if net_port_dev_id > net_port_dev_port:
                net_port = net_port_dev_id
            else:
                net_port = net_port_dev_port

            net_port += 1

            if str(net_port) == self._port:
                # similar regexes used in OvsVctl
                if re.match(r"^p\d+$", net) or re.match(r"^pf\d+hpf$", net) or re.match(r"^pf\d+vf\d+$", net):
                    continue
                matched_net_list.append(net)

        self.net = " ".join(matched_net_list)

        self.hca_type = self._data_source.read_file_if_exists(self._sys_prefix + "/infiniband/" + self.rdma + "/hca_type").rstrip()

        self.lnk_state = self._data_source.read_file_if_exists(self._sys_prefix + "/infiniband/" + self.rdma + "/ports/" +
                                                         self._port + "/state")
        self.lnk_state = extract_string_by_regex(self.lnk_state, "[0-9:]+ (.*)", "").lower()
        if self.lnk_state == "active":
            self.lnk_state = "actv"

        if self.lnk_state == "down":
            self.phys_state = self._data_source.read_file_if_exists(self._sys_prefix + "/infiniband/" + self.rdma +
                                                          "/ports/" + self._port + "/phys_state")
            self.phys_state = extract_string_by_regex(self.phys_state, "[0-9:]+ (.*)", "").lower()

            if self.phys_state == "polling":
                self.lnk_state = "poll"


        self.link_layer = self._data_source.read_file_if_exists(self._sys_prefix + "/infiniband/" + self.rdma +
                                                          "/ports/" + self._port + "/link_layer")
        self.link_layer = self.link_layer.rstrip()
        if self.link_layer == "InfiniBand":
            self.link_layer = "IB"
        elif self.link_layer == "Ethernet":
            self.link_layer = "Eth"

        self.fw = self._data_source.read_file_if_exists(self._sys_prefix + "/infiniband/" + self.rdma + "/fw_ver")
        self.fw = self.fw.rstrip()

        self.psid = self._data_source.read_file_if_exists(self._sys_prefix + "/infiniband/" + self.rdma + "/board_id")
        self.psid = self.psid.rstrip()

        self.port_rate = self._data_source.read_file_if_exists(self._sys_prefix + "/infiniband/" + self.rdma + "/ports/" +
                                                         self._port + "/rate")
        self.port_rate = extract_string_by_regex(self.port_rate, "([0-9]*) .*", "")
        if self.lnk_state == "down" and self._config.show_warnings_and_errors is True:
            self.port_rate = self.port_rate + self._config.warning_sign

        self.port_list = self._data_source.list_dir_if_exists(self._sys_prefix + "/infiniband/" + self.rdma + "/ports/").rstrip()
        self.port_list = self.port_list.split(" ")

        self.plid = self._data_source.read_file_if_exists(self._sys_prefix + "/infiniband/" + self.rdma +
                                                    "/ports/" + self._port + "/lid")
        try:
            self.plid = int(self.plid, 16)
        except ValueError:
            self.plid = ""
        self.plid = str(self.plid)

        self.smlid = self._data_source.read_file_if_exists(self._sys_prefix + "/infiniband/" + self.rdma +
                                                     "/ports/" + self._port + "/sm_lid")
        try:
            self.smlid = int(self.smlid, 16)
        except ValueError:
            self.smlid = ""
        self.smlid = str(self.smlid)

        full_guid = self._data_source.read_file_if_exists(self._sys_prefix + "/infiniband/" + self.rdma +
                                                    "/ports/" + self._port + "/gids/0")

        self.pguid = extract_string_by_regex(full_guid, "((:[A-Fa-f0-9]{4}){4})$", "").lower()
        self.pguid = re.sub(':', '', self.pguid)

        self.ib_net_prefix = extract_string_by_regex(full_guid, "^(([A-Fa-f0-9]{4}:){4})", "").lower()
        self.ib_net_prefix = re.sub(':', '', self.ib_net_prefix)

        self.has_smi = self._data_source.read_file_if_exists(self._sys_prefix + "/infiniband/" + self.rdma +
                                                       "/ports/" + self._port + "/has_smi")
        self.has_smi = self.has_smi.rstrip()
        if self.link_layer != "IB" or re.match('mlx4', self.rdma):
            self.virt_hca = "N/A"
        elif self.has_smi == "0":
            self.virt_hca = "Virt"
        elif self.has_smi == "1":
            self.virt_hca = "Phys"
        else:
            self.virt_hca = ""

        self.sys_image_guid = self._data_source.read_file_if_exists(self._sys_prefix + "/infiniband/" + self.rdma +
                                                              "/sys_image_guid").rstrip()

        self.bond_mii_status = self._data_source.read_file_if_exists(self._sys_prefix + "/net/" + self.net +
                                                              "/bonding_slave/mii_status").rstrip()
        self.bond_state = self._data_source.read_file_if_exists(self._sys_prefix + "/net/" + self.net +
                                                              "/bonding_slave/state").rstrip()

        self.operstate = self._data_source.read_file_if_exists("/sys/class/net/" + self.net + "/operstate").rstrip()
        self.ip_state = None
        if self.operstate == "up":
            # Implemented via shell cmd to avoid using non default libraries
            interface_data = self._data_source.exec_shell_cmd(" ip address show dev %s" % self.net)
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

        tmp = self._data_source.list_dir_if_exists(self._sys_prefix + "/net/" + self.net).split(" ")
        bond_master_dir = find_in_list(tmp, "upper_.*").rstrip()
        self.bond_master = extract_string_by_regex(bond_master_dir, "upper_(.*)$")

        if self.ip_state == "down" and ( self.lnk_state == "actv" or self.bond_state ) \
                and self._config.show_warnings_and_errors is True:
            self.ip_state = self.ip_state + self._config.error_sign
        if self.ip_state == "up_noip" and self._config.show_warnings_and_errors is True:
            self.ip_state = self.ip_state + self._config.warning_sign

        # ========== RoCE view only related variables ==========
        self.gtclass = None
        self.tcp_ecn = None
        self.rdma_cm_tos = None

        if self._config.output_view == "roce" or self._config.output_view == "all":
            self.gtclass = self._data_source.read_file_if_exists(self._sys_prefix + "/infiniband/" + self.rdma +
                                                           "/tc/1/traffic_class").rstrip()
            self.tcp_ecn = self._data_source.read_file_if_exists("/proc/sys/net/ipv4/tcp_ecn").rstrip()

            roce_tos_path_prefix = "/sys/kernel/config/rdma_cm/" + self.rdma
            roce_tos_path_prefix_cleanup = False
            try:
                if self._data_source.list_dir_if_exists(roce_tos_path_prefix) == "":
                    os.mkdir(roce_tos_path_prefix)
                    roce_tos_path_prefix_cleanup = True
                    self._data_source.list_dir_if_exists(roce_tos_path_prefix) # here to record dir if recording enabled
                self.rdma_cm_tos = self._data_source.read_file_if_exists(roce_tos_path_prefix +
                                                                   "/ports/1/default_roce_tos").rstrip()
                if roce_tos_path_prefix_cleanup:
                    os.rmdir(roce_tos_path_prefix)
            except OSError:
                self.rdma_cm_tos = "Failed to retrieve"

        self.traff_tx_bitps = "N/A"
        self.traff_rx_bitps = "N/A"
        self.packet_seq_err_per_sec = "N/A"

        # Read the SF config only once
        if self._port == "1":
            tmp = self._data_source.list_dir_if_exists(self._sys_prefix ).rstrip().split()
            self.sf_list = find_in_list(tmp, r'mlx5_core\.sf\.[0-9]+', return_only_first_group=False)
            if not self.sf_list:
                self.sf_list = []
        else:
            self.sf_list = []

    def get_traffic(self):
        # see https://community.mellanox.com/s/article/understanding-mlx5-linux-counters-and-status-parameters for more info about the counteres
        if self.lnk_state == "down":
            return

        try:
            self._prev_tx_bit = self._curr_tx_bit
            self._prev_rx_bit = self._curr_rx_bit
            self._prev_packet_seq_err = self._curr_packet_seq_err
            self._prev_timestamp = self._curr_timestamp
            # record suffix var used as a hack during lshca data recording , this creates 2 different paths that will be recorder seperately
            record_suffix = "__2"
        except AttributeError:
            record_suffix = "__1"

        # Using this to record data if requested
        self._curr_timestamp = self._data_source.exec_python_code("time.time()", "_" + self.rdma + record_suffix, use_cache=True)

        # Handle case when delay between 2 get_traffic executions is too short
        if hasattr(self, '_prev_timestamp') and (self._curr_timestamp - self._prev_timestamp) == 0 :
            time.sleep(0.1)
            self._curr_timestamp = self._data_source.exec_python_code("time.time()",  "_" + self.rdma + record_suffix)

        # Use of cache required in case there is a bond, bond and it's first interface has same driver information
        # If cache won't be used, bond interface overwrites readings of first interface - creating issues in recorded data and regreession
        # Cache takes record_suffix in to consediration
        self._curr_tx_bit = self._data_source.read_file_if_exists(self._sys_prefix + "/infiniband/" + self.rdma + "/ports/" +
                                                                     self._port + "/counters/port_xmit_data", record_suffix, use_cache=True)

        if self._curr_tx_bit:
            self._curr_tx_bit = int(self._curr_tx_bit) * 8 * 4
        else:
            self._curr_tx_bit = "N/A"

        self._curr_rx_bit = self._data_source.read_file_if_exists(self._sys_prefix + "/infiniband/" + self.rdma + "/ports/" +
                                                                     self._port + "/counters/port_rcv_data", record_suffix, use_cache=True)

        if self._curr_rx_bit:
            self._curr_rx_bit = int(self._curr_rx_bit) * 8 * 4
        else:
            self._curr_rx_bit = "N/A"

        self._curr_packet_seq_err = self._data_source.read_file_if_exists(self._sys_prefix + "/infiniband/" + self.rdma + "/ports/" +
                                                                     self._port + "/hw_counters/packet_seq_err", record_suffix, use_cache=True)

        if self._curr_packet_seq_err:
            self._curr_packet_seq_err = int(self._curr_packet_seq_err)
        else:
            self._curr_packet_seq_err = "N/A"

        try:
            # not handling counter rollover, this is too reare case
            self.traff_tx_bitps = (self._curr_tx_bit - self._prev_tx_bit) / (self._curr_timestamp - self._prev_timestamp)
            self.traff_tx_bitps = humanize_number(self.traff_tx_bitps)

            self.traff_rx_bitps = (self._curr_rx_bit - self._prev_rx_bit) / (self._curr_timestamp - self._prev_timestamp)
            self.traff_rx_bitps = humanize_number(self.traff_rx_bitps)

            self.packet_seq_err_per_sec = str((self._curr_packet_seq_err - self._prev_packet_seq_err) / (self._curr_timestamp - self._prev_timestamp))

        except (AttributeError,TypeError):
            pass


class SaSmpQueryDevice(object):
    def __init__(self,  data_source, config):
        self._data_source = data_source
        self._config = config

        self.sw_guid = ""
        self.sw_description = ""
        self.sm_guid = ""

    def get_data(self, rdma, port, smlid):
        self._port = port
        self._rdma = rdma
        self._smlid = smlid

        if "SMGuid" not in self._config.output_order:
            self._config.output_order.append("SMGuid")
        if "SwGuid" not in self._config.output_order:
            self._config.output_order.append("SwGuid")
        if "SwDescription" not in self._config.output_order:
            self._config.output_order.append("SwDescription")

        self.data = self._data_source.exec_shell_cmd("smpquery -C " + self._rdma + " -P " + self._port + " NI -D  0,1")
        self.sw_guid = self.get_info_from_sa_smp_query_data(".*SystemGuid.*", "\.+(.*)")
        self.sw_guid = extract_string_by_regex(self.sw_guid, "0x(.*)")

        self.data = self._data_source.exec_shell_cmd("smpquery -C " + self._rdma + " -P " + self._port + " ND -D  0,1")
        self.sw_description = self.get_info_from_sa_smp_query_data(".*Node *Description.*", "\.+(.*)")

        self.data = self._data_source.exec_shell_cmd("saquery SMIR -C " + self._rdma + " -P " + self._port + " " + self._smlid)
        self.sm_guid = self.get_info_from_sa_smp_query_data(".*GUID.*", "\.+(.*)")
        self.sm_guid = extract_string_by_regex(self.sm_guid, "0x(.*)")

    def get_info_from_sa_smp_query_data(self, search_regex, output_regex):
        search_result = find_in_list(self.data, search_regex)
        search_result = extract_string_by_regex(search_result, output_regex)
        return str(search_result).strip()


class MlxCable(object):
    def __init__(self, data_source):
        self._data_source = data_source

        self.cable_length = ""
        self.cable_pn = ""
        self.cable_sn = ""

    def get_data(self, mst_cable):
        if mst_cable == "":
            return
        data = self._data_source.exec_shell_cmd("mlxcables -d " + mst_cable, use_cache=True)
        self.cable_length = search_in_list_and_extract_by_regex(data, r'Length +:.*', r'Length +:(.*)').replace(" ", "")
        self.cable_pn = search_in_list_and_extract_by_regex(data, r'Part number +:.*', r'Part number +:(.*)').replace(" ", "")
        self.cable_sn = search_in_list_and_extract_by_regex(data, r'Serial number +:.*', r'Serial number +:(.*)').replace(" ", "")


class MlxLink(object):
    def __init__(self, data_source):
        self._data_source = data_source

        self.physical_link_recommendation = ""
        self.physical_link_speed = ""
        self.physical_link_status = ""

    def get_data(self, mst_device, port):
        if mst_device == "":
            return
        data = self._data_source.exec_shell_cmd("mlxlink -d {} -p {} --json".format(mst_device, port), use_cache=True)
        try:
            json_data = json.loads("".join(data))
        except (TypeError, ValueError):
            return

        if "result" in json_data and \
           "output" in json_data["result"]:
            if "Operational Info" in json_data["result"]["output"]:
                if "Physical state" in  json_data["result"]["output"]["Operational Info"]:
                   self.physical_link_status = json_data["result"]["output"]["Operational Info"]["Physical state"]
                if "Speed" in  json_data["result"]["output"]["Operational Info"]:
                    self.physical_link_speed = json_data["result"]["output"]["Operational Info"]["Speed"]
            if "Troubleshooting Info" in json_data["result"]["output"]:
                if "Recommendation" in json_data["result"]["output"]["Troubleshooting Info"]:
                    self.physical_link_recommendation = json_data["result"]["output"]["Troubleshooting Info"]["Recommendation"]
                    self.physical_link_recommendation = self.physical_link_recommendation.replace(" ", "_")

                    if self.physical_link_recommendation == "No_issue_was_observed.":
                        self.physical_link_recommendation = "No_issue"

class MlxConfig(object):
    def __init__(self, data_source):
        self._data_source = data_source

        self.internal_cpu_model = ""
        self.internal_cpu_page_supplier = ""
        self.internal_cpu_eswitch_manager = ""
        self.internal_cpu_cpu_ib_vport0 = ""
        self.internal_cpu_offload_engine = "    "

    def get_data(self, mst_device):
        if mst_device == "":
            return

        # all of MST devices on single HCA point to the same configuration source
        # this will reduce execution time
        normalised_mst_device = re.sub(r'(.*)\.[0-9]', r'\1', mst_device)

        data = self._data_source.exec_shell_cmd("mlxconfig -d {} q".format(normalised_mst_device), use_cache=True)
        self.internal_cpu_model = search_in_list_and_extract_by_regex(data, r'.*INTERNAL_CPU_MODEL.*', r'.*\((.*)\)')
        self.internal_cpu_page_supplier = search_in_list_and_extract_by_regex(data, r'.*INTERNAL_CPU_PAGE_SUPPLIER.*', r'.*\((.*)\)')
        self.internal_cpu_eswitch_manager = search_in_list_and_extract_by_regex(data, r'.*INTERNAL_CPU_ESWITCH_MANAGER.*', r'.*\((.*)\)')
        self.internal_cpu_cpu_ib_vport0 = search_in_list_and_extract_by_regex(data, r'.*INTERNAL_CPU_IB_VPORT0.*', r'.*\((.*)\)')
        self.internal_cpu_offload_engine = search_in_list_and_extract_by_regex(data, r'.*INTERNAL_CPU_OFFLOAD_ENGINE.*', r'.*\((.*)\)')

class MlxPrivHost(object):
    def __init__(self, data_source):
        self._data_source = data_source

        self.restric_level = ""

    def get_data(self, mst_device):
        if mst_device == "":
            return

        # all of MST devices on single HCA point to the same configuration source
        # this will reduce execution time
        normalised_mst_device = re.sub(r'(.*)\.[0-9]', r'\1', mst_device)

        data = self._data_source.exec_shell_cmd("mlxprivhost -d {} q".format(normalised_mst_device), use_cache=True)
        tmp = search_in_list_and_extract_by_regex(data, r'^level +: [A-Z]+', r'.*: ([A-Z]+)')
        self.restric_level = tmp.lower()

class OvsVsctl(object):
    def __init__(self, data_source):
        self._data_source = data_source

        self.ovs_bridge = ""
        self.uplnk_repr = ""
        self.pf_repr = ""
        self.vf_repr = ""

    def get_data(self, net):
        data = {}
        ovsvctl_list_br = self._data_source.exec_shell_cmd("ovs-vsctl list-br", use_cache=True)
        for bridge in ovsvctl_list_br:
            ovsvctl_list_ports = self._data_source.exec_shell_cmd("ovs-vsctl list-ports {}".format(bridge), use_cache=True)
            data[bridge] = ovsvctl_list_ports

        ovs_bridge = ""
        uplnk_repr = ""
        pf_repr = ""
        vf_repr = ""

        bridge_found = False
        for bridge in data:
            ovs_bridge = bridge
            for br_net in data[bridge]:
                if br_net == net:
                    bridge_found = True
                # similar regexes used in SYSFSDevice
                if re.match(r"^p\d+$", br_net):
                    uplnk_repr = br_net
                if re.match(r"^pf\d+hpf$", br_net):
                    pf_repr = br_net
                if re.match(r"^pf\d+vf\d+$", br_net):
                    vf_repr = br_net
            if bridge_found:
                break

        if bridge_found:
            self.ovs_bridge = ovs_bridge
            self.uplnk_repr = uplnk_repr
            self.pf_repr = pf_repr
            self.vf_repr = vf_repr

class MiscCMDs(object):
    def __init__(self, data_source, config):
        self.data_source = data_source
        self.config = config

    def get_mlnx_qos_trust(self, net):
        data = self.data_source.exec_shell_cmd("mlnx_qos -i " + net, use_cache=True)
        regex = "Priority trust state: (.*)"
        search_result = find_in_list(data, regex)
        search_result = extract_string_by_regex(search_result, regex)
        return search_result

    def get_mlnx_qos_pfc(self, net):
        data = self.data_source.exec_shell_cmd("mlnx_qos -i " + net, use_cache=True)
        regex = '^\s+enabled\s+(([0-9]\s+)+)'
        search_result = find_in_list(data, regex)
        search_result = extract_string_by_regex(search_result, regex).replace(" ", "")
        return search_result

    def get_tempr(self, rdma):
        data = self.data_source.exec_shell_cmd("mget_temp -d " + rdma, use_cache=True)
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

    def get_driver_ver(self):
        mofed_ver = str(self.data_source.exec_shell_cmd("ofed_info -s ", use_cache=True))
        regex = '.*MLNX_OFED_LINUX-(.*):.*'
        mofed_ver = extract_string_by_regex(mofed_ver, regex)
        if mofed_ver != "=N/A=":
            return "mlnx_ofed-" + mofed_ver

        inbox_ver = self.data_source.exec_shell_cmd("modinfo mlx5_core", use_cache=True)
        regex = '^version:\s+([0-9].*)'
        search_result = find_in_list(inbox_ver, regex)
        search_result = extract_string_by_regex(search_result, regex)
        if search_result:
            return "inbox-" + str(search_result)
        else:
            return "N/A"

    def get_bfb_version(self):
        ver = self.data_source.read_file_if_exists("/etc/mlnx-release", use_cache=True)
        return ver.strip()


class MlnxBDFDevice(object):
    def __init__(self, bdf, data_source, config, port=1, sf=""):
        self.bdf = bdf
        self._config = config
        self._data_source = data_source

        self._inside_dpu = False

        self._sysFSDevice = SYSFSDevice(self.bdf, self._data_source, self._config, port, sf)
        self._pciDevice = PCIDevice(self.bdf, self._data_source, self._config)
        self._mstDevice = MSTDevice(self._data_source, self._config)
        self._mlxLink = MlxLink(self._data_source)
        self._mlxCable = MlxCable(self._data_source)
        self._mlxConfig = MlxConfig(self._data_source)
        self._mlxPrivHost = MlxPrivHost(self._data_source)
        self._ovsVsctl = OvsVsctl(self._data_source)
        self._miscDevice = MiscCMDs(self._data_source, self._config)
        self._sasmpQueryDevice = SaSmpQueryDevice(self._data_source, self._config)
        self._lldpData = LldpData(self._data_source, self._config)

    def get_data(self):
        self._get_if_inside_dpu(self._data_source.exec_shell_cmd("lspci -Dd 15b3:", use_cache=True))

        # ------ SysFS ------
        self._sysFSDevice.get_data()
        self.fw = self._sysFSDevice.fw
        self.hca_type = self._sysFSDevice.hca_type
        self.ib_net_prefix = self._sysFSDevice.ib_net_prefix
        self.link_layer = self._sysFSDevice.link_layer
        self.ip_state = self._sysFSDevice.ip_state
        self.pguid = self._sysFSDevice.pguid
        self.port = self._sysFSDevice._port
        self.port_list = self._sysFSDevice.port_list
        self.port_rate = self._sysFSDevice.port_rate
        self.plid = self._sysFSDevice.plid
        self.net = self._sysFSDevice.net
        self.numa = self._sysFSDevice.numa
        self.rdma = self._sysFSDevice.rdma
        self.smlid = self._sysFSDevice.smlid
        self.lnk_state = self._sysFSDevice.lnk_state
        self.virt_hca = self._sysFSDevice.virt_hca
        self.vfParent = self._sysFSDevice.vfParent
        self.sys_image_guid = self._sysFSDevice.sys_image_guid
        self.psid = self._sysFSDevice.psid
        self.bond_master = self._sysFSDevice.bond_master
        self.bond_state = self._sysFSDevice.bond_state
        self.bond_mii_status = self._sysFSDevice.bond_mii_status
        if self._config.output_view == "traffic" or self._config.output_view == "all":
            self._sysFSDevice.get_traffic()
        self.traff_tx_bitps = self._sysFSDevice.traff_tx_bitps
        self.traff_rx_bitps = self._sysFSDevice.traff_rx_bitps
        self.packet_seq_err_per_sec = self._sysFSDevice.packet_seq_err_per_sec
        self.sf_list = self._sysFSDevice.sf_list

        # ------ PCI ------
        self._pciDevice.get_data()
        self.description = self._pciDevice.description
        self.lnkCapWidth = self._pciDevice.lnkCapWidth
        self.lnkStaWidth = self._pciDevice.lnkStaWidth
        self.pci_device_id = self._pciDevice.pci_device_id

        if self.sriov == "VF":
            self.lnkCapWidth = ""
            self.lnkStaWidth = ""
        self.pn = self._pciDevice.pn
        self.sn = self._pciDevice.sn

        # ------ MST ------
        if self._config.output_view == "cable" or \
          self._config.output_view == "dpu" or \
          self._config.mst_device_enabled or \
          self._config.output_view == "all":
            self._mstDevice.init_mst_service()
            self._mstDevice.get_data(self.bdf)
            if self._config.output_view != "dpu" and "MST_device" not in self._config.output_order:
                self._config.output_order.append("MST_device")
        self.mst_device = self._mstDevice.mst_device
        self.mst_cable = self._mstDevice.mst_cable

        # ------ MLX link ------
        if self._config.output_view == "cable" or self._config.output_view == "all":
            self._mlxLink.get_data(self.mst_device, self.port)
        self.physical_link_speed = self._mlxLink.physical_link_speed
        self.physical_link_status = self._mlxLink.physical_link_status
        self.physical_link_recommendation = self._mlxLink.physical_link_recommendation

        # ------ MLX Cable ------
        if self._config.output_view == "cable" or self._config.output_view == "all":
            self._mlxCable.get_data(self.mst_cable)
        self.cable_length = self._mlxCable.cable_length
        self.cable_pn = self._mlxCable.cable_pn
        self.cable_sn = self._mlxCable.cable_sn

        # ------ MLX Config ------
        if self._is_dpu() and (self._config.output_view == "dpu" or self._config.output_view == "all"):
            self._mlxConfig.get_data(self.mst_device)
        self.internal_cpu_model = self._mlxConfig.internal_cpu_model
        self.internal_cpu_page_supplier = self._mlxConfig.internal_cpu_page_supplier
        self.internal_cpu_eswitch_manager = self._mlxConfig.internal_cpu_eswitch_manager
        self.internal_cpu_cpu_ib_vport0 = self._mlxConfig.internal_cpu_cpu_ib_vport0
        self.internal_cpu_offload_engine = self._mlxConfig.internal_cpu_offload_engine

        # ------ MLX PrivHost ------
        if self._is_dpu() and (self._config.output_view == "dpu" or self._config.output_view == "all"):
            self._mlxPrivHost.get_data(self.mst_device)
        self.restric_level = self._mlxPrivHost.restric_level

        # ------ Misc ------
        self.tempr = self._miscDevice.get_tempr(self.rdma)
        self.driver_ver = self._miscDevice.get_driver_ver()
        self.bfb_ver = self._miscDevice.get_bfb_version()

        # ------ SA/SMP query ------
        if self._config.sa_smp_query_device_enabled:
            self._sasmpQueryDevice.get_data(self.rdma, self.port, self.smlid)
        self.sw_guid = self._sasmpQueryDevice.sw_guid
        self.sw_description = self._sasmpQueryDevice.sw_description
        self.sm_guid = self._sasmpQueryDevice.sm_guid

        # ------ Traffic ------
        if self._config.output_view == "traffic" or self._config.output_view == "all":
        # If traffic requested, get the reading for the second time.
        # Doing it at the end of the function lets some time to passs between 2 readings
            self._sysFSDevice.get_traffic()
            self.traff_tx_bitps = self._sysFSDevice.traff_tx_bitps
            self.traff_rx_bitps = self._sysFSDevice.traff_rx_bitps
            self.packet_seq_err_per_sec = self._sysFSDevice.packet_seq_err_per_sec

        # ------ OVS Vctl ------
        if self._inside_dpu and (self._config.output_view == "dpu" or self._config.output_view == "lldp" or self._config.output_view == "all"):
            self._ovsVsctl.get_data(self.net)
        self.ovs_bridge = self._ovsVsctl.ovs_bridge
        self.pf_repr = self._ovsVsctl.pf_repr
        self.vf_repr = self._ovsVsctl.vf_repr
        self.uplnk_repr = self._ovsVsctl.uplnk_repr

        # ------ LLDP ------
        if ( self._config.output_view == "lldp" or self._config.output_view == "all" ) and \
            self.net != self.bond_master and \
          ( \
            ( self.sriov == "PF" and self.link_layer == "Eth" ) or \
            # Handle second interface in the bond, it has no self.link_layer value
            ( self.sriov == "PF" and self.bond_master != "=N/A=" and self.bond_master != "") \
          ):
            if self._inside_dpu and self.uplnk_repr:
                self._lldpData.get_data(self.uplnk_repr, self.ip_state)
            else:
                self._lldpData.get_data(self.net, self.ip_state)

        self.llpd_port_id = self._lldpData.port_id
        self.llpd_system_name =  self._lldpData.system_name
        self.llpd_system_description = self._lldpData.system_description
        self.llpd_mgmt_addr = self._lldpData.mgmt_addr

    def _is_dpu(self):
        # This function decides on well known Mellanox PCI ids taken from the https://pci-ids.ucw.cz/read/PC/15b3
        # it comes to eliminate usage of slow mlxconfig and mlxprivhost utils on non dpu HCAs
        # all BF DPUs start with a2xx or c2xx
        if self.pci_device_id.startswith("15b3:a2") or self.pci_device_id.startswith("15b3:c2"):
            return True
        else:
            return False

    def _get_if_inside_dpu(self, pci_tree):
        for bdf in pci_tree:
            result = extract_string_by_regex(bdf, "(0000:00:00.0) (.+)")
            if result != "=N/A=":
                self._inside_dpu = True
                return


    def __repr__(self):
        return self._sysFSDevice.__repr__() + "\n" + self._pciDevice.__repr__() + "\n" + \
                self._mstDevice.__repr__() + "\n"

    @property
    def sriov(self):
        if self._config.show_warnings_and_errors is True and self._sysFSDevice.sriov == "PF" and \
                re.match(r".*[Vv]irtual [Ff]unction.*", self._pciDevice.description):
            return self._sysFSDevice.sriov + self._config.warning_sign
        else:
            return self._sysFSDevice.sriov

    @property
    def roce_status(self):
        if self.link_layer == "IB" or not ( self._config.output_view == "roce" or self._config.output_view == "all"):
            return "N/A"

        lossy_status_bitmap_str = ""

        bond_slave = False
        if self.bond_master != "=N/A=" and self.bond_master != "":
            bond_slave = True

        if type(self) != MlnxBDFDevice:
            lossy_status_bitmap_str += "_"
        elif self._miscDevice.get_mlnx_qos_trust(self.net) == self._config.lossless_roce_expected_trust:
            lossy_status_bitmap_str += "1"
        else:
            lossy_status_bitmap_str += "0"

        if type(self) != MlnxBDFDevice:
            lossy_status_bitmap_str += "_"
        elif self._miscDevice.get_mlnx_qos_pfc(self.net) == self._config.lossless_roce_expected_pfc:
            lossy_status_bitmap_str += "1"
        else:
            lossy_status_bitmap_str += "0"

        if bond_slave:
            lossy_status_bitmap_str += "_"
        elif self._sysFSDevice.gtclass == self._config.lossless_roce_expected_gtclass:
            lossy_status_bitmap_str += "1"
        else:
            lossy_status_bitmap_str += "0"

        if self._sysFSDevice.tcp_ecn == self._config.lossless_roce_expected_tcp_ecn:
            lossy_status_bitmap_str += "1"
        else:
            lossy_status_bitmap_str += "0"

        if bond_slave:
            lossy_status_bitmap_str += "_"
        elif self._sysFSDevice.rdma_cm_tos == self._config.lossless_roce_expected_rdma_cm_tos:
            lossy_status_bitmap_str += "1"
        else:
            lossy_status_bitmap_str += "0"

        if re.compile('^[1_]+$').match(lossy_status_bitmap_str):
            retval = "Lossless"
        elif re.compile('^[0_]+$').match(lossy_status_bitmap_str):
            retval = "Lossy"
        else:
            retval = "Lossy:" + lossy_status_bitmap_str
            if self._config.show_warnings_and_errors is True:
                return retval + self._config.warning_sign

        return retval

    @property
    def dpu_mode(self):
        if not self._is_dpu():
            return ""

        mode = "Undefined"

        if self.internal_cpu_model == "1":
            if self.internal_cpu_page_supplier == "1" and \
              self.internal_cpu_eswitch_manager == "1" and \
              self.internal_cpu_cpu_ib_vport0 == "1" and \
              self.internal_cpu_offload_engine == "1":
                mode = "NIC"
            elif self.internal_cpu_page_supplier == "0" and \
              self.internal_cpu_eswitch_manager == "0" and \
              self.internal_cpu_cpu_ib_vport0 == "0" and \
              self.internal_cpu_offload_engine == "0":
                if self.restric_level == "privileged":
                    mode = "ECPF"
                elif self.restric_level == "restricted":
                    mode = "RestrHost"
        elif self.internal_cpu_model == "0":
            mode = "Separated"

        return mode

    def get_traff(self):
        self.sysFSDevice.get_traffic()
        self.traff_tx_bitps = self.sysFSDevice.traff_tx_bitps
        self.traff_rx_bitps = self.sysFSDevice.traff_rx_bitps

    def output_info(self):
        if self.sriov in ("PF", "PF" + self._config.warning_sign):
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
                  "BondMiiStat": self.bond_mii_status,
                  "PhyLinkStat": self.physical_link_status ,
                  "PhyLnkSpd": self.physical_link_speed,
                  "CblPN": self.cable_pn,
                  "CblSN": self.cable_sn,
                  "CblLng": self.cable_length,
                  "PhyAnalisys": self.physical_link_recommendation,
                  "TX_bps": self.traff_tx_bitps,
                  "RX_bps": self.traff_rx_bitps,
                  "PktSeqErr": self.packet_seq_err_per_sec,
                  "LLDPportId": self.llpd_port_id,
                  "LLDPsysName": self.llpd_system_name,
                  "LLDPsysDescr": self.llpd_system_description,
                  "LLDPmgmtAddr": self.llpd_mgmt_addr,
                  "OvsBrdg" : self.ovs_bridge,
                  "PfRepr" : self.pf_repr,
                  "VfRepr" : self.vf_repr,
                  "UplnkRepr" : self.uplnk_repr
                  }
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
        self.driver_ver = bdf_dev.driver_ver
        self.psid = bdf_dev.psid
        self.sys_image_guid = bdf_dev.sys_image_guid
        self.description = bdf_dev.description
        self.tempr = bdf_dev.tempr
        self.dpu_mode = bdf_dev.dpu_mode
        self.bfb_ver = bdf_dev.bfb_ver
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
                    break
        else:
            self.bdf_devices.append(new_bdf_dev)

    def output_info(self):
        output = {"SN": self.sn,
                  "PN": self.pn,
                  "FW": self.fw,
                  "Driver": self.driver_ver,
                  "PSID": self.psid,
                  "Desc": self.description,
                  "Tempr": self.tempr,
                  "Dev": self.hca_index,
                  "DPUmode": self.dpu_mode,
                  "BFBver": self.bfb_ver,
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
    def get_data(self):
        #Using python2 super notation for cross version compatability
        super(MlnxRdmaBondDevice, self).get_data()
        self._fix_rdma_bond()

    def _fix_rdma_bond(self):
        index = extract_string_by_regex(self.rdma, ".*([0-9]+)$")
        self.bdf = "rdma_bond_" + index
        self.net = self.bond_master
        self.bond_master = ""
        self.bond_mii_status = ""
        self.ip_state = None
        self.mst_device = ""
        self.cable_length = ""
        self.cable_pn = ""
        self.cable_sn = ""
        self.physical_link_speed = ""
        self.physical_link_recommendation = ""
        self.physical_link_status = ""
        self.llpd_port_id = ""
        self.llpd_system_name =  ""
        self.llpd_system_description = ""
        self.llpd_mgmt_addr  = ""

        sys_prefix = "/sys/devices/virtual/net/" + self.net

        operstate = self._data_source.read_file_if_exists(sys_prefix + "/operstate").rstrip()
        if operstate == "up":
            # Implemented via shell cmd to avoid using non default libraries
            interface_data = self._data_source.exec_shell_cmd(" ip address show dev %s" % self.net)
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
                and self._config.show_warnings_and_errors is True:
            self.ip_state = self.ip_state + self._config.error_sign
        if self.ip_state == "up_noip" and self._config.show_warnings_and_errors is True:
            self.ip_state = self.ip_state + self._config.warning_sign

        mode = self._data_source.read_file_if_exists(sys_prefix + "/bonding/mode").rstrip()
        mode = mode.split(" ")[0]
        xmit_hash_policy = self._data_source.read_file_if_exists(sys_prefix + "/bonding/xmit_hash_policy").rstrip()
        xmit_hash_policy = xmit_hash_policy.split(" ")[0]
        xmit_hash_policy = xmit_hash_policy.replace("layer","l")
        xmit_hash_policy = xmit_hash_policy.replace("encap","e")

        self.bond_state = mode
        if xmit_hash_policy != "" :
            self.bond_state = self.bond_state + "/" + xmit_hash_policy

        # Slaves speed check
        slaves = self._data_source.read_file_if_exists(sys_prefix + "/bonding/slaves").rstrip().split(" ")
        bond_speed = ""
        bond_speed_missmatch = False
        for slave in slaves:
            slave_speed = self._data_source.read_file_if_exists(sys_prefix + "/slave_" + slave + "/speed").rstrip()
            if slave_speed:
                slave_speed = str(int(int(slave_speed)/1000))
            if self.port_rate != slave_speed:
                bond_speed_missmatch = True

            if bond_speed == "":
                bond_speed = slave_speed
            else:
                bond_speed = bond_speed + "/" + slave_speed

        self.port_rate = bond_speed

        if bond_speed_missmatch:
            if self._config.show_warnings_and_errors is True:
                self.port_rate  = self.port_rate + self._config.error_sign


class ifreq(ctypes.Structure):
    _fields_ = [("ifr_ifrn", ctypes.c_char * 16),
                ("ifr_flags", ctypes.c_short)]


class LldpData:
    LLDP_ETHER_PROTO = 0x88CC       # LLDP ehternet protocol number

    LLDP_TLV_TYPE_BITMASK = int(0b1111111000000000) # first 7 bits of 2 bytes
    LLDP_TLV_LENGTH_BITMASK = int(0b0000000111111111) # last 9 bits of 2 bytes
    LLDP_TLV_TYPE_SHIFT = 9

    def __init__(self, data_source, config):
        self._config = config
        self._data_source = data_source
        self._interface = None
        self._packet = None
        self._raw_socket = None
        self._tlv = {}

        self.port_id = ""
        self.mgmt_addr = ""
        self.system_name = ""
        self.system_description = ""

    def parse_lldp_packet(self, rcvd_packet):
        # Packet example
        # (b'\x01\x80\xc2\x00\x00\x0e\xb8Y\x9f\xa9\x9c`\x88\xcc\x02\x07\x04\xb8Y\x9f\xa9\x9c\x00\x04\x07\x05Eth1/1\x06\x02\x00x\x08\x01 \n\tanc-dx-t1\x0c\x18MSN3700,Onyx,SWv3.9.0914\x0e\x04\x00\x14\x00\x04\x10\x16\x05\x01\n\x90\xfc\x85\x02\x00\x00\x00\x00\n+\x06\x01\x02\x01\x02\x02\x01\x01\x00\xfe\x19\x00\x80\xc2\t\x08\x00\x03\x00`2\x00\x002\x00\x00\x00\x00\x02\x02\x02\x02\x02\x02\x00\x02\xfe\x19\x00\x80\xc2\n\x00\x00\x03\x00`2\x00\x002\x00\x00\x00\x00\x02\x02\x02\x02\x02\x02\x00\x02\xfe\x06\x00\x80\xc2\x0b\x08\x08\xfe\x08\x00\x80\xc2\x0c\x00c\x12\xb7\x00\x00', ('ens1f0', 35020, 2, 1, b'\xb8Y\x9f\xa9\x9c`'))
        if rcvd_packet:
            payload = rcvd_packet[0] # taking the binary part of the tuple
            meta = rcvd_packet[1]
        else:
            return

        if meta[0] != self._interface:
            self.lldp_err_msg("InterfaceMismatch", self._config.error_sign)
            return

        ether_payload = None
        # this loop comes to skip vlan and similar encapsulation headers.
        # By RFC they should not exist in LLDP packes, but in reality they do in some cases.
        for i in range(12, 50):
            ether_type = struct.unpack("!H", payload[i:(i + 2)])[0]
            if hex(ether_type) == hex(self.LLDP_ETHER_PROTO):
                ether_payload = payload[(i + 2):] # Eternet payload starts after Ether type
                break
        if ether_payload == None:
            print("Failed to parce ethernet frame. Exititng")
            sys.exit(1)

        i = 0
        while i < len(ether_payload):
            tlv_header = struct.unpack("!H", ether_payload[i:i+2])[0]
            tlv_type = ( int(tlv_header) & self.LLDP_TLV_TYPE_BITMASK ) >> self.LLDP_TLV_TYPE_SHIFT
            tlv_len = int(tlv_header) & self.LLDP_TLV_LENGTH_BITMASK

            tlv_value = ether_payload[i+2:i+2+tlv_len]
            i += 2 + tlv_len

            self._tlv[tlv_type] = tlv_value

        try:
            # [1:] is hack to skip \x05 in port id string
            self.port_id = self._tlv[2][1:].decode("utf-8")
        except:
            self.port_id = "Fail2Decode"

        try:
            self.system_name = self._tlv[5].decode("utf-8")
        except:
            self.system_name = "Fail2Decode"

        if 6 in self._tlv:
            try:
                self.system_description = self._tlv[6].decode("utf-8")
            except:
                self.system_description = "Fail2Decode"

        if 8 in self._tlv:
            try:
                # TBD: add idetification of IPv type and take length in to consediration
                self.mgmt_addr = socket.inet_ntoa(self._tlv[8][2:6])
            except:
                self.mgmt_addr = "Fail2Decode"

    def lldp_err_msg(self, msg, sign):
        if self._config.show_warnings_and_errors is True:
            msg += sign
        self.port_id = msg
        self.system_name =  msg
        self.system_description = msg
        self.mgmt_addr = msg

    def get_data(self, net, ip_state):
        if sys.version_info[0] < 3:
            raise Exception("Getting LLDP data requires Python3")

        self._interface = net

        if ip_state == "" or net == "":
            self.lldp_err_msg("LnkStatUnclr", self._config.warning_sign)
            return

        if ip_state.startswith("down"):
            self.lldp_err_msg("LnkDown", self._config.warning_sign)
            return

        packet = self._data_source.get_raw_socket_data(net, self.LLDP_ETHER_PROTO, self._config.lldp_capture_timeout, use_cache=True)
        if packet:
            if str(packet) == "TimeoutError":
                self.lldp_err_msg("NoLldpRcvd", self._config.error_sign)
                return
            else:
                self.parse_lldp_packet(packet)


class DataSource(object):
    def __init__(self, config):
        self.cache = {}
        self.config = config
        self.interfaces_struct = []
        if self.config.record_data_for_debug is True:
            if not os.path.exists(self.config.record_dir):
                os.makedirs(self.config.record_dir)

            self.config.record_tar_file = "%s/%s--%s--%s--v%s.tar" % (self.config.record_dir, os.uname()[1], str(self.config.output_view).upper(),
                                                                  str(time.time()), self.config.ver)

            print("\nlshca started data recording")
            print("output saved in " + self.config.record_tar_file + " file\n")

            self.stdout = StringIO()
            sys.stdout = self.stdout

    def __del__(self):
        if self.config.record_data_for_debug is True:
            sys.stdout = sys.__stdout__
            try:
                args_str = " ".join(sys.argv[1:])
            except:
                args_str = ""
            self.record_data("cmd", "lshca " + args_str)
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
            self.record_data("output_fields", self.config.output_order)

    def log_debug(self, level, data):
        if self.config.debug >= level:
            print("DEBUG{}: {}".format(level, data))

    def exec_shell_cmd(self, cmd, use_cache=False):
        cache_key = self.cmd_to_str(cmd)

        if use_cache is True and cache_key in self.cache:
            output = self.cache[cache_key]

        else:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, executable="/bin/bash")
            output, error = process.communicate()
            if isinstance(output, bytes):
                output = output.decode()

            if use_cache is True:
                self.cache.update({cache_key: output})

        output = output.splitlines()
        if self.config.record_data_for_debug is True:
            cmd = "shell.cmd/" + cmd
            self.record_data(cmd, output)

        return output

    def record_data(self, cmd, output):
        p_output = pickle.dumps(output)

        if sys.version_info.major == 3:
            tar_contents = BytesIO(p_output)
        else:
            tar_contents = StringIO(p_output)

        file_name = cmd

        tarinfo = tarfile.TarInfo(file_name)
        tarinfo.size = len(p_output)
        tarinfo.mtime = time.time()

        tar = tarfile.open(name=self.config.record_tar_file, mode='a')
        tar.addfile(tarinfo, tar_contents)
        tar.close()

    def read_file_if_exists(self, file_to_read, record_suffix="", use_cache=False):
        cache_key = self.cmd_to_str(str(file_to_read) + str(record_suffix))

        if use_cache is True and cache_key in self.cache:
            output = self.cache[cache_key]
        else:
            if os.path.exists(file_to_read):
                f = open(file_to_read, "r")
                try:
                    output = f.read()
                except (IOError, TypeError) as exception:
                    print("Driver error: failed to read {}".format(file_to_read), file=sys.stderr)
                    output = ""
                except Exception as e:
                    print("\n\nFailed to read file" + str(file_to_read) + "\n\n")
                    raise
                f.close()
            else:
                output = ""

            if use_cache is True:
                self.cache.update({cache_key: output})

        if self.config.record_data_for_debug is True:
            cmd = "os.path.exists" + file_to_read + record_suffix
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

    def exec_python_code(self, python_code, record_suffix="", use_cache=False):
        cache_key = self.cmd_to_str(str(python_code) + str(record_suffix))

        if use_cache is True and cache_key in self.cache:
            output = self.cache[cache_key]
        else:
            output = eval(python_code)

            if use_cache is True:
                self.cache.update({cache_key: output})

        if self.config.record_data_for_debug is True:
            cmd = "os.python.code/" + hashlib.md5(python_code.encode('utf-8')).hexdigest() + record_suffix
            self.record_data(cmd, output)

        return output

    def get_raw_socket_data(self, interface, ether_proto, capture_timeout, use_cache=True):
        cache_key = self.cmd_to_str(str(interface) + str(ether_proto))

        if use_cache is True and cache_key in self.cache:
            output = self.cache[cache_key]
        else:
            try:
                raw_socket = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ether_proto))
            except socket.error as e:
                    print('Socket could not be created. {}'.format(e))
                    sys.exit()

            try:
                raw_socket.bind((interface, ether_proto))
                self.interfaces_struct.append({"interface":interface, "socket": raw_socket})
                self._set_interface_promisc_status(interface, raw_socket, True)
            except Exception as e:
                print("Tried connecting interface '{}'".format(interface))
                raise e

            signal.signal(signal.SIGINT, self.signal_recieved)
            signal.signal(signal.SIGALRM, self.signal_recieved)
            signal.alarm(capture_timeout)

            try:
                output = raw_socket.recvfrom(65565)
            except TimeoutError:
                output = "TimeoutError"

            signal.alarm(0)
            self._set_interface_promisc_status(interface, raw_socket, False)
            self.interfaces_struct.remove({"interface":interface, "socket": raw_socket})
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            signal.signal(signal.SIGALRM, signal.SIG_DFL)

            if use_cache is True:
                self.cache.update({cache_key: output})

        if self.config.record_data_for_debug is True:
            cmd = "raw.socket.data/" + cache_key
            self.record_data(cmd, output)

        return output

    def signal_recieved(self, signal_number, stack_frame):
        interfaces_affected = ""
        for int_str in self.interfaces_struct:
            self._set_interface_promisc_status(int_str["interface"], int_str["socket"], False)
            interfaces_affected += " " + str(int_str["interface"])

        # SIGALRM = 14
        if signal_number == 14:
            raise TimeoutError
        else:
            print("\nSignal '{}' recieved. Interfaces {} set as non-promisc. Exiting".format(signal_number, interfaces_affected), file=sys.stderr)
            sys.exit(1)

    def _set_interface_promisc_status(self, interface, raw_socket, promisc):
        IFF_PROMISC = 0x100             # Set interface promiscuous
        SIOCGIFFLAGS = 0x8913           # Get flags  SIOC G IF FLAGS
        SIOCSIFFLAGS = 0x8914           # Set flags  SIOC S IF FLAGS

        ifr = ifreq()
        ifr.ifr_ifrn = interface.encode('UTF-8')

        fcntl.ioctl(raw_socket.fileno(), SIOCGIFFLAGS, ifr)
        if promisc:
            ifr.ifr_flags |= IFF_PROMISC # Add promisc flag
        else:
            ifr.ifr_flags &= ~IFF_PROMISC # Remove promisc flag
        fcntl.ioctl(raw_socket.fileno(), SIOCSIFFLAGS, ifr) # S for Set

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


def find_in_list(list_to_search_in, regex_pattern, return_only_first_group=True):
    regex = re.compile(regex_pattern)
    result = [m.group(0) for l in list_to_search_in for m in [regex.search(l)] if m]

    if result:
        if return_only_first_group:
            return result[0]
        else:
            return result
    else:
        return ""

def search_in_list_and_extract_by_regex(data_list, search_regex, output_regex):
    list_search_result = find_in_list(data_list, search_regex)
    regex_search_result = extract_string_by_regex(list_search_result, output_regex)
    return str(regex_search_result).strip()

def humanize_number(num, precision=1):
    abbrevs = (
        (10 ** 15, 'P'),
        (10 ** 12, 'T'),
        (10 ** 9, 'G'),
        (10 ** 6, 'M'),
        (10 ** 3, 'K'),
        (1, '')
    )
    if num == 1:
        return '1'
    for factor, suffix in abbrevs:
        if num >= factor:
            break
    return '%.*f%s' % (precision, num / factor, suffix)

def get_lshca_version():
    # used by setup.py for automatic version identification
    config = Config()
    return config.ver

def main():
    if os.geteuid() != 0:
        sys.exit("You need to have root privileges to run this script")

    config = Config()
    config.parse_arguments(sys.argv[1:])

    data_source = DataSource(config)

    hca_manager = HCAManager(data_source, config)
    hca_manager.get_data()

    hca_manager.display_hcas_info()


if __name__ == "__main__":
    main()
