# Description: This utility comes to provide bird's-eye view of HCAs installed.
#              It's mainly intended for system administrators, thus defaults configured accordingly.
# Author: Michael Braverman
# Project repo: https://github.com/MrBr-github/lshca
# License: This utility provided under GNU GPLv3 license

from __future__ import print_function
import argparse
import json
import re
import sre_constants
import sys
import textwrap

if sys.version_info.major == 3:
    from .hca_manager import HCAManager
    from .config import Config
else:
    from hca_manager import HCAManager
    from config import Config


class BColors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


class CliConfig(object):
    def __init__(self, config):
        self.lib_config = config

        self.output_view = "system"
        self.output_order_general = {
            "system": ["Dev", "Desc", "PN", "PSID", "SN", "FW", "PCI_addr", "RDMA", "Net", "Port", "Numa", "LnkStat",
                       "IpStat", "Link", "Rate", "SRIOV", "Parent_addr", "Tempr", "LnkCapWidth", "LnkStaWidth",
                       "HCA_Type"],
            "ib": ["Dev", "Desc", "PN", "PSID", "SN", "FW", "RDMA", "Port", "Net", "Numa", "LnkStat", "IpStat",
                   "VrtHCA", "PLid", "PGuid", "IbNetPref"],
            "roce": ["Dev", "Desc", "PN", "PSID", "SN", "FW", "PCI_addr", "RDMA", "Net", "Port", "Numa", "LnkStat",
                     "IpStat", "RoCEstat"]
        }
        self.output_order = self.output_order_general[self.output_view]
        self.colour_warnings_and_errors = True

        self.output_format = "human_readable"
        self.output_format_elastic = None
        self.output_separator_char = "-"
        self.output_fields_filter_positive = ""
        self.output_fields_filter_negative = ""
        self.where_output_filter = ""

        self.ver = "1.0"

    def parse_arguments(self, user_args):
        parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter,
                                         epilog=textwrap.dedent('''\
                     Output warnings and errors:
                         In some cases warning and error signs will be shown. They highlight obvious issues
                         Warnings and errors won't be visible in JSON output and/or if the output is not to terminal
                          ''' + self.lib_config.warning_sign + '''  == Warning.
                         Example: speed of disabled port might be 10G, where the actual port speed is 100G
                         ''' + self.lib_config.error_sign + '''  == Error.
                         Example: HCA requires x16 PCI lanes, but only x8 available in the slot

                     examples:
                         lshca.sh -j -s mst -o \"-SN\"
                         lshca.sh -o \"Dev,Port,Net,PN,Desc,RDMA\" -ow \"RDMA=mlx5_[48]\"

                        '''))

        parser.add_argument("-hh", action="store_true", dest="extended_help",
                            help="show extended help message and exit. All fields description and more")
        parser.add_argument("-d", action="store_true", dest="debug", help="run with debug outputs")
        parser.add_argument("-j", action="store_true", dest="json",
                            help="output data as JSON, affected by output selection flag")
        parser.add_argument("-of", choices=["human_readable", "json", "module"], dest="output_format",
                            help="set output format.")
        parser.add_argument("-v", "--version", action="version", version=str(
                              "lshca cli ver. %s\nlshca lib ver. %s" % (self.ver, self.lib_config.ver)))
        parser.add_argument("-m", choices=["normal", "record"], default="normal", dest="mode",
                            help=textwrap.dedent('''\
                            mode of operation (default: %(default)s):
                              normal - list HCAs
                              record - record all data for debug and lists HCAs\
                            '''))
        parser.add_argument("-w", choices=["system", "ib", "roce", "all"], default="system", dest="view",
                            help=textwrap.dedent('''\
                            show output view (default: %(default)s):
                              system - (default). Show system oriented HCA info
                              ib     - Show IB oriented HCA info. Implies "sasmpquery" data source
                              roce   - Show RoCE oriented HCA info"
                              all    - Show all available HCA info. Aggregates all above views + MST data source.
                              Note: all human readable output views are elastic. See extended help for more info.
                            ''')
                            )
        parser.add_argument("--non-elastic", action="store_false", dest="elastic",
                            help="Set human readable output as non elastic")
        parser.add_argument("--no-colour", "--no-color", action="store_false", dest="colour",
                            help="Do not colour warrinings and errors.")
        parser.add_argument("-s", choices=["lspci", "sysfs", "mst", "sasmpquery"], nargs="+", dest="sources",
                            help=textwrap.dedent('''\
                            add optional data sources (comma delimited list)
                            always on data sources are:
                              lspci    - provides lspci utility based info. Requires root for full output 
                              sysfs    - provides driver based info retrieved from /sys/
                            optional data sources:
                              mst        - provides MST based info. This data source slows execution
                              sasmpquery - provides SA/SMP query based info of the IB network
                            '''))
        parser.add_argument("-o", dest="output_fields_filter_positive", nargs="+",
                            help=textwrap.dedent('''\
                            SELECT fields to output (comma delimited list). Use field names as they appear in output
                            '''))
        parser.add_argument("-onot", dest="output_fields_filter_negative", nargs="+",
                            help=textwrap.dedent('''\
                            REMOVE fields from default output (comma delimited list).
                            Use field names as they appear in output. -o takes precedence
                            '''))
        parser.add_argument("-ow", dest="output_fields_value_filter", nargs="+",
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
            self.lib_config.record_data_for_debug = True

        if args.debug:
            self.lib_config.debug = True

        if args.view == "ib":
            self.lib_config.query_preset[self.lib_config.QPRESET_IB] = True
            self.output_view = "ib"
        elif args.view == "roce":
            self.lib_config.query_preset[self.lib_config.QPRESET_ROCE] = True
            self.output_view = "roce"
        elif args.view == "system":
            self.output_view = "system"
        elif args.view == "all":
            self.lib_config.query_preset[self.lib_config.QPRESET_IB] = True
            self.lib_config.query_preset[self.lib_config.QPRESET_ROCE] = True
            self.lib_config.query_preset[self.lib_config.QPRESET_MST] = True
            self.output_view = "all"

        if self.output_view != "all":
            self.output_order = self.output_order_general[self.output_view]
        else:
            for i, view in enumerate(self.output_order_general):
                if i == 0:
                    self.output_order = self.output_order_general[view]
                else:
                    for key in self.output_order_general[view]:
                        if key not in self.output_order:
                            self.output_order.append(key)

        if args.json:
            self.output_format = "json"
            self.lib_config.show_warnings_and_errors = False

        if args.sources:
            for data_source in args.sources:
                if data_source == "lspci":
                    pass
                elif data_source == "sysfs":
                    pass
                elif data_source == "mst":
                    self.lib_config.query_preset[self.lib_config.QPRESET_MST] = True
                    if "MST_device" not in self.output_order:
                        self.output_order.append("MST_device")

                elif data_source == "sasmpquery":
                    self.lib_config.query_preset[self.lib_config.QPRESET_IB] = True

        if self.lib_config.query_preset[self.lib_config.QPRESET_IB]:
            if "SMGuid" not in self.output_order:
                self.output_order.append("SMGuid")
            if "SwGuid" not in self.output_order:
                self.output_order.append("SwGuid")
            if "SwDescription" not in self.output_order:
                self.output_order.append("SwDescription")

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
        print(textwrap.dedent("""
        --== Detailed fields description ==--
        Note: BDF is a Bus-Device-Function PCI address. Each HCA port/vf has unique BDF.

        HCA header:
          Dev   - Device number. Enumerated value padded with #
          Desc  - HCA description as appears in lspci output
          FW    - HCA currently running firmware version
          PN    - HCA part number including revision
          SN    - HCA serial number
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
                        ip_ipv4 - up/ipv4 addr. configured
                        ip_ipv6 - up/ipv6 addr. configured
                        ip_ipv6 - up/both ipv4 and ipv6 addr. configured

         System view
          HCA_Type      - Channel Adapter type, as appears in "ibstat"
          Link          - Link type. Possible values:
                            IB  - InfiniBand
                            Eth - Ethernet
          LnkCapWidth   - PCI width capability. Number of PCI lanes required by HCA. PF only.
          LnkStaWidth   - PCI width status. Number of PCI lanes avaliable for HCA in current slot. PF only.
          Parent_addr   - BDF address of SRIOV parent Physical Function for this Virtual Function
          Rate          - Link rate in Gbit/s
          SRIOV         - SRIOV function type. Possible values:
                            PF - Physical Function
                            VF - Virtual Function

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


        --== Elastic view rules ==--
        Elastic view comes to reduce excessive information in human readable output.
        Following will be removed per HCA if the condition is True
        SRIOV        - if all SRIOV are PF
        Parent_addr  - if all SRIOV are PF
        LnkStaWidth  - if LnkStaWidth matches LnkCapWidth
        Port         - if all Port values are 1
        LnkStat      - if all LnkStat valuse are "actv"
        IpStat       - if all LnkStat valuse are "down"

        """))
        sys.exit(0)


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
            hca_fields_for_removal = []
            remove_sriov_and_parent = True
            remove_lnk_sta_width = True
            remove_port = True
            remove_lnk_stat = True
            remove_ip_stat = True

            for bdf_device in hca["bdf_devices"]:
                # ---- Removing SRIOV and Parent_addr if no VFs present
                if "SRIOV" in bdf_device:
                    if bdf_device["SRIOV"].strip() != "PF" and \
                            bdf_device["SRIOV"].strip() != "PF" + self.config.lib_config.warning_sign:
                        remove_sriov_and_parent = False

                # ---- Remove LnkStaWidth if it matches LnkCapWidth
                if "LnkStaWidth" in bdf_device:
                    field_value = bdf_device["LnkStaWidth"].strip()
                    if re.search(re.escape(self.config.lib_config.error_sign) + "$", field_value):
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
                    if bdf_device["LnkStat"].strip() != "actv":
                        remove_lnk_stat = False

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

        self.update_separator_and_column_width()

        if self.separator_len == 0:
            sys.exit(1)

        if self.config.output_format == "human_readable":
            self.print_output_human_readable()
        elif self.config.output_format == "json":
            self.print_output_json()

    def colour_warnings_and_errors(self, field_value):
        if self.config.lib_config.show_warnings_and_errors and self.config.colour_warnings_and_errors:
            if re.search(re.escape(self.config.lib_config.error_sign) + "$", str(field_value).strip()):
                field_value = BColors.FAIL + field_value + BColors.ENDC
            elif re.search(re.escape(self.config.lib_config.warning_sign) + "$", str(field_value).strip()):
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


def main():
    lib_config = Config()
    cli_config = CliConfig(lib_config)
    cli_config.parse_arguments(sys.argv[1:])

    try:
        hca_manager = HCAManager(lib_config)
    except OSError as e:
        exit(e.message)

    out = Output(cli_config)
    for hca in hca_manager.mlnx_hcas:
        output_info = hca.output_info()
        out.append(output_info)

    out.print_output()


if __name__ == "__main__":
    main()
