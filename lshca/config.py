# Description: Part of lshca library
#
# Author: Michael Braverman
# Project repo: https://github.com/MrBr-github/lshca
# License: This utility provided under GNU GPLv3 license

from __future__ import print_function


class Config(object):
    QPRESET_SYSTEM = "system"
    QPRESET_IB = "ib"
    QPRESET_ROCE = "roce"
    QPRESET_MST = "mst"

    def __init__(self):
        self.debug = False

        self.query_preset = {
            self.QPRESET_SYSTEM: True,
            self.QPRESET_IB: False,
            self.QPRESET_ROCE: False,
            self.QPRESET_MST: False
        }

        self.show_warnings_and_errors = True

        self.warning_sign = "*"
        self.error_sign = " >!<"

        self.record_data_for_debug = False
        self.record_dir = "/tmp/lshca"
        self.record_tar_file = None

        self._ver = "4.0"

        self._lossless_roce_expected_trust = "dscp"
        self._lossless_roce_expected_pfc = "00010000"
        self._lossless_roce_expected_gtclass = "Global tclass=106"
        self._lossless_roce_expected_tcp_ecn = "1"
        self._lossless_roce_expected_rdma_cm_tos = "106"

    @property
    def ver(self):
        return self._ver