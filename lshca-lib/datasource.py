from __future__ import print_function
import os
import sys
import StringIO
import subprocess
import pickle
import tarfile
import time
import re


class DataSource(object):
    def __init__(self, config):
        self.cache = {}
        self.config = config
        if self.config.record_data_for_debug is True:
            if not os.path.exists(self.config.record_dir):
                os.makedirs(self.config.record_dir)

                self.config.record_tar_file = "%s/%s--%s.tar" % (self.config.record_dir, os.uname()[1],
                                                                 str(time.time()))

            print("\nlshca started data recording")
            print("output saved in " + self.config.record_tar_file + " file\n")

            self.stdout = StringIO.StringIO()
            sys.stdout = self.stdout

    def __del__(self):
        if self.config.record_data_for_debug is True:
            sys.stdout = sys.__stdout__
            self.record_data("cmd", "lshca.sh " + " ".join(sys.argv[1:]))
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
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
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
