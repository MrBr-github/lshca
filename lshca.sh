#!/bin/bash

# This script comes to help running lshca cli without installation
# One of the use cases: HPC cluster with shared NFS

params="$@"
self_dir=$( cd "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )
if result=$(python2 --version 2>&1) ; then
  python2 ${self_dir}/lshca/cli.py ${params}
elif result=$(python3 --version 2>&1) ; then
  PYTHONPATH=$PYTHONPATH:${self_dir}  python3 -m lshca.cli ${params}
elif result=$(python --version 2>&1) ; then
  if [ $(echo ${result} | awk -F '[ \.]' '{print $3}') == "2" ] ; then
    python2 ${self_dir}/lshca/cli.py ${params}
  else
    PYTHONPATH=$PYTHONPATH:${self_dir}  python3 -m lshca.cli ${params}
  fi
fi

