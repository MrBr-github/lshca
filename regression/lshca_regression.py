#!/usr/bin/env python

from __future__ import print_function

import argparse
import difflib
import hashlib
import os
from pathlib import Path
import pickle
import re
import shutil
import sys
import tarfile
import tempfile
import textwrap
import traceback
from io import StringIO

from packaging import version

regr_home = os.path.dirname(os.path.abspath(__file__))
sys.path.append(regr_home + '/../')

import lshca


class DataSourceRecorded(lshca.DataSource):
    def read_cmd_output_from_file(self, cmd_prefix, cmd):
        output_file_to_read = self.config.record_dir + cmd_prefix + cmd
        try:
            f = open(output_file_to_read, "rb")
            output = pickle.load(f)
            error = ""
            if os.path.exists('{}__ERROR'.format(output_file_to_read)):
                f = open('{}__ERROR'.format(output_file_to_read), "rb")
                error = pickle.load(f)
        except IOError:
            if cmd and 'lspci -vvvDnn -s' in cmd:
                altered_cmd = cmd.replace('lspci -vvvDnn -s', 'lspci -vvvD -s')
                output, error = self.read_cmd_output_from_file(cmd_prefix, altered_cmd)
            elif cmd and 'lspci -vvvDnnd 15b3:' in cmd:
                # Used to identify mellanox bdfs in version < 3.9
                altered_cmd = cmd.replace('lspci -vvvDnnd 15b3:', 'lspci -Dd 15b3:')
                output, error = self.read_cmd_output_from_file(cmd_prefix, altered_cmd)
            elif self.config.skip_missing:
                output = ""
                error = ""
            else:
                raise

        return output, error

    def exec_shell_cmd(self, cmd, splitlines=True, **kwargs):
        # use_cache is here for compatibility only
        output, error = self.read_cmd_output_from_file("/shell.cmd/", cmd)
        if error:
            self.log.error('Following cmd returned and error message.\n\tCMD: {}\n\tMsg: {}'.format(cmd, error))

        # splitlines parameter added in version 3.9, before that everything was splitted and recorded in this state
        if version.parse(self.config.recorded_lshca_version) >= version.parse("3.9"):
            if splitlines:
                output = output.splitlines()

        return output

    def get_bdf_data_from_lspci(self, bdf, **kwargs):
        # type: (str, bool) -> dict
        if version.parse(self.config.recorded_lshca_version) >= version.parse("3.9"):
            output = super(DataSourceRecorded, self).get_bdf_data_from_lspci(bdf)
        else:
            # comes to compensate on missing get_bdf_data_from_lspci information in recordings by versions < 3.9
            output = self.exec_shell_cmd("lspci -vvvDnn -s" + bdf)
        return output

    def read_file_if_exists(self, file_to_read, record_suffix="", **kwargs):
        output, error = self.read_cmd_output_from_file("/os.path.exists/", file_to_read + record_suffix)
        if error:
            print(error, file=sys.stderr)
        return output

    def read_link_if_exists(self, link_to_read, **kwargs):
        output, error = self.read_cmd_output_from_file("/os.readlink/", link_to_read)
        if error:
            print(error, file=sys.stderr)
        return output

    def list_dir_if_exists(self, dir_to_list, **kwargs):
        output, error = self.read_cmd_output_from_file("/os.listdir/", dir_to_list.rstrip('/') + "_dir")
        if error:
            print(error, file=sys.stderr)
        return output

    def exec_python_code(self, python_code, record_suffix="", **kwargs):
        output, error = self.read_cmd_output_from_file("/os.python.code/", hashlib.md5(python_code.encode('utf-8')).hexdigest() + record_suffix)
        if error:
            print(error, file=sys.stderr)
        return output

    def get_raw_socket_data(self, interface, ether_proto, capture_timeout, **kwargs):
        cache_key = self.cmd_to_str(str(interface) + str(ether_proto))
        output, error = self.read_cmd_output_from_file("/raw.socket.data/", cache_key)
        if error:
            print(error, file=sys.stderr)
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


class RegressionConfig(lshca.Config):
    def __init__(self):
        self.skip_missing = False
        self.recorded_lshca_version = "0"
        super(RegressionConfig, self).__init__()


def main(tmp_dir_name, recorder_sys_argv, regression_conf):
    config = regression_conf

    # Comes to handle missing TTY during regression
    config.override__set_tty_exists = True
    config.parse_arguments(recorder_sys_argv[1:])
    config.record_data_for_debug = False
    config.record_dir = tmp_dir_name
    data_source = DataSourceRecorded(config)

    hca_manager = lshca.HCAManager(data_source, config)
    hca_manager.get_data()

    hca_manager.display_hcas_info()


