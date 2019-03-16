#!/usr/bin/env python2

from lshca import *
import tempfile
import shutil
import difflib


class DataSourceRecorded(DataSource):
    @staticmethod
    def read_cmd_output_from_file(cmd_prefix, cmd):
        file_to_read = config.record_dir + cmd_prefix + cmd
        f = open(file_to_read, "rb")
        output = pickle.load(f)
        return output

    def exec_shell_cmd(self, cmd, use_cache=False):
        # use_cache is here for compatibility only
        output = self.read_cmd_output_from_file("/shell.cmd/", cmd)
        return output

    def read_file_if_exists(self, file_to_read):
        output = self.read_cmd_output_from_file("/os.path.exists/", file_to_read)
        return output

    def read_link_if_exists(self, link_to_read):
        output = self.read_cmd_output_from_file("/os.readlink/", link_to_read)
        return output

    def list_dir_if_exists(self, dir_to_list):
        output = self.read_cmd_output_from_file("/os.listdir/", dir_to_list.rstrip('/') + "_dir")
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


def main(tmp_dir_name, recorder_sys_argv):
    if os.geteuid() != 0:
        exit("You need to have root privileges to run this script")

    # Comes to handle missing TTY during regression
    config.override__set_tty_exists = True
    config.parse_arguments(recorder_sys_argv[1:])
    config.record_data_for_debug = False
    config.record_dir = tmp_dir_name

    data_source = DataSourceRecorded()

    hca_manager = HCAManager(data_source)

    hca_manager.display_hcas_info()


def regression():
    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('-v', action='store_true', dest="verbose", help="set high verbosity")
    parser.add_argument('-p', dest="parameters", nargs=argparse.REMAINDER,
                        help=textwrap.dedent('''\
                                override saved parameters and pass new ones
                                this parameter HAS to be the LAST one
                                '''))
    args = parser.parse_args(sys.argv[1:])

    recorded_data_files_list = os.listdir("recorded_data")
    tmp_dir_name = tempfile.mkdtemp(prefix="lshca_regression_")
    regression_run_succseeded = True

    if len(recorded_data_files_list) != 0:
        for recorded_data_file in recorded_data_files_list:

            shutil.copyfile("recorded_data/" + recorded_data_file, tmp_dir_name + "/" + recorded_data_file)

            tar = tarfile.open(tmp_dir_name + "/" + recorded_data_file)
            tar.extractall(path=tmp_dir_name)

            if args.parameters:
                recorder_sys_argv = args.parameters[0].split(" ")
                recorder_sys_argv.insert(0, "lshca_run_by_regression")
            else:
                f = open(tmp_dir_name + "/cmd", "r")
                recorder_sys_argv = pickle.load(f)
                recorder_sys_argv = recorder_sys_argv.split(" ")

            stdout = StringIO.StringIO()
            sys.stdout = stdout
            try:
                main(tmp_dir_name, recorder_sys_argv)
                output = stdout
            except Exception as e:
                output = e
            finally:
                sys.stdout = sys.__stdout__

            print '**************************************************************************************'
            print BColors.BOLD + 'Recorded data file: ' + str(recorded_data_file) + BColors.ENDC
            print '**************************************************************************************'
            try:
                test_output = output.getvalue()
            except AttributeError:
                regression_run_succseeded = False
                print "Regression run " + BColors.FAIL + "FAILED." + BColors.ENDC + "\n"
                print output
                continue

            f = open(tmp_dir_name + "/output", "rb")
            saved_output = pickle.load(f)

            if test_output != saved_output:
                regression_run_succseeded = False
                print "Regression run " + BColors.FAIL + "FAILED." + BColors.ENDC + \
                      " Saved and regression outputs differ\n"

                d = difflib.Differ()
                diff = d.compare(saved_output.split("\n"), test_output.split("\n"))
                print '\n'.join(diff)
            else:
                print "Regression run " + BColors.OKGREEN + "PASSED." + BColors.ENDC
                if args.verbose:
                    print BColors.OKBLUE + "Test output below:" + BColors.ENDC
                    print test_output

        shutil.rmtree(tmp_dir_name)

        if not regression_run_succseeded:
            sys.exit(1)


if __name__ == "__main__":
    regression()
