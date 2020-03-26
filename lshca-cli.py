#!/usr/bin/env python2

# Description: This utility comes to provide bird's-eye view of HCAs installed.
#              It's mainly intended for system administrators, thus defaults configured accordingly.
# Author: Michael Braverman
# Email: mrbr.mail@gmail.com
# Project repo: https://gitlab.com/MrBr-gitlab/lshca/
# License: This utility provided under GNU GPLv3 license

import lshca

from __future__ import print_function
import json
import re
import sre_constants
import sys


class BColors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


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


def main():
    try:
        hca_manager = lshca.HCAManager()
    except OSError as e:
        exit(e.message)

    config = lshca.Config()
    out = Output(config)
    for hca in hca_manager.mlnx_hcas:
        output_info = hca.output_info()
        out.append(output_info)

    out.print_output()


if __name__ == "__main__":
    main()
