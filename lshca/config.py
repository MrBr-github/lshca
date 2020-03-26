import argparse
import textwrap
import sys


class Config(object):
    def __init__(self):
        self.debug = False

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
        self.show_warnings_and_errors = True
        self.colour_warnings_and_errors = True
        self.warning_sign = "*"
        self.error_sign = " >!<"

        self.record_data_for_debug = False
        self.record_dir = "/tmp/lshca"
        self.record_tar_file = None

        self.ver = "3.0"

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
                         lshca.sh -j -s mst -o \"-SN\"
                         lshca.sh -o \"Dev,Port,Net,PN,Desc,RDMA\" -ow \"RDMA=mlx5_[48]\"

                        '''))

        parser.add_argument('-hh', action='store_true', dest="extended_help",
                            help="show extended help message and exit. All fields description and more")
        parser.add_argument('-d', action='store_true', dest="debug", help="run with debug outputs")
        parser.add_argument('-j', action='store_true', dest="json",
                            help="output data as JSON, affected by output selection flag")
        parser.add_argument('-of', choices=["human_readable", "json", "module"], dest="output_format",
                            help="set output format.")
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

        """)
        sys.exit(0)