def regression():
    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('-v', action='store_true', dest="verbose", help="set high verbosity")
    parser.add_argument('--skip-missing', action='store_true', dest="skip_missing",
                        help="skip missing data source files")
    parser.add_argument('--keep-recorded-ds', action='store_true', dest="keep_recorded_ds",
                        help="Don't delete recorded data source tmp directory")
    parser.add_argument('--display-only', choices=["orig", "curr"], dest="display_only",
                        help=textwrap.dedent('''\
                                instead of diff display only:
                                  orig - original data
                                  curr - current data
                                '''))
    parser.add_argument('--display-recorded-fields', action='store_true', help="Display ONLY originaly recorded fields. Overwrites -p")
    parser.add_argument('-p', dest="parameters", nargs=argparse.REMAINDER,
                        help=textwrap.dedent('''\
                                override saved parameters and pass new ones
                                this parameter HAS to be the LAST one
                                '''))

    # comes to handle comma separated list of choices
    cust_user_args = []
    for arg in sys.argv[1:]:
        result = arg.split(",")
        for member in result:
            cust_user_args.append(member)
    args = parser.parse_args(cust_user_args)

    recorded_data_files_list = load_case_files()

    if not recorded_data_files_list:
        print("WARNING: no test cases ran")
        sys.exit(0)

    tmp_dir_name = tempfile.mkdtemp(prefix="lshca_regression_")
    regression_run_succseeded = True
    for full_recorded_data_file in recorded_data_files_list:
        shutil.copyfile(
            str(full_recorded_data_file),
            str(Path(tmp_dir_name) / full_recorded_data_file.name)
        )
        untared_data_source_dir = Path(tmp_dir_name) / full_recorded_data_file.stem
        untared_data_source_dir.mkdir()

        tar = tarfile.open(str(Path(tmp_dir_name) / full_recorded_data_file.name))
        tar.extractall(path=str(untared_data_source_dir))

        if args.parameters:
            recorded_sys_args = args.parameters[0].split(" ")
            recorded_sys_args.insert(0, "lshca_run_by_regression")
        else:
            try:
                recorded_sys_args = pickle.loads((untared_data_source_dir / "cmd").read_bytes())
            except ValueError as e:
                print("\nFailed unpickling %s \n\n" % str(full_recorded_data_file.name))
                raise e

            recorded_sys_args = recorded_sys_args.split(" ")
            if args.display_recorded_fields:
                try:
                    recorded_output_fields = pickle.loads((untared_data_source_dir / "output_fields").read_bytes())
                except:
                    print(BColors.FAIL + "Error: No output fileds saved in "  + full_recorded_data_file.name + BColors.ENDC )
                    sys.exit(1)
                recorded_sys_args.append("-o")
                recorded_sys_args.append(",".join(recorded_output_fields))

        tmp = pickle.loads((untared_data_source_dir / "environment").read_bytes())
        for item in tmp:
            if 'LSHCA:' in item:
                recorded_lshca_version = item.split(" ")[1]
                break

        lshca_output, lshca_errors = StringIO(), StringIO()
        sys.stdout, sys.stderr = lshca_output, lshca_errors

        try:
            regression_conf = RegressionConfig()
            regression_conf.skip_missing = args.skip_missing
            regression_conf.recorded_lshca_version = recorded_lshca_version
            main(str(untared_data_source_dir), recorded_sys_args, regression_conf)
        except Exception as e:
            lshca_output = StringIO(str(e))
        finally:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__

        print('**************************************************************************************')
        print(BColors.BOLD + 'Recorded data file: ' + str(full_recorded_data_file) + BColors.ENDC)
        print("Command: " + " ".join(recorded_sys_args))
        print('**************************************************************************************')

        saved_output = load_saved_output(untared_data_source_dir)
        saved_errors = load_saved_errors(untared_data_source_dir)

        print(regression_conf.output_separator_char)
        test_errors = lshca_errors.getvalue()
        test_output = re.sub(regression_conf.output_separator_char, '', lshca_output.getvalue())
        saved_output = re.sub(regression_conf.output_separator_char, '', saved_output)

        if not do_compare(args, saved_errors, saved_output, test_errors, test_output):
            regression_run_succseeded = False

        print("\n")

    if not args.keep_recorded_ds:
        shutil.rmtree(tmp_dir_name)
    else:
        print("Data sources left in {} directory".format(tmp_dir_name))

    if not regression_run_succseeded:
        sys.exit(1)

def load_case_files():
    rec_data_dir_path = Path("recorded_data/")
    recorded_data_files_list = [p for p in rec_data_dir_path.glob('*.tar')]
    if sys.version_info.major == 3:
        recorded_data_files_list.extend([p for p in (rec_data_dir_path / "py3-only").glob('*.tar')])
    return recorded_data_files_list

def load_saved_errors(untared_data_source_dir):
    # recording of errors started from version 3.9
    # this comes to handle recordings with missing errors
    saved_errors = None
    err = untared_data_source_dir / "errors"
    if err.exists():
        try:
            saved_errors = pickle.loads(err.read_bytes())
        except ValueError as e:
            print("\nFailed unpickling %s \n\n" % str(err))
            raise e
    else:
        print("{}Warring{}: Missing recorded errors".format(BColors.WARNING, BColors.ENDC))
    return saved_errors

def load_saved_output(untared_data_source_dir):
    out = untared_data_source_dir / "output"
    try:
        saved_output = pickle.loads(out.read_bytes())
    except ValueError as e:
        print("\nFailed unpickling %s \n\n" % str(out))
        raise e
    return saved_output

def do_compare(args, saved_errors, saved_output, test_errors, test_output):
    passed = True

    outs_equal = test_output == saved_output
    errs_equal = test_errors == saved_errors if saved_errors else True
    if outs_equal and errs_equal:
        print("Regression run " + BColors.OKGREEN + "PASSED." + BColors.ENDC)
        if args.verbose:
            print(BColors.OKBLUE + "Test output below:" + BColors.ENDC)
            print(test_errors)
            print(test_output)
    else:
        passed = False
        print("Regression run " + BColors.FAIL + "FAILED." + BColors.ENDC + \
                    " Saved and regression outputs/errors differ\n")

        if not args.display_only:
            d = difflib.Differ()
            if saved_errors:
                diff = d.compare(saved_errors.split("\n"), test_errors.split("\n"))
                print('\n'.join(diff))
            diff = d.compare(saved_output.split("\n"), test_output.split("\n"))
            print('\n'.join(diff))
        elif args.display_only == "orig":
            print(saved_errors)
            print(saved_output)
        elif args.display_only == "curr":
            print(test_errors)
            print(test_output)
    return passed


if __name__ == "__main__":
    regression()
